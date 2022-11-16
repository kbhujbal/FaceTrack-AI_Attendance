# Face Recognition Attendance System

Enterprise-grade automated attendance tracking using Raspberry Pi edge devices and cloud backend with smart caching.

## Overview

Deploy Raspberry Pi cameras in classrooms to automatically mark student attendance via face recognition. The system handles thousands of students efficiently through hybrid edge-cloud architecture.

**Core Innovation:** Pi downloads only students enrolled in current class (50 vs 5,000 embeddings) → 100x faster recognition.

## Quick Start

### Option 1: Docker Deployment (Recommended)

```bash
# Start entire system
docker-compose up -d

# Access API docs
open http://localhost:8000/docs
```

### Option 2: Manual Setup

**Backend:**
```bash
cd backend
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# Configure
cp .env.example .env
nano .env  # Set DATABASE_URL, REDIS_URL, SECRET_KEY

# Initialize database
psql -h localhost -U postgres -f ../database/schema.sql

# Run server
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

**Raspberry Pi:**
```bash
cd pi_client
sudo apt install python3-opencv cmake libboost-all-dev
pip install -r requirements.txt

# Configure
cp .env.example .env
nano .env  # Set CLASSROOM_ID, API_BASE_URL, API_KEY

# Run client
python main.py
```

**Encode student faces:**
```bash
python scripts/encode_faces.py --batch photos/
# Expected format: photos/S001.jpg, photos/S002.jpg, etc.
```

## Architecture

See [ARCHITECTURE.md](ARCHITECTURE.md) for detailed design.

```
┌─────────────┐
│ Pi + Camera │───┐  Every 10min: "What class is scheduled?"
└─────────────┘   │  Downloads: Only enrolled students (50)
                  │  Uploads: Attendance batch (10 records)
┌─────────────┐   │
│ Pi + Camera │───┤
└─────────────┘   ▼
            ┌──────────┐    ┌──────────────────┐
            │ FastAPI  │────│ PostgreSQL + Redis│
            │ Backend  │    │ Message Queue     │
            └──────────┘    └──────────────────┘
```

**Data Flow:**
1. Pi queries: "What class is in LAB-301 right now?"
2. Cloud returns: Course CS101 + 50 student face embeddings
3. Pi detects faces → matches against 50 (not 5,000)
4. Pi uploads: Batch attendance records every 60 seconds
5. Cloud processes: Async queue → PostgreSQL

## Key Features

- **Smart Caching**: Pi caches only relevant students → 100x speedup
- **Edge Processing**: Face detection on Pi → low latency
- **Offline Mode**: Local queue if network fails → zero data loss
- **Debouncing**: Prevents duplicate marks (30s window)
- **Async Processing**: Handles 9 AM spike (1,000+ req/min)
- **Partitioned DB**: Monthly partitions for performance

## Project Structure

```
FastrackAI/
├── ARCHITECTURE.md          # Detailed system design
├── README.md                # This file
├── docker-compose.yml       # One-command deployment
│
├── database/
│   └── schema.sql           # PostgreSQL schema (partitioned)
│
├── backend/                 # Cloud API
│   ├── app/
│   │   ├── main.py
│   │   ├── api/v1/
│   │   │   ├── schedule.py     # GET /schedule
│   │   │   ├── attendance.py   # POST /attendance
│   │   │   └── heartbeat.py    # POST /heartbeat
│   ├── Dockerfile
│   └── requirements.txt
│
├── pi_client/               # Raspberry Pi edge client
│   ├── main.py              # Orchestrator
│   ├── camera.py            # Face detection/recognition
│   ├── sync_manager.py      # API sync + caching
│   └── requirements.txt
│
└── scripts/
    └── encode_faces.py      # Encode student photos
```

## API Reference

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/v1/schedule?room_id=LAB-301` | GET | Fetch current class + student roster |
| `/api/v1/attendance` | POST | Submit attendance batch |
| `/api/v1/attendance/student/{id}` | GET | Student attendance history |
| `/api/v1/attendance/course/{id}` | GET | Class attendance report |

**Example - Submit Attendance:**
```bash
curl -X POST http://localhost:8000/api/v1/attendance \
  -H "Content-Type: application/json" \
  -d '{
    "device_id": "pi-lab301",
    "records": [
      {
        "student_id": "S001",
        "course_id": "CS101",
        "timestamp": "2024-01-15T09:05:23Z",
        "confidence": 0.92
      }
    ]
  }'
```

## Configuration

**Backend (.env):**
```bash
DATABASE_URL=postgresql://user:pass@localhost:5432/attendance_db
REDIS_URL=redis://localhost:6379/0
SECRET_KEY=your-secret-key-here
API_PREFIX=/api/v1
WORKERS=4
```

**Pi Client (.env):**
```bash
DEVICE_UUID=a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11
CLASSROOM_ID=LAB-301
API_BASE_URL=https://api.attendance.example.com
API_KEY=your_api_key_here
RECOGNITION_THRESHOLD=0.6
DEBOUNCE_SECONDS=30
FRAME_SKIP=3  # Process every 3rd frame
```

## Performance

**Raspberry Pi 4 (4GB):**
- Face detection: 200ms
- Recognition (50 students): 150ms
- Throughput: 2 students/second
- Result: No bottleneck (1 student enters every 5 seconds)

