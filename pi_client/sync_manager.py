"""
Sync Manager - Handles communication with Cloud API
"""
import requests
import time
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
from loguru import logger
from config import settings
import json


class APIClient:
    """HTTP client for Cloud API communication"""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'Authorization': f'Bearer {settings.API_KEY}',
            'Content-Type': 'application/json',
            'User-Agent': f'PiClient/{settings.DEVICE_NAME}'
        })
        self.session.verify = True

    def get_schedule(self, classroom_id: str) -> Optional[Dict[str, Any]]:
        """Fetch current schedule and enrolled students

        Args:
            classroom_id: Classroom identifier

        Returns:
            Dict with schedule and student roster or None on failure
        """
        url = settings.api_schedule_endpoint
        params = {
            'room_id': classroom_id,
            'device_id': settings.DEVICE_UUID
        }

        for attempt in range(settings.API_RETRY_ATTEMPTS):
            try:
                response = self.session.get(
                    url,
                    params=params,
                    timeout=settings.API_TIMEOUT
                )

                if response.status_code == 200:
                    data = response.json()
                    logger.info(f"Schedule fetched: {data.get('course_name', 'N/A')}")
                    return data

                elif response.status_code == 204:
                    logger.info("No class scheduled at this time")
                    return None

                elif response.status_code == 404:
                    logger.warning(f"Classroom {classroom_id} not found")
                    return None

                else:
                    logger.error(f"API error: {response.status_code} - {response.text}")

            except requests.exceptions.Timeout:
                logger.warning(f"Schedule fetch timeout (attempt {attempt + 1}/{settings.API_RETRY_ATTEMPTS})")

            except requests.exceptions.ConnectionError:
                logger.error(f"Connection error (attempt {attempt + 1}/{settings.API_RETRY_ATTEMPTS})")

            except Exception as e:
                logger.error(f"Unexpected error fetching schedule: {e}")

            if attempt < settings.API_RETRY_ATTEMPTS - 1:
                time.sleep(2 ** attempt)  # Exponential backoff

        return None

    def post_attendance(self, records: List[Dict[str, Any]]) -> bool:
        """Send attendance records to Cloud

        Args:
            records: List of attendance records

        Returns:
            True if successful, False otherwise
        """
        url = settings.api_attendance_endpoint
        payload = {
            'device_id': settings.DEVICE_UUID,
            'records': records
        }

        for attempt in range(settings.API_RETRY_ATTEMPTS):
            try:
                response = self.session.post(
                    url,
                    json=payload,
                    timeout=settings.API_TIMEOUT
                )

                if response.status_code in (200, 201, 202):
                    logger.info(f"Attendance batch uploaded: {len(records)} records")
                    return True

                elif response.status_code == 400:
                    logger.error(f"Invalid payload: {response.text}")
                    return False  # Don't retry on validation errors

                else:
                    logger.error(f"API error: {response.status_code} - {response.text}")

            except requests.exceptions.Timeout:
                logger.warning(f"Attendance post timeout (attempt {attempt + 1}/{settings.API_RETRY_ATTEMPTS})")

            except Exception as e:
                logger.error(f"Error posting attendance: {e}")

            if attempt < settings.API_RETRY_ATTEMPTS - 1:
                time.sleep(2 ** attempt)

        return False

    def send_heartbeat(self, metrics: Dict[str, Any]) -> bool:
        """Send device heartbeat with health metrics

        Args:
            metrics: Device health metrics (CPU temp, disk usage, etc.)

        Returns:
            True if successful
        """
        url = settings.api_heartbeat_endpoint
        payload = {
            'device_id': settings.DEVICE_UUID,
            'timestamp': datetime.utcnow().isoformat(),
            'metrics': metrics
        }

        try:
            response = self.session.post(url, json=payload, timeout=10)
            return response.status_code in (200, 202)
        except Exception as e:
            logger.debug(f"Heartbeat failed: {e}")
            return False


class ScheduleManager:
    """Manages schedule synchronization and caching"""

    def __init__(self, api_client: APIClient):
        self.api_client = api_client
        self.current_schedule: Optional[Dict[str, Any]] = None
        self.last_sync_time: Optional[datetime] = None
        self.next_sync_time: Optional[datetime] = None

    def should_sync(self) -> bool:
        """Check if schedule sync is needed"""
        if self.last_sync_time is None:
            return True

        if datetime.now() >= self.next_sync_time:
            return True

        return False

    def sync(self, classroom_id: str) -> bool:
        """Fetch latest schedule from Cloud

        Args:
            classroom_id: Classroom identifier

        Returns:
            True if schedule was updated
        """
        logger.info("Syncing schedule...")

        new_schedule = self.api_client.get_schedule(classroom_id)

        # Update sync timestamps
        self.last_sync_time = datetime.now()
        self.next_sync_time = self.last_sync_time + timedelta(minutes=settings.SYNC_INTERVAL_MINUTES)

        # Check if schedule changed
        if new_schedule != self.current_schedule:
            self.current_schedule = new_schedule
            logger.info("Schedule updated")
            return True

        logger.info("Schedule unchanged")
        return False

    def get_current_class(self) -> Optional[Dict[str, Any]]:
        """Get currently scheduled class info"""
        return self.current_schedule

    def get_enrolled_students(self) -> List[Dict[str, Any]]:
        """Extract student list from current schedule"""
        if not self.current_schedule:
            return []

        return self.current_schedule.get('enrolled_students', [])

    def is_class_active(self) -> bool:
        """Check if a class is currently scheduled"""
        if not self.current_schedule:
            return False

        # Could add time-based validation here
        return True


