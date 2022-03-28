"""
Face Recognition Attendance System - Raspberry Pi Edge Client
Main application entry point
"""
import sys
import time
import signal
from typing import Optional
from datetime import datetime
from loguru import logger
from pathlib import Path

from config import settings
from camera import CameraManager, FaceRecognizer
from sync_manager import SyncManager


class AttendanceApp:
    """Main application orchestrator"""

    def __init__(self, classroom_id: str):
        self.classroom_id = classroom_id
        self.is_running = False

        # Initialize components
        self.camera = CameraManager()
        self.recognizer = FaceRecognizer()
        self.sync_manager = SyncManager(classroom_id)

        # State tracking
        self.last_schedule_check = 0
        self.last_upload_time = 0
        self.last_cleanup_time = 0

        logger.info(f"AttendanceApp initialized for classroom: {classroom_id}")

    def setup(self) -> bool:
        """Initialize all components"""
        logger.info("Setting up application...")

        # Create necessary directories
        Path("./data").mkdir(exist_ok=True)
        Path("./logs").mkdir(exist_ok=True)

        # Start camera
        if not self.camera.start():
            logger.error("Failed to start camera")
            return False

        # Initial schedule sync
        logger.info("Performing initial schedule sync...")
        if self.sync_manager.sync_schedule_if_needed():
            self._load_student_roster()

        logger.info("Setup complete")
        return True

    def _load_student_roster(self):
        """Load student encodings from current schedule"""
        students = self.sync_manager.schedule_manager.get_enrolled_students()

        if students:
            self.recognizer.load_roster(students)
            logger.info(f"Loaded roster: {len(students)} students")
        else:
            logger.warning("No students in current roster")

    def run(self):
        """Main application loop"""
        self.is_running = True
        logger.info("Application started - monitoring for faces")

        frame_count = 0
        start_time = time.time()

        while self.is_running:
            try:
                current_time = time.time()

                # Periodic schedule sync
                if current_time - self.last_schedule_check >= 60:  # Check every minute
                    if self.sync_manager.sync_schedule_if_needed():
                        self._load_student_roster()
                    self.last_schedule_check = current_time

                # Periodic attendance upload
                if current_time - self.last_upload_time >= settings.BATCH_INTERVAL_SECONDS:
                    self.sync_manager.upload_attendance_batch()
                    self.last_upload_time = current_time

                # Periodic cleanup
                if current_time - self.last_cleanup_time >= 300:  # Every 5 minutes
                    self.sync_manager.attendance_queue.clear_old_debounce_entries()
                    self.last_cleanup_time = current_time

                # Check if class is active
                if not self.sync_manager.schedule_manager.is_class_active():
                    time.sleep(1)  # No class scheduled - idle mode
                    continue

                # Read frame from camera
                frame = self.camera.read_frame()
                if frame is None:
                    continue

                # Process frame (with skipping optimization)
                if not self.camera.should_process_frame():
                    continue

                frame_count += 1

                # Detect faces
                detected_faces = self.recognizer.detect_faces(frame)

                if not detected_faces:
                    continue

                logger.debug(f"Detected {len(detected_faces)} face(s)")

                # Recognize each face
                for face in detected_faces:
                    result = self.recognizer.recognize_face(face.encoding)

                    if result:
                        student_id, confidence = result
                        self.sync_manager.mark_attendance(student_id, confidence)

                # Calculate and log FPS periodically
                if frame_count % 100 == 0:
                    elapsed = time.time() - start_time
                    fps = frame_count / elapsed
                    logger.info(f"Performance: {fps:.2f} FPS, Queue: {self.sync_manager.attendance_queue.size()}")

            except KeyboardInterrupt:
                logger.info("Received shutdown signal")
                break

            except Exception as e:
                logger.error(f"Error in main loop: {e}", exc_info=True)
                time.sleep(1)  # Prevent tight error loop

        self.shutdown()

    def shutdown(self):
        """Graceful shutdown"""
        logger.info("Shutting down...")

        self.is_running = False

        # Final attendance upload
        logger.info("Uploading remaining attendance records...")
        self.sync_manager.upload_attendance_batch()

        # Stop camera
        self.camera.stop()

        logger.info("Shutdown complete")


def setup_logging():
    """Configure logging"""
    logger.remove()  # Remove default handler

    # Console output
    logger.add(
        sys.stderr,
        level=settings.LOG_LEVEL,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan> - <level>{message}</level>"
    )

    # File output with rotation
    logger.add(
        settings.LOG_FILE_PATH,
        rotation="100 MB",
        retention="30 days",
        level="DEBUG",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}"
    )


def signal_handler(sig, frame):
    """Handle termination signals"""
    logger.warning(f"Received signal {sig}")
    sys.exit(0)


def main():
    """Application entry point"""
    # Setup logging
    setup_logging()

    logger.info("=" * 70)
    logger.info("Face Recognition Attendance System - Edge Client")
    logger.info(f"Device: {settings.DEVICE_NAME} ({settings.DEVICE_UUID})")
    logger.info(f"Classroom: {settings.CLASSROOM_ID}")
    logger.info("=" * 70)

    # Validate configuration
    if not settings.CLASSROOM_ID:
        logger.error("CLASSROOM_ID not configured. Set in .env file.")
        sys.exit(1)

    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Create and run application
    app = AttendanceApp(classroom_id=settings.CLASSROOM_ID)

    if not app.setup():
        logger.error("Application setup failed")
        sys.exit(1)

    try:
        app.run()
    except Exception as e:
        logger.critical(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
