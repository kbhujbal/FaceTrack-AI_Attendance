"""
Configuration management for Raspberry Pi Edge Client
"""
from pydantic_settings import BaseSettings
from pydantic import Field, field_validator
from typing import Optional
import uuid


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""

    # Device Identity
    DEVICE_UUID: str = Field(default_factory=lambda: str(uuid.uuid4()))
    DEVICE_NAME: str = Field(default="PI-UNKNOWN")
    CLASSROOM_ID: Optional[str] = None

    # Cloud API Configuration
    API_BASE_URL: str = Field(default="https://api.attendance.example.com")
    API_VERSION: str = Field(default="v1")
    API_KEY: str = Field(...)
    API_TIMEOUT: int = Field(default=30, ge=5, le=120)
    API_RETRY_ATTEMPTS: int = Field(default=3, ge=1, le=10)

    # Schedule Sync Settings
    SYNC_INTERVAL_MINUTES: int = Field(default=10, ge=1, le=60)
    PRELOAD_MINUTES: int = Field(default=15, ge=5, le=60)

    # Camera Settings
    CAMERA_INDEX: int = Field(default=0)
    CAMERA_WIDTH: int = Field(default=640, ge=320, le=1920)
    CAMERA_HEIGHT: int = Field(default=480, ge=240, le=1080)
    CAMERA_FPS: int = Field(default=30, ge=10, le=60)
    FRAME_SKIP: int = Field(default=3, ge=1, le=10)
    FRAME_SCALE: float = Field(default=0.25, ge=0.1, le=1.0)

    # Face Recognition Settings
    RECOGNITION_MODEL: str = Field(default="hog")
    RECOGNITION_THRESHOLD: float = Field(default=0.6, ge=0.3, le=0.9)
    MIN_FACE_SIZE: int = Field(default=50, ge=20, le=200)

    # Debouncing
    DEBOUNCE_SECONDS: int = Field(default=30, ge=10, le=300)

    # Local Queue Settings
    LOCAL_DB_PATH: str = Field(default="./data/local_queue.db")
    BATCH_SIZE: int = Field(default=10, ge=1, le=100)
    BATCH_INTERVAL_SECONDS: int = Field(default=60, ge=10, le=300)

    # Logging
    LOG_LEVEL: str = Field(default="INFO")
    LOG_FILE_PATH: str = Field(default="./logs/pi_client.log")

    @field_validator("API_BASE_URL")
    @classmethod
    def validate_api_url(cls, v: str) -> str:
        return v.rstrip("/")

    @property
    def api_schedule_endpoint(self) -> str:
        return f"{self.API_BASE_URL}/api/{self.API_VERSION}/schedule"

    @property
    def api_attendance_endpoint(self) -> str:
        return f"{self.API_BASE_URL}/api/{self.API_VERSION}/attendance"

    @property
    def api_heartbeat_endpoint(self) -> str:
        return f"{self.API_BASE_URL}/api/{self.API_VERSION}/heartbeat"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True


_settings: Optional[Settings] = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


settings = get_settings()
