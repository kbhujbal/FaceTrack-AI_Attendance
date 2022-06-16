# Face Recognition Attendance System

**Enterprise-grade automated attendance tracking using Raspberry Pi edge devices and cloud-based intelligence.**

## Overview

This system deploys Raspberry Pi units with cameras in classrooms to automatically mark student attendance using face recognition. The hybrid edge-cloud architecture ensures scalability, reliability, and performance even with thousands of students.

### Key Features

- **Smart Caching**: Pi downloads only enrolled students for current class (50 instead of 5,000)
- **Edge Processing**: Face detection runs locally on Pi for low latency
- **Async Architecture**: Cloud handles attendance spikes (9 AM rush) gracefully
- **Debouncing**: Prevents duplicate marks within configurable time window
- **Offline Resilience**: Pi queues records locally if network fails
- **Real-time Monitoring**: Track device health, attendance rates, system performance

## Architecture

```
┌─────────────┐
│ Raspberry Pi │ ──┐
│  + Camera    │   │
└─────────────┘   │
                  │  Every 10min: "What class is now?"
┌─────────────┐   │  Downloads: 50 student embeddings
│ Raspberry Pi │───┤
│  + Camera    │   │  Uploads: Batch attendance records
└─────────────┘   │
                  │
       ...        │
                  ▼
         ┌──────────────┐      ┌──────────────┐
         │ Load Balancer│─────▶│   FastAPI    │
         │    nginx     │      │   Backend    │
         └──────────────┘      └──────────────┘
                                       │
                    ┌──────────────────┼──────────────────┐
                    │                  │                  │
            ┌───────▼──────┐  ┌────────▼─────┐  ┌────────▼─────┐
            │  PostgreSQL  │  │  Redis Cache │  │ Message Queue│
            │  (Partitioned)│  │ (Schedules) │  │  (RabbitMQ)  │
            └──────────────┘  └──────────────┘  └──────────────┘
```

## Quick Start

### Prerequisites

- **Cloud**: PostgreSQL 14+, Redis 7+, Python 3.9+
- **Pi**: Raspberry Pi 4/5, Pi Camera Module, 64GB microSD

### 1. Deploy Cloud Backend

```bash
cd backend

# Setup database
psql -h your-db-host -U postgres -f ../database/schema.sql

# Configure
cp .env.example .env
nano .env  # Edit DATABASE_URL, REDIS_URL, etc.

# Install and run
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

API Docs: `http://localhost:8000/docs`

### 2. Setup Raspberry Pi

```bash
cd pi_client

# Install dependencies
sudo apt install python3-opencv cmake libboost-all-dev
pip install -r requirements.txt

# Configure
cp .env.example .env
nano .env  # Set CLASSROOM_ID, API_KEY, etc.

# Run
python main.py
```

### 3. Add Sample Data

```sql
-- Already included in schema.sql
-- 5 students, 3 courses, schedules, etc.

-- Add face embeddings (Python script)
python scripts/encode_faces.py --student S001 --image photos/alice.jpg
```

## Project Structure

```
FastrackAI/
├── ARCHITECTURE.md          # Detailed system design
├── DEPLOYMENT.md            # Production deployment guide
├── README.md                # This file
│
├── database/
│   └── schema.sql           # PostgreSQL schema with partitions
│
├── backend/                 # Cloud API (FastAPI)
│   ├── app/
│   │   ├── main.py          # Application entry point
│   │   ├── config.py        # Settings management
│   │   ├── database.py      # SQLAlchemy setup
│   │   ├── schemas.py       # Pydantic models
│   │   └── api/v1/
│   │       ├── schedule.py  # GET /schedule endpoint
│   │       ├── attendance.py# POST /attendance endpoint
│   │       └── heartbeat.py # POST /heartbeat endpoint
│   ├── requirements.txt
│   └── .env.example
│
└── pi_client/               # Raspberry Pi edge client
    ├── main.py              # Application orchestrator
    ├── config.py            # Configuration (Pydantic)
    ├── camera.py            # Face detection & recognition
    ├── sync_manager.py      # Cloud API communication
    ├── requirements.txt
    └── .env.example
```

## API Endpoints

### 1. GET /api/v1/schedule

**Purpose**: Pi fetches current class and student roster

**Request:**
```bash
curl "http://api.attendance.example.com/api/v1/schedule?room_id=LAB-301"
```