**Cloud API:**
- Latency P95: <200ms
- Throughput: 1,000+ req/min
- Scales: 100 classrooms × 50 students at 9 AM

## Hardware Requirements

**Recommended:**
- Raspberry Pi 5 (8GB) or Pi 4 (4GB)
- Pi Camera Module 3 or Logitech C920
- 64GB microSD (high endurance)
- Argon NEO 5 cooling case
- Ethernet (avoid WiFi congestion)

**Cloud (for 100 classrooms):**
- 2× t3.medium (backend)
- db.t3.small (PostgreSQL)
- cache.t3.micro (Redis)
- Cost: ~$200/month

## Database Quick Reference

```sql
-- View current schedule
SELECT * FROM current_schedule WHERE classroom_id = 'LAB-301';

-- Today's attendance
SELECT s.first_name, s.last_name, al.timestamp
FROM attendance_logs al
JOIN students s ON al.student_id = s.student_id
WHERE DATE(al.timestamp) = CURRENT_DATE;

-- Attendance percentage per student
SELECT * FROM student_attendance_summary WHERE course_id = 'CS101';

-- Get enrolled students for current class (what Pi calls)
SELECT * FROM get_enrolled_students_for_class('LAB-301', CURRENT_TIMESTAMP);
```

## Troubleshooting

**Pi camera not working:**
```bash
vcgencmd get_camera  # Should show: supported=1 detected=1
sudo raspi-config → Interface Options → Camera → Enable
```

**Slow recognition:**
```bash
# Edit pi_client/.env
FRAME_SKIP=5          # Was 3
CAMERA_FPS=20         # Was 30
RECOGNITION_MODEL=hog # Faster than 'cnn'
```

**Backend won't start:**
```bash
docker logs attendance_backend
# Check DATABASE_URL, REDIS_URL in .env
```

**API timeouts:**
```bash
curl http://localhost:8000/health  # Should return {"status":"healthy"}
```

## Deployment Checklist

- [ ] Change default passwords (postgres, redis)
- [ ] Generate new SECRET_KEY for backend
- [ ] Rotate API_KEY for Pi devices
- [ ] Enable SSL/TLS (Let's Encrypt)
- [ ] Configure firewall (allow only Pi IPs)
- [ ] Set up database backups (daily)
- [ ] Enable monitoring (Prometheus/Grafana)
- [ ] Test with 3 Pis in pilot classrooms
- [ ] Tune RECOGNITION_THRESHOLD based on accuracy

## Security

- Face embeddings are **binary vectors** (not reversible to images)
- JWT authentication for API access
- TLS 1.3 encryption for all communication
- Rate limiting: 100 requests/min per device
- GDPR/FERPA compliant (consent + data retention policies)

## Scaling Guidelines

| Students | Backend | Database | Redis | Cost/Month |
|----------|---------|----------|-------|------------|
| < 1,000 | 2× t3.small | db.t3.small | cache.t3.micro | $200 |
| 1,000-5,000 | 3× t3.medium | db.r5.large | cache.r5.large | $500 |
| 5,000-20,000 | 5× t3.large | db.r5.xlarge | cache.r5.xlarge | $1,500 |

## Common Tasks

**Add new student:**
```bash
# 1. Insert to database
psql -d attendance_db -c "INSERT INTO students (student_id, first_name, last_name, email) VALUES ('S999', 'John', 'Doe', 'john@example.com');"

# 2. Encode face
python scripts/encode_faces.py --student S999 --image photos/john.jpg

# 3. Verify
python scripts/encode_faces.py --verify S999
```

**Add new course:**
```sql
INSERT INTO courses (course_id, course_code, course_name, department, credits)
VALUES ('CS301', 'CSE301', 'Machine Learning', 'Computer Science', 4);

-- Enroll students
INSERT INTO enrollments (student_id, course_id) VALUES ('S001', 'CS301');

-- Create schedule
INSERT INTO schedules (course_id, classroom_id, day_of_week, start_time, end_time, effective_from, effective_to)
VALUES ('CS301', 'LAB-301', 1, '14:00', '15:30', CURRENT_DATE, CURRENT_DATE + INTERVAL '6 months');
```

**Deploy new Pi:**
```bash
# Generate UUID
python3 -c "import uuid; print(uuid.uuid4())"

# Configure .env with new UUID and CLASSROOM_ID

# Create systemd service for auto-start
sudo nano /etc/systemd/system/attendance.service
sudo systemctl enable attendance
sudo systemctl start attendance
```

## Monitoring

**Logs:**
```bash
# Backend
docker logs -f attendance_backend

# Pi (if using systemd)
sudo journalctl -u attendance -f

# Database
docker exec -it attendance_db psql -U user -d attendance_db
```

**Metrics (Prometheus):**
- `face_detection_latency_seconds`
- `recognition_accuracy_ratio`
- `api_request_duration_seconds`
- `attendance_records_total`

**Alerts:**
- Pi offline > 10 minutes
- CPU temperature > 70°C
- Recognition accuracy < 85%
- API latency > 500ms

## Documentation

- **ARCHITECTURE.md** - Detailed system design, data flow, scalability strategies
- **README.md** - This file (quick start + reference)

## License

MIT License

---

**Built with:** FastAPI, PostgreSQL, Redis, OpenCV, face_recognition, Raspberry Pi
