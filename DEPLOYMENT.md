# Deployment Guide - Face Recognition Attendance System

## Table of Contents
1. [Prerequisites](#prerequisites)
2. [Cloud Backend Deployment](#cloud-backend-deployment)
3. [Raspberry Pi Setup](#raspberry-pi-setup)
4. [Database Setup](#database-setup)
5. [Load Testing](#load-testing)
6. [Production Checklist](#production-checklist)

---

## Prerequisites

### Cloud Infrastructure
- **Compute**: 2× t3.medium EC2 instances (or equivalent)
- **Database**: PostgreSQL 14+ (RDS db.t3.small)
- **Cache**: Redis 7+ (ElastiCache)
- **Load Balancer**: ALB or nginx
- **Storage**: S3 bucket for backups
- **Monitoring**: CloudWatch / Prometheus + Grafana

### Raspberry Pi Hardware
- Raspberry Pi 4 Model B (4GB) or Pi 5 (8GB)
- Pi Camera Module 3 or USB webcam
- 64GB Samsung Endurance microSD card
- Cooling case (Argon NEO 5 recommended)
- Stable power supply (official 27W USB-C)

---

## Cloud Backend Deployment

### Step 1: Database Setup

```bash
# Connect to PostgreSQL
psql -h your-db-host -U postgres

# Create database
CREATE DATABASE attendance_db;

# Run schema
\i database/schema.sql

# Verify tables
\dt
```

### Step 2: Backend Application

```bash
cd backend

# Create virtual environment
python3.9 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
nano .env  # Edit with your values

# Run database migrations (if using Alembic)
alembic upgrade head

# Test locally
uvicorn app.main:app --reload

# Access docs at http://localhost:8000/docs
```

### Step 3: Production Deployment (Docker)

**Dockerfile:**
```dockerfile
FROM python:3.9-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY app/ ./app/

# Run with gunicorn
CMD ["gunicorn", "app.main:app", "-w", "4", "-k", "uvicorn.workers.UvicornWorker", "--bind", "0.0.0.0:8000"]
```

**docker-compose.yml:**
```yaml
version: '3.8'

services:
  backend:
    build: ./backend
    ports:
      - "8000:8000"
    environment:
      DATABASE_URL: postgresql://user:password@db:5432/attendance_db
      REDIS_URL: redis://redis:6379/0
    depends_on:
      - db
      - redis

  db:
    image: postgres:14
    environment:
      POSTGRES_DB: attendance_db
      POSTGRES_USER: user
      POSTGRES_PASSWORD: password
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./database/schema.sql:/docker-entrypoint-initdb.d/schema.sql

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"

  nginx:
    image: nginx:alpine
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf
    depends_on:
      - backend

volumes:
  postgres_data:
```

**Deploy:**
```bash
docker-compose up -d

# Check logs
docker-compose logs -f backend
```

### Step 4: nginx Load Balancer Configuration

**nginx.conf:**
```nginx
upstream backend {
    least_conn;
    server backend-1:8000 max_fails=3 fail_timeout=30s;
    server backend-2:8000 max_fails=3 fail_timeout=30s;
}

server {
    listen 80;
    server_name api.attendance.example.com;

    # Rate limiting
    limit_req_zone $binary_remote_addr zone=api_limit:10m rate=100r/m;
    limit_req zone=api_limit burst=20 nodelay;

    location / {
        proxy_pass http://backend;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_connect_timeout 30s;
        proxy_send_timeout 30s;
        proxy_read_timeout 30s;
    }

    location /health {
        proxy_pass http://backend;
        access_log off;
    }
}
```

---

## Raspberry Pi Setup

### Step 1: OS Installation

```bash
# Download Raspberry Pi OS Lite (64-bit)
# Flash to microSD using Raspberry Pi Imager

# First boot - update system
sudo apt update && sudo apt upgrade -y

# Install Python 3.9+
sudo apt install python3-pip python3-venv

# Install system dependencies
sudo apt install -y \
    libopencv-dev \
    python3-opencv \
    cmake \
    libboost-all-dev \
    libatlas-base-dev
```

### Step 2: Application Setup

```bash
# Clone repository (or copy files)
cd /home/pi
git clone https://github.com/your-org/attendance-system.git
cd attendance-system/pi_client

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
nano .env

# Required configuration:
# DEVICE_UUID=<generate UUID>
# DEVICE_NAME=PI-LAB301
# CLASSROOM_ID=LAB-301
# API_BASE_URL=https://api.attendance.example.com
# API_KEY=<your_api_key>
```

### Step 3: Test Camera

```bash
# Test camera module
python camera.py

# You should see video feed with face detection
# Press 'q' to quit
```

### Step 4: Create Systemd Service

**/etc/systemd/system/attendance.service:**
```ini
[Unit]
Description=Face Recognition Attendance System
After=network.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/attendance-system/pi_client
Environment="PATH=/home/pi/attendance-system/pi_client/venv/bin"
ExecStart=/home/pi/attendance-system/pi_client/venv/bin/python main.py
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

**Enable and start:**
```bash
sudo systemctl daemon-reload
sudo systemctl enable attendance.service
sudo systemctl start attendance.service

# Check status
sudo systemctl status attendance.service

# View logs
sudo journalctl -u attendance.service -f
```

### Step 5: Cooling and Performance

```bash
# Monitor CPU temperature
vcgencmd measure_temp

# Add to crontab for monitoring
crontab -e

# Add line:
*/5 * * * * vcgencmd measure_temp >> /home/pi/temp_log.txt
```

**If overheating (> 70°C):**
1. Ensure cooling case is properly installed
2. Add heatsinks to CPU
3. Enable active cooling fan
4. Reduce `CAMERA_FPS` in config (30 → 20)

---

## Database Setup

### Partitioning Strategy (Performance Critical)

```sql
-- Create partitions for next 12 months
DO $$
DECLARE
    start_date DATE;
    end_date DATE;
    partition_name TEXT;
BEGIN
    FOR i IN 0..11 LOOP
        start_date := DATE_TRUNC('month', CURRENT_DATE + (i || ' months')::INTERVAL);
        end_date := start_date + INTERVAL '1 month';
        partition_name := 'attendance_logs_' || TO_CHAR(start_date, 'YYYY_MM');

        EXECUTE FORMAT(
            'CREATE TABLE IF NOT EXISTS %I PARTITION OF attendance_logs FOR VALUES FROM (%L) TO (%L)',
            partition_name, start_date, end_date
        );
    END LOOP;
END $$;
```

**Automate partition creation (monthly cron job):**
```bash
# Add to cron
0 0 1 * * psql -U postgres -d attendance_db -c "SELECT create_monthly_partitions();"
```

### Indexing Strategy

```sql
-- Critical indexes (already in schema.sql)
-- Verify they exist:
\di attendance_logs_student_date
\di schedules_lookup

-- If query performance degrades, add:
CREATE INDEX CONCURRENTLY idx_attendance_composite
ON attendance_logs(course_id, date, student_id)
WHERE status = 'present';
```

### Backup Strategy

```bash
# Daily backup script
#!/bin/bash
DATE=$(date +%Y%m%d)
pg_dump -h localhost -U postgres attendance_db | gzip > /backups/attendance_${DATE}.sql.gz

# Keep last 30 days
find /backups -name "attendance_*.sql.gz" -mtime +30 -delete

# Add to crontab
0 2 * * * /usr/local/bin/backup_attendance.sh
```

---

## Load Testing

### Simulate Thundering Herd (9:00 AM Scenario)

**Load test script (locust):**
```python
from locust import HttpUser, task, between
import random
import uuid

class AttendanceUser(HttpUser):
    wait_time = between(1, 3)

    @task
    def submit_attendance(self):
        device_id = str(uuid.uuid4())
        records = [
            {
                "student_id": f"S{random.randint(1, 5000):04d}",
                "course_id": f"CS{random.randint(101, 999)}",
                "timestamp": "2024-01-15T09:05:00Z",
                "confidence": random.uniform(0.7, 0.95)
            }
            for _ in range(10)  # Batch of 10
        ]

        self.client.post(
            "/api/v1/attendance",
            json={"device_id": device_id, "records": records},
            headers={"Authorization": "Bearer test_key"}
        )
```

**Run test:**
```bash
pip install locust

locust -f load_test.py --host=http://localhost:8000

# Open http://localhost:8089
# Simulate: 100 users, spawn rate 10/sec
# Duration: 5 minutes
```

**Expected Performance:**
- Target: 1,000 requests/minute
- Latency P95: < 200ms
- Success rate: > 99.9%

---

## Production Checklist

### Security
- [ ] Change all default passwords
- [ ] Enable SSL/TLS (Let's Encrypt)
- [ ] Rotate API keys monthly
- [ ] Enable database encryption at rest
- [ ] Configure firewall rules (only Pi IPs → API)
- [ ] Set up VPN for Pi devices (optional)
- [ ] Enable audit logging
- [ ] Configure rate limiting (100 req/min per device)

### Monitoring
- [ ] Set up Prometheus + Grafana
- [ ] Configure alerts:
  - Pi offline > 10 minutes
  - CPU temp > 70°C
  - API latency > 500ms
  - Database connections > 80%
  - Queue depth > 1000
- [ ] Create dashboards:
  - Real-time attendance (today)
  - Device health (all Pis)
  - API performance
  - Database metrics

### Scalability
- [ ] Enable auto-scaling (min: 2, max: 10 instances)
- [ ] Configure Redis clustering (if > 10,000 students)
- [ ] Set up read replicas (PostgreSQL)
- [ ] Enable CDN for admin dashboard
- [ ] Implement circuit breakers
- [ ] Configure queue workers (Celery)

### Backup & Disaster Recovery
- [ ] Daily database backups (automated)
- [ ] Test restore procedure monthly
- [ ] Replicate to secondary region (critical data)
- [ ] Document rollback procedures
- [ ] Keep 90 days of backups

### Testing
- [ ] Load test with 100 concurrent Pis
- [ ] Verify attendance accuracy (> 95%)
- [ ] Test network failure scenarios
- [ ] Validate database partition creation
- [ ] Test camera failure handling

### Documentation
- [ ] Create runbooks for common issues
- [ ] Document API endpoints (Swagger/OpenAPI)
- [ ] Write troubleshooting guide for support staff
- [ ] Create video tutorial for Pi installation
- [ ] Document escalation procedures

---

## Troubleshooting

### Common Pi Issues

**Camera not detected:**
```bash
# Check camera connection
vcgencmd get_camera

# Should show: supported=1 detected=1

# Enable camera interface
sudo raspi-config
# Interface Options → Camera → Enable
```

**Face recognition too slow:**
- Reduce `FRAME_SKIP` (3 → 5)
- Lower resolution (640x480 → 320x240)
- Use `hog` model instead of `cnn`
- Ensure cooling is adequate

**Network timeouts:**
- Check API_BASE_URL in .env
- Verify firewall rules
- Test with `curl https://api.attendance.example.com/health`

### Common Backend Issues

**Database connection pool exhausted:**
```python
# Increase pool size in config
DB_POOL_SIZE=50
DB_MAX_OVERFLOW=20
```

**High API latency:**
- Check Redis cache hit rate
- Verify database indexes
- Enable query logging (temporarily)
- Review slow query log

**Queue buildup:**
- Scale Celery workers
- Increase batch processing
- Check database write performance

---

## Scaling Guidelines

| Metric | Small (< 1,000 students) | Medium (1,000-5,000) | Large (5,000-20,000) |
|--------|-------------------------|---------------------|---------------------|
| **Backend Instances** | 2× t3.small | 3× t3.medium | 5× t3.large |
| **Database** | db.t3.small | db.r5.large | db.r5.xlarge |
| **Redis** | cache.t3.micro | cache.r5.large | cache.r5.xlarge |
| **Celery Workers** | 2 | 4 | 8 |
| **Pi Devices** | 10-50 | 50-200 | 200-500 |
| **Monthly AWS Cost** | ~$200 | ~$500 | ~$1,500 |

---

**Next Steps:**
1. Set up staging environment
2. Deploy 3 Pis for pilot testing
3. Collect 2 weeks of performance data
4. Tune recognition thresholds
5. Proceed with full rollout