class AttendanceQueue:
    """Local queue for attendance records (with SQLite backend)"""

    def __init__(self):
        self.queue: List[Dict[str, Any]] = []
        self.recent_marks: Dict[str, datetime] = {}  # For debouncing

    def add_record(self, student_id: str, course_id: str, confidence: float) -> bool:
        """Add attendance record with debouncing

        Args:
            student_id: Student identifier
            course_id: Course identifier
            confidence: Recognition confidence score

        Returns:
            True if record was added (not debounced)
        """
        # Check debouncing
        key = f"{student_id}:{course_id}"
        now = datetime.now()

        if key in self.recent_marks:
            last_mark_time = self.recent_marks[key]
            elapsed = (now - last_mark_time).total_seconds()

            if elapsed < settings.DEBOUNCE_SECONDS:
                logger.debug(f"Debounced {student_id} ({elapsed:.1f}s < {settings.DEBOUNCE_SECONDS}s)")
                return False

        # Add record
        record = {
            'student_id': student_id,
            'course_id': course_id,
            'timestamp': now.isoformat(),
            'confidence': round(confidence, 3),
            'device_id': settings.DEVICE_UUID
        }

        self.queue.append(record)
        self.recent_marks[key] = now

        logger.info(f"Attendance marked: {student_id} (confidence: {confidence:.3f})")
        return True

    def get_batch(self, size: int = None) -> List[Dict[str, Any]]:
        """Get batch of records for upload

        Args:
            size: Batch size (defaults to settings.BATCH_SIZE)

        Returns:
            List of records
        """
        size = size or settings.BATCH_SIZE
        batch = self.queue[:size]
        return batch

    def remove_batch(self, batch: List[Dict[str, Any]]):
        """Remove successfully uploaded records"""
        for record in batch:
            if record in self.queue:
                self.queue.remove(record)

    def size(self) -> int:
        """Get current queue size"""
        return len(self.queue)

    def clear_old_debounce_entries(self):
        """Clean up debounce dictionary"""
        now = datetime.now()
        cutoff = timedelta(seconds=settings.DEBOUNCE_SECONDS * 2)

        keys_to_remove = [
            key for key, timestamp in self.recent_marks.items()
            if now - timestamp > cutoff
        ]

        for key in keys_to_remove:
            del self.recent_marks[key]


class SyncManager:
    """Orchestrates all sync operations"""

    def __init__(self, classroom_id: str):
        self.classroom_id = classroom_id
        self.api_client = APIClient()
        self.schedule_manager = ScheduleManager(self.api_client)
        self.attendance_queue = AttendanceQueue()

    def sync_schedule_if_needed(self) -> bool:
        """Sync schedule if interval has elapsed

        Returns:
            True if schedule was updated
        """
        if self.schedule_manager.should_sync():
            return self.schedule_manager.sync(self.classroom_id)
        return False

    def upload_attendance_batch(self) -> bool:
        """Upload queued attendance records

        Returns:
            True if upload was successful
        """
        if self.attendance_queue.size() == 0:
            return True

        batch = self.attendance_queue.get_batch()

        if self.api_client.post_attendance(batch):
            self.attendance_queue.remove_batch(batch)
            return True

        return False

    def mark_attendance(self, student_id: str, confidence: float) -> bool:
        """Mark attendance for student

        Args:
            student_id: Student identifier
            confidence: Recognition confidence

        Returns:
            True if record was added
        """
        current_class = self.schedule_manager.get_current_class()

        if not current_class:
            logger.warning("No active class - cannot mark attendance")
            return False

        course_id = current_class.get('course_id')

        return self.attendance_queue.add_record(student_id, course_id, confidence)


if __name__ == "__main__":
    # Test sync manager
    import sys
    from loguru import logger

    logger.add(sys.stderr, level="DEBUG")

    # This will fail without proper API credentials
    sync_manager = SyncManager(classroom_id="LAB-301")

    logger.info("Testing schedule sync...")
    sync_manager.sync_schedule_if_needed()

    logger.info(f"Current class: {sync_manager.schedule_manager.get_current_class()}")
