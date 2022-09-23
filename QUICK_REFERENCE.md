# Quick Reference Guide

## Project Overview

**Face Recognition Attendance System** - Enterprise IoT solution using Raspberry Pi edge devices + Cloud backend.

**Key Innovation:** Smart caching - Pi downloads only students enrolled in current class (50 vs 5,000 embeddings).

---

## Directory Structure

```
FastrackAI/
├── ARCHITECTURE.md          ← System design & data flow
├── DEPLOYMENT.md            ← Production setup guide
├── TESTING.md               ← Testing procedures
├── README.md                ← Project overview
├── docker-compose.yml       ← One-command deployment
│
├── database/
│   └── schema.sql           ← PostgreSQL schema (partitioned)
│
├── backend/                 ← Cloud API (FastAPI)
│   ├── app/
│   │   ├── main.py          ← Entry point
│   │   ├── api/v1/
│   │   │   ├── schedule.py  ← GET /schedule
│   │   │   ├── attendance.py← POST /attendance
│   │   │   └── heartbeat.py ← POST /heartbeat
│   ├── Dockerfile
│   └── requirements.txt
│
├── pi_client/               ← Raspberry Pi edge client
│   ├── main.py              ← Orchestrator
│   ├── camera.py            ← Face detection
│   ├── sync_manager.py      ← API sync
│   └── config.py            ← Settings
│
└── scripts/
    └── encode_faces.py      ← Encode student photos
```

---

## Quick Start Commands

### Deploy Entire System (Docker)
```bash
docker-compose up -d
```

### Backend Only
```bash
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
# http://localhost:8000/docs
```

### Raspberry Pi Setup
```bash
cd pi_client
sudo apt install python3-opencv cmake libboost-all-dev
pip install -r requirements.txt
cp .env.example .env
nano .env  # Configure CLASSROOM_ID, API_KEY
python main.py
```

### Encode Student Faces
```bash
python scripts/encode_faces.py --student S001 --image alice.jpg
python scripts/encode_faces.py --batch photos/
python scripts/encode_faces.py --verify S001
```

---

## API Endpoints Cheat Sheet

| Endpoint | Method | Purpose | Caller |
|----------|--------|---------|--------|
| `/api/v1/schedule?room_id=LAB-301` | GET | Fetch current class + roster | Pi (every 10min) |
| `/api/v1/attendance` | POST | Submit batch attendance | Pi (every 60s) |
| `/api/v1/heartbeat` | POST | Device health metrics | Pi (every 60s) |
| `/api/v1/attendance/student/{id}` | GET | Student history | Admin |
| `/api/v1/attendance/course/{id}` | GET | Class attendance | Faculty |
| `/health` | GET | Health check | Load balancer |

---

## Configuration Files

### Backend `.env`
```bash
DATABASE_URL=postgresql://user:pass@host:5432/db
REDIS_URL=redis://localhost:6379/0
SECRET_KEY=your-secret-key
API_PREFIX=/api/v1
WORKERS=4
```

### Pi Client `.env`
```bash
DEVICE_UUID=a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11
CLASSROOM_ID=LAB-301
API_BASE_URL=https://api.attendance.example.com
API_KEY=your_api_key
RECOGNITION_THRESHOLD=0.6
DEBOUNCE_SECONDS=30
FRAME_SKIP=3
```

---

## Database Quick Commands

```sql
-- View current schedule
SELECT * FROM current_schedule WHERE classroom_id = 'LAB-301';

-- Today's attendance
SELECT s.first_name, s.last_name, al.timestamp
FROM attendance_logs al
JOIN students s ON al.student_id = s.student_id
WHERE DATE(al.timestamp) = CURRENT_DATE;

-- Attendance percentage per course
SELECT * FROM student_attendance_summary WHERE course_id = 'CS101';

-- Get enrolled students for class (what Pi calls)
SELECT * FROM get_enrolled_students_for_class('LAB-301', CURRENT_TIMESTAMP);

-- Create next month's partition
SELECT create_monthly_partitions();
```

---

## Troubleshooting Quick Fixes

### Pi camera not working
```bash
vcgencmd get_camera  # Should show: supported=1 detected=1
sudo raspi-config → Interface Options → Camera → Enable
```

### Backend won't start
```bash
docker logs attendance_backend
# Check DATABASE_URL, REDIS_URL in .env
docker exec -it attendance_db psql -U user -d db
```

### Face recognition too slow
```bash
# In pi_client/.env:
FRAME_SKIP=5          # Was 3, now process every 5th frame
CAMERA_FPS=20         # Was 30
FRAME_SCALE=0.25      # Already optimal
RECOGNITION_MODEL=hog # Faster than 'cnn'
```

### Database connection pool exhausted
```bash
# In backend/.env:
DB_POOL_SIZE=50       # Was 20
DB_MAX_OVERFLOW=20    # Was 10
```

### High API latency
```bash
# Check Redis cache
docker exec -it attendance_redis redis-cli
> INFO stats
> KEYS schedule:*

# Check database indexes
\d attendance_logs
\di
```