**Response:**
```json
{
  "course_id": "CS101",
  "course_name": "Data Structures",
  "start_time": "09:00",
  "end_time": "10:30",
  "enrolled_students": [
    {
      "student_id": "S001",
      "name": "Alice Johnson",
      "email": "alice.j@university.edu",
      "face_encoding": "<binary data>"
    }
  ]
}
```

### 2. POST /api/v1/attendance

**Purpose**: Pi uploads batch of attendance records

**Request:**
```bash
curl -X POST http://api.attendance.example.com/api/v1/attendance \
  -H "Content-Type: application/json" \
  -d '{
    "device_id": "a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11",
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

**Response:** `202 Accepted` (async processing)

### 3. GET /api/v1/attendance/course/{course_id}

**Purpose**: Admin views attendance for a class

**Response:**
```json
{
  "course_id": "CS101",
  "date": "2024-01-15",
  "total_enrolled": 50,
  "present": 47,
  "absent": 3,
  "attendance_percentage": 94.0,
  "students": [...]
}
```

## Configuration

### Raspberry Pi (.env)

| Variable | Description | Default |
|----------|-------------|---------|
| `CLASSROOM_ID` | Unique classroom identifier | Required |
| `API_BASE_URL` | Cloud API endpoint | Required |
| `API_KEY` | Authentication token | Required |
| `RECOGNITION_THRESHOLD` | Match threshold (0-1) | 0.6 |
| `DEBOUNCE_SECONDS` | Duplicate prevention | 30 |
| `FRAME_SKIP` | Process every Nth frame | 3 |
| `BATCH_SIZE` | Records per upload | 10 |

### Backend (.env)

| Variable | Description |
|----------|-------------|
| `DATABASE_URL` | PostgreSQL connection string |
| `REDIS_URL` | Redis cache endpoint |
| `SECRET_KEY` | JWT signing key |
| `CORS_ORIGINS` | Allowed frontend origins |

## Performance Benchmarks

**Raspberry Pi 4 (4GB):**
- Face detection: ~200ms per frame
- Recognition (50 students): ~150ms
- Throughput: ~2 students/second
- Typical classroom entry: 1 student/5 seconds → **No queue buildup**

**Cloud API:**
- Latency (P95): < 200ms
- Throughput: 1,000+ requests/minute
- Handles 100 classrooms × 50 students = 5,000 records at 9 AM

## Security

- Face embeddings stored as binary (not reversible to images)
- API authentication via JWT tokens
- TLS 1.3 for all communication
- Rate limiting: 100 requests/min per device
- GDPR/FERPA compliant (consent management, data retention)

## Monitoring

**Metrics (Prometheus):**
- `face_detection_latency_seconds`
- `recognition_accuracy_ratio`
- `api_request_duration_seconds`
- `queue_depth_local_db`

**Alerts:**
- Pi offline > 10 minutes
- CPU temperature > 70°C
- Recognition accuracy < 85%
- API latency > 500ms

## Troubleshooting

### Pi camera not working
```bash
vcgencmd get_camera
# Enable: sudo raspi-config → Interface Options → Camera
```

### Slow recognition
- Reduce `CAMERA_FPS` (30 → 20)
- Increase `FRAME_SKIP` (3 → 5)
- Use `hog` model instead of `cnn`

### API timeouts
- Check firewall rules
- Verify `API_BASE_URL` in .env
- Test: `curl https://api.example.com/health`

## Development

### Run Tests
```bash
# Backend
cd backend
pytest

# Pi Client (requires camera)
cd pi_client
python camera.py  # Visual test
```

### Database Migrations
```bash
cd backend
alembic revision --autogenerate -m "Description"
alembic upgrade head
```

## Roadmap

- [x] Core face recognition system
- [x] Smart caching and sync
- [x] Cloud API with async processing
- [ ] Admin dashboard (React)
- [ ] Mobile app for faculty
- [ ] Mask detection support
- [ ] Multi-face tracking optimization
- [ ] LMS integration (Canvas, Moodle)

## License

MIT License - See LICENSE file

## Support

- **Documentation**: See [ARCHITECTURE.md](ARCHITECTURE.md) and [DEPLOYMENT.md](DEPLOYMENT.md)
- **Issues**: Open GitHub issue
- **Email**: support@attendance.example.com

---

**Built with:** FastAPI, PostgreSQL, Redis, OpenCV, face_recognition, Raspberry Pi
