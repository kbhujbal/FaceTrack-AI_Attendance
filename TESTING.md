# Testing Guide - Face Recognition Attendance System

## Quick Start Testing (Local)

### 1. Start Backend Services

```bash
# Start database and backend using Docker
docker-compose up -d postgres redis backend

# Wait for services to be healthy
docker-compose ps

# Check backend is running
curl http://localhost:8000/health
```

### 2. Verify Database Setup

```bash
# Connect to database
docker exec -it attendance_db psql -U attendance_user -d attendance_db

# Check tables
\dt

# Verify sample data
SELECT student_id, first_name, last_name FROM students;
SELECT course_id, course_name FROM courses;
SELECT classroom_id, building, room_number FROM classrooms;

# Exit
\q
```

### 3. Test API Endpoints

**Schedule Endpoint (What class is now?):**
```bash
# Should return CS101 if testing on Tuesday 9:00-10:30
curl "http://localhost:8000/api/v1/schedule?room_id=LAB-301&device_id=a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11"

# Preview week schedule
curl "http://localhost:8000/api/v1/schedule/preview?room_id=LAB-301"
```

**Attendance Endpoint (Submit records):**
```bash
curl -X POST http://localhost:8000/api/v1/attendance \
  -H "Content-Type: application/json" \
  -d '{
    "device_id": "a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11",
    "records": [
      {
        "student_id": "S001",
        "course_id": "CS101",
        "timestamp": "2024-01-15T09:05:23Z",
        "confidence": 0.92,
        "classroom_id": "LAB-301"
      }
    ]
  }'
```

**Query Attendance:**
```bash
# Student attendance
curl "http://localhost:8000/api/v1/attendance/student/S001?course_id=CS101"

# Course attendance (today)
curl "http://localhost:8000/api/v1/attendance/course/CS101"
```

### 4. Test Raspberry Pi Client (Without Camera)

**Mock camera test:**
```bash
cd pi_client

# Create test configuration
cat > .env << EOF
DEVICE_UUID=a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11
DEVICE_NAME=PI-TEST
CLASSROOM_ID=LAB-301
API_BASE_URL=http://localhost:8000
API_KEY=test_key_12345
LOG_LEVEL=DEBUG
EOF

# Test sync manager (API communication)
python3 -c "
from sync_manager import SyncManager
from config import settings

sm = SyncManager('LAB-301')
print('Testing schedule sync...')
sm.sync_schedule_if_needed()
print(f'Current class: {sm.schedule_manager.get_current_class()}')
print(f'Enrolled students: {len(sm.schedule_manager.get_enrolled_students())}')
"
```

## End-to-End Testing

### Scenario 1: Morning Class (CS101 at 9:00 AM)

**Step 1: Setup Schedule**
```sql
-- Ensure schedule exists for current day/time
INSERT INTO schedules (course_id, classroom_id, day_of_week, start_time, end_time, effective_from, effective_to)
VALUES ('CS101', 'LAB-301', EXTRACT(DOW FROM CURRENT_DATE), '09:00', '10:30', CURRENT_DATE, CURRENT_DATE + INTERVAL '30 days')
ON CONFLICT DO NOTHING;
```

**Step 2: Encode Student Faces**
```bash
# Prepare student photos
mkdir -p photos
# Add photos: photos/S001.jpg, photos/S002.jpg, etc.

# Encode faces
python scripts/encode_faces.py --batch photos/ --db "postgresql://attendance_user:attendance_pass@localhost:5432/attendance_db"
```

**Step 3: Run Pi Client**
```bash
cd pi_client

# If you have a camera connected:
python main.py

# Monitor logs
tail -f logs/pi_client.log
```

**Step 4: Verify Attendance**
```bash
# Check database
docker exec -it attendance_db psql -U attendance_user -d attendance_db

SELECT
    al.timestamp,
    s.first_name,
    s.last_name,
    c.course_name,
    al.confidence_score
FROM attendance_logs al
JOIN students s ON al.student_id = s.student_id
JOIN courses c ON al.course_id = c.course_id
WHERE DATE(al.timestamp) = CURRENT_DATE
ORDER BY al.timestamp DESC;
```

### Scenario 2: Network Failure Handling

**Step 1: Start Pi with backend running**
```bash
cd pi_client
python main.py &
PID=$!
```

**Step 2: Simulate network failure**
```bash
# Stop backend
docker-compose stop backend

# Pi should queue records locally
# Check local queue:
sqlite3 data/local_queue.db "SELECT COUNT(*) FROM attendance_queue;"
```