---

## Performance Targets

| Metric | Target | Critical |
|--------|--------|----------|
| Face detection latency | < 300ms | < 500ms |
| Recognition (50 students) | < 200ms | < 400ms |
| API response time (P95) | < 200ms | < 500ms |
| Throughput | 1000 req/min | 500 req/min |
| Pi CPU temperature | < 60°C | < 70°C |
| Recognition accuracy | > 95% | > 90% |

---

## Common Tasks

### Add New Student
```sql
INSERT INTO students (student_id, first_name, last_name, email)
VALUES ('S999', 'John', 'Doe', 'john@example.com');

-- Encode face
python scripts/encode_faces.py --student S999 --image john.jpg
```

### Add New Course
```sql
INSERT INTO courses (course_id, course_code, course_name, department, credits)
VALUES ('CS301', 'CSE301', 'Machine Learning', 'Computer Science', 4);

-- Enroll students
INSERT INTO enrollments (student_id, course_id)
VALUES ('S001', 'CS301'), ('S002', 'CS301');

-- Create schedule
INSERT INTO schedules (course_id, classroom_id, day_of_week, start_time, end_time, effective_from, effective_to)
VALUES ('CS301', 'LAB-301', 1, '14:00', '15:30', CURRENT_DATE, CURRENT_DATE + INTERVAL '6 months');
```

### Deploy New Pi Device
```bash
# On Pi:
cd ~/attendance-system/pi_client

# Generate UUID
python3 -c "import uuid; print(uuid.uuid4())"

# Configure
nano .env
# DEVICE_UUID=<generated-uuid>
# DEVICE_NAME=PI-LAB402
# CLASSROOM_ID=LAB-402

# Create systemd service
sudo cp attendance.service /etc/systemd/system/
sudo systemctl enable attendance
sudo systemctl start attendance

# On Cloud: Register device in database
INSERT INTO edge_devices (device_uuid, device_name, classroom_id, model)
VALUES ('<uuid>', 'PI-LAB402', 'LAB-402', 'Raspberry Pi 4 4GB');
```

### View Logs
```bash
# Backend
docker logs -f attendance_backend

# Pi (if using systemd)
sudo journalctl -u attendance -f

# Pi (if running manually)
tail -f logs/pi_client.log

# Database queries
docker exec -it attendance_db psql -U user -d db -c "SELECT * FROM api_audit_log ORDER BY timestamp DESC LIMIT 10;"
```

---

## Monitoring Dashboards

**Grafana Panels (if using monitoring profile):**
- Real-time attendance map
- Device health (CPU temp, disk usage)
- API latency (P50, P95, P99)
- Recognition accuracy trend
- Queue depth over time

Access: `http://localhost:3000` (admin/admin)

**Prometheus Metrics:**
```
face_detection_latency_seconds
recognition_accuracy_ratio
api_request_duration_seconds
attendance_records_total
device_cpu_temperature
```

---

## Security Checklist

- [ ] Change default passwords (`postgres`, `redis`, `grafana`)
- [ ] Rotate `SECRET_KEY` in backend `.env`
- [ ] Rotate `API_KEY` for Pi devices monthly
- [ ] Enable SSL/TLS (Let's Encrypt)
- [ ] Configure firewall (allow only Pi IPs → API)
- [ ] Enable audit logging
- [ ] Set up fail2ban for API
- [ ] Review CORS origins
- [ ] Encrypt database backups
- [ ] Enable 2FA for admin dashboard

---

## Scaling Thresholds

**When to scale:**
- API latency P95 > 300ms → Add backend instance
- Database CPU > 70% → Upgrade instance or add read replica
- Redis memory > 80% → Upgrade instance
- Queue depth consistently > 100 → Add Celery workers
- Pi CPU temp > 65°C → Improve cooling or reduce FPS

**Auto-scaling rules (AWS):**
```
Target: CPU 60%
Min instances: 2
Max instances: 10
Scale-up cooldown: 60s
Scale-down cooldown: 300s
```

---

## Backup & Recovery

### Daily Backup (Automated)
```bash
#!/bin/bash
pg_dump -h localhost -U user attendance_db | gzip > backup_$(date +%Y%m%d).sql.gz
aws s3 cp backup_*.sql.gz s3://attendance-backups/
find . -name "backup_*.sql.gz" -mtime +30 -delete
```

### Restore from Backup
```bash
gunzip < backup_20240115.sql.gz | psql -U user -d attendance_db
```

### Disaster Recovery
```bash
# Restore to new region
1. Launch new RDS instance
2. Restore from S3 backup
3. Update backend DNS
4. Restart backend services
# RPO: 24 hours, RTO: 2 hours
```

---

## Contact & Support

- **Documentation**: See `ARCHITECTURE.md`, `DEPLOYMENT.md`, `TESTING.md`
- **Issues**: GitHub Issues
- **Monitoring**: Grafana dashboards
- **Logs**: CloudWatch / Local log files

---

**Last Updated**: 2024-01-15
**Version**: 1.0.0
**Maintainer**: Attendance System Team
