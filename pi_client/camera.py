"""
Camera module for face detection and recognition
"""
import cv2
import face_recognition
import numpy as np
from typing import List, Tuple, Optional
from dataclasses import dataclass
from loguru import logger
from config import settings


@dataclass
class DetectedFace:
    """Represents a detected face with its encoding and location"""
    encoding: np.ndarray
    location: Tuple[int, int, int, int]  # (top, right, bottom, left)
    confidence: float = 1.0


class CameraManager:
    """Manages camera capture and face detection"""

    def __init__(self):
        self.camera: Optional[cv2.VideoCapture] = None
        self.frame_count = 0
        self.is_running = False

    def start(self) -> bool:
        """Initialize and start camera"""
        try:
            self.camera = cv2.VideoCapture(settings.CAMERA_INDEX)
            self.camera.set(cv2.CAP_PROP_FRAME_WIDTH, settings.CAMERA_WIDTH)
            self.camera.set(cv2.CAP_PROP_FRAME_HEIGHT, settings.CAMERA_HEIGHT)
            self.camera.set(cv2.CAP_PROP_FPS, settings.CAMERA_FPS)

            if not self.camera.isOpened():
                logger.error("Failed to open camera")
                return False

            self.is_running = True
            logger.info(f"Camera started: {settings.CAMERA_WIDTH}x{settings.CAMERA_HEIGHT}@{settings.CAMERA_FPS}fps")
            return True

        except Exception as e:
            logger.error(f"Camera initialization error: {e}")
            return False

    def stop(self):
        """Release camera resources"""
        if self.camera:
            self.camera.release()
            self.is_running = False
            logger.info("Camera stopped")

    def read_frame(self) -> Optional[np.ndarray]:
        """Read a single frame from camera"""
        if not self.camera or not self.is_running:
            return None

        ret, frame = self.camera.read()
        if not ret:
            logger.warning("Failed to read frame")
            return None

        self.frame_count += 1
        return frame

    def should_process_frame(self) -> bool:
        """Determine if current frame should be processed (skip logic)"""
        return self.frame_count % settings.FRAME_SKIP == 0


class FaceRecognizer:
    """Handles face detection and recognition"""

    def __init__(self):
        self.known_encodings: List[np.ndarray] = []
        self.known_ids: List[str] = []
        self.model = settings.RECOGNITION_MODEL

    def load_roster(self, students: List[dict]):
        """Load student face encodings from API response

        Args:
            students: List of dicts with 'student_id' and 'face_encoding' keys
        """
        self.known_encodings = []
        self.known_ids = []

        for student in students:
            try:
                encoding_bytes = student.get('face_encoding')
                if encoding_bytes:
                    # Convert bytes back to numpy array
                    encoding = np.frombuffer(encoding_bytes, dtype=np.float64)
                    self.known_encodings.append(encoding)
                    self.known_ids.append(student['student_id'])
            except Exception as e:
                logger.warning(f"Failed to load encoding for {student.get('student_id')}: {e}")

        logger.info(f"Loaded {len(self.known_encodings)} student encodings")

    def detect_faces(self, frame: np.ndarray) -> List[DetectedFace]:
        """Detect and encode faces in frame

        Args:
            frame: BGR image from camera

        Returns:
            List of DetectedFace objects
        """
        # Resize frame for faster processing
        small_frame = cv2.resize(frame, (0, 0), fx=settings.FRAME_SCALE, fy=settings.FRAME_SCALE)

        # Convert BGR to RGB (face_recognition uses RGB)
        rgb_frame = cv2.cvtColor(small_frame, cv2.COLOR_BGR2RGB)

        # Detect face locations
        face_locations = face_recognition.face_locations(rgb_frame, model=self.model)

        if not face_locations:
            return []

        # Filter out small faces
        scale_factor = 1 / settings.FRAME_SCALE
        filtered_locations = []
        for (top, right, bottom, left) in face_locations:
            face_height = bottom - top
            face_width = right - left
            if face_height >= settings.MIN_FACE_SIZE and face_width >= settings.MIN_FACE_SIZE:
                # Scale back to original frame coordinates
                filtered_locations.append((
                    int(top * scale_factor),
                    int(right * scale_factor),
                    int(bottom * scale_factor),
                    int(left * scale_factor)
                ))

        if not filtered_locations:
            return []

        # Encode faces
        face_encodings = face_recognition.face_encodings(rgb_frame, face_locations)

        detected_faces = []
        for encoding, location in zip(face_encodings, filtered_locations):
            detected_faces.append(DetectedFace(
                encoding=encoding,
                location=location,
                confidence=1.0
            ))

        return detected_faces

    def recognize_face(self, face_encoding: np.ndarray) -> Optional[Tuple[str, float]]:
        """Match face encoding against known roster

        Args:
            face_encoding: 128-d face embedding

        Returns:
            Tuple of (student_id, distance) or None if no match
        """
        if not self.known_encodings:
            logger.warning("No known encodings loaded")
            return None

        # Calculate distances to all known faces
        distances = face_recognition.face_distance(self.known_encodings, face_encoding)

        # Find best match
        best_match_idx = np.argmin(distances)
        best_distance = distances[best_match_idx]

        if best_distance < settings.RECOGNITION_THRESHOLD:
            student_id = self.known_ids[best_match_idx]
            confidence = 1 - best_distance  # Convert distance to confidence score
            logger.debug(f"Recognized {student_id} with distance {best_distance:.3f}")
            return student_id, confidence

        logger.debug(f"No match found (best distance: {best_distance:.3f})")
        return None

    def draw_debug_overlay(self, frame: np.ndarray, faces: List[DetectedFace],
                          recognized_ids: List[Optional[str]]) -> np.ndarray:
        """Draw bounding boxes and labels on frame for debugging

        Args:
            frame: Original frame
            faces: Detected faces
            recognized_ids: Corresponding student IDs (or None)

        Returns:
            Frame with overlay
        """
        for face, student_id in zip(faces, recognized_ids):
            top, right, bottom, left = face.location

            # Draw box
            color = (0, 255, 0) if student_id else (0, 0, 255)
            cv2.rectangle(frame, (left, top), (right, bottom), color, 2)

            # Draw label
            label = student_id if student_id else "Unknown"
            cv2.rectangle(frame, (left, bottom - 25), (right, bottom), color, cv2.FILLED)
            cv2.putText(frame, label, (left + 6, bottom - 6),
                       cv2.FONT_HERSHEY_DUPLEX, 0.6, (255, 255, 255), 1)

        return frame


if __name__ == "__main__":
    # Test camera functionality
    from loguru import logger
    import sys

    logger.add(sys.stderr, level="DEBUG")

    camera = CameraManager()
    recognizer = FaceRecognizer()

    if not camera.start():
        logger.error("Failed to start camera")
        sys.exit(1)

    logger.info("Camera test started. Press 'q' to quit.")

    try:
        while True:
            frame = camera.read_frame()
            if frame is None:
                continue

            if camera.should_process_frame():
                faces = recognizer.detect_faces(frame)
                logger.info(f"Detected {len(faces)} faces")

                # Draw overlay
                if faces:
                    frame = recognizer.draw_debug_overlay(frame, faces, [None] * len(faces))

            cv2.imshow('Camera Test', frame)

            if cv2.waitKey(1) & 0xFF == ord('q'):
                break

    finally:
        camera.stop()
        cv2.destroyAllWindows()