**Step 3: Restore network**
```bash
# Restart backend
docker-compose start backend

# Pi should auto-sync queued records
# Verify in logs
tail -f logs/pi_client.log | grep "batch uploaded"
```

### Scenario 3: Thundering Herd (Peak Load)

**Simulate 100 classrooms at 9:00 AM:**

```python
# load_test.py
import asyncio
import aiohttp
import random
from datetime import datetime

async def submit_attendance(session, classroom_id):
    """Simulate one Pi device"""
    records = [
        {
            "student_id": f"S{random.randint(1, 5000):04d}",
            "course_id": f"CS{random.randint(101, 999)}",
            "timestamp": datetime.now().isoformat(),
            "confidence": random.uniform(0.7, 0.95),
            "classroom_id": classroom_id
        }
        for _ in range(10)  # Batch of 10
    ]

    payload = {
        "device_id": f"test-device-{classroom_id}",
        "records": records
    }

    async with session.post(
        "http://localhost:8000/api/v1/attendance",
        json=payload
    ) as response:
        return response.status

async def main():
    async with aiohttp.ClientSession() as session:
        tasks = [
            submit_attendance(session, f"ROOM-{i:03d}")
            for i in range(100)  # 100 classrooms
        ]

        results = await asyncio.gather(*tasks)
        success = sum(1 for r in results if r in (200, 202))
        print(f"Success: {success}/100")

asyncio.run(main())
```

**Run test:**
```bash
pip install aiohttp
python load_test.py

# Monitor backend performance
docker stats attendance_backend

# Check queue depth
docker exec -it attendance_redis redis-cli LLEN attendance_queue
```

## Unit Tests

### Backend Tests

**test_api.py:**
```python
import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}

def test_schedule_no_class():
    response = client.get("/api/v1/schedule?room_id=INVALID&device_id=test")
    # Should return 200 with null body or 204 No Content
    assert response.status_code in (200, 204)

def test_attendance_submission():
    payload = {
        "device_id": "test-device",
        "records": [
            {
                "student_id": "S001",
                "course_id": "CS101",
                "timestamp": "2024-01-15T09:05:23Z",
                "confidence": 0.92
            }
        ]
    }
    response = client.post("/api/v1/attendance", json=payload)
    assert response.status_code == 202
    assert "accepted" in response.json()["status"].lower()

def test_attendance_invalid_payload():
    payload = {"device_id": "test", "records": [{"invalid": "data"}]}
    response = client.post("/api/v1/attendance", json=payload)
    assert response.status_code == 400
```

**Run tests:**
```bash
cd backend
pytest test_api.py -v
```

### Pi Client Tests

**test_camera.py:**
```python
import pytest
import numpy as np
from camera import FaceRecognizer, DetectedFace

def test_recognize_face_no_roster():
    recognizer = FaceRecognizer()
    fake_encoding = np.random.rand(128)

    result = recognizer.recognize_face(fake_encoding)
    assert result is None  # No roster loaded

def test_load_roster():
    recognizer = FaceRecognizer()

    students = [
        {
            "student_id": "S001",
            "face_encoding": np.random.rand(128).tobytes()
        }
    ]

    recognizer.load_roster(students)
    assert len(recognizer.known_encodings) == 1
    assert recognizer.known_ids[0] == "S001"

def test_debouncing():
    from sync_manager import AttendanceQueue

    queue = AttendanceQueue()

    # First mark should succeed
    assert queue.add_record("S001", "CS101", 0.9) == True

    # Immediate duplicate should be debounced
    assert queue.add_record("S001", "CS101", 0.9) == False
```

**Run tests:**
```bash
cd pi_client
pytest test_camera.py -v
```

## Performance Testing

### 1. Face Recognition Accuracy

```python
# test_accuracy.py
import face_recognition
from pathlib import Path

def test_recognition_accuracy():
    """Test with multiple photos of same person"""
    base_photo = "photos/S001_base.jpg"
    test_photos = [
        "photos/S001_variation1.jpg",
        "photos/S001_variation2.jpg",
        "photos/S001_different_angle.jpg"
    ]

    base_encoding = face_recognition.face_encodings(
        face_recognition.load_image_file(base_photo)
    )[0]

    matches = 0
    for test_photo in test_photos:
        test_encoding = face_recognition.face_encodings(
            face_recognition.load_image_file(test_photo)
        )[0]

        distance = face_recognition.face_distance([base_encoding], test_encoding)[0]
        if distance < 0.6:  # Threshold
            matches += 1

    accuracy = matches / len(test_photos) * 100
    print(f"Recognition accuracy: {accuracy}%")
    assert accuracy >= 90  # Expect >90% accuracy
```

### 2. Pi Performance Benchmark

```python
# benchmark_pi.py
import time
import cv2
import face_recognition
import numpy as np

def benchmark_face_detection():
    """Measure face detection performance"""
    camera = cv2.VideoCapture(0)

    times = []
    for _ in range(100):
        ret, frame = camera.read()
        small_frame = cv2.resize(frame, (0, 0), fx=0.25, fy=0.25)

        start = time.time()
        face_locations = face_recognition.face_locations(small_frame, model="hog")
        elapsed = time.time() - start

        times.append(elapsed)

    camera.release()

    print(f"Average detection time: {np.mean(times)*1000:.2f}ms")
    print(f"P95 latency: {np.percentile(times, 95)*1000:.2f}ms")
    print(f"Throughput: {1/np.mean(times):.2f} FPS")
```

### 3. Database Query Performance

```sql
-- Test schedule lookup (hot path)
EXPLAIN ANALYZE
SELECT *
FROM get_enrolled_students_for_class('LAB-301', CURRENT_TIMESTAMP);

-- Should use indexes, < 50ms

-- Test attendance aggregation
EXPLAIN ANALYZE
SELECT
    s.student_id,
    COUNT(DISTINCT al.date) as days_present
FROM students s
JOIN enrollments e ON s.student_id = e.student_id
LEFT JOIN attendance_logs al ON s.student_id = al.student_id
    AND al.course_id = e.course_id
WHERE e.course_id = 'CS101'
GROUP BY s.student_id;

-- Should use partition pruning, < 100ms
```

## Integration Tests

### Full Workflow Test

```bash
#!/bin/bash
# integration_test.sh

set -e

echo "Starting integration test..."

# 1. Start services
docker-compose up -d
sleep 10

# 2. Verify health
curl -f http://localhost:8000/health || exit 1

# 3. Check schedule endpoint
SCHEDULE=$(curl -s "http://localhost:8000/api/v1/schedule?room_id=LAB-301&device_id=test")
echo "Schedule: $SCHEDULE"

# 4. Submit test attendance
curl -X POST http://localhost:8000/api/v1/attendance \
  -H "Content-Type: application/json" \
  -d '{
    "device_id": "test",
    "records": [
      {"student_id": "S001", "course_id": "CS101", "timestamp": "2024-01-15T09:05:00Z", "confidence": 0.9}
    ]
  }'

# 5. Wait for async processing
sleep 2

# 6. Verify record in database
docker exec attendance_db psql -U attendance_user -d attendance_db \
  -c "SELECT COUNT(*) FROM attendance_logs WHERE student_id = 'S001';" | grep -q "1"

echo "✅ Integration test passed!"

# Cleanup
docker-compose down
```

## Troubleshooting Tests

### Common Issues

**Database connection refused:**
```bash
# Check if postgres is running
docker ps | grep postgres

# Check logs
docker logs attendance_db

# Verify network
docker network inspect attendance_network
```

**Pi client import errors:**
```bash
# Ensure virtual environment is activated
source venv/bin/activate

# Reinstall dependencies
pip install -r requirements.txt --force-reinstall
```

**Face recognition fails:**
```bash
# Check camera
ls -l /dev/video*

# Test camera directly
python3 -c "import cv2; print(cv2.VideoCapture(0).isOpened())"

# Verify dlib installation
python3 -c "import dlib; print(dlib.__version__)"
```

## CI/CD Pipeline (GitHub Actions Example)

**.github/workflows/test.yml:**
```yaml
name: Tests

on: [push, pull_request]

jobs:
  backend-tests:
    runs-on: ubuntu-latest

    services:
      postgres:
        image: postgres:14
        env:
          POSTGRES_USER: test_user
          POSTGRES_PASSWORD: test_pass
          POSTGRES_DB: test_db
        options: >-
          --health-cmd pg_isready
          --health-interval 10s

    steps:
      - uses: actions/checkout@v2

      - name: Set up Python
        uses: actions/setup-python@v2
        with:
          python-version: 3.9

      - name: Install dependencies
        run: |
          cd backend
          pip install -r requirements.txt

      - name: Run tests
        env:
          DATABASE_URL: postgresql://test_user:test_pass@localhost:5432/test_db
        run: |
          cd backend
          pytest -v
```

---

**Testing Checklist:**
- [ ] All API endpoints return expected responses
- [ ] Database schema loads without errors
- [ ] Face encoding/recognition accuracy > 90%
- [ ] Pi client handles network failures gracefully
- [ ] Load test passes (100 concurrent requests)
- [ ] Debouncing prevents duplicates
- [ ] Partitioning works correctly
- [ ] Docker deployment successful
- [ ] Integration test passes end-to-end
