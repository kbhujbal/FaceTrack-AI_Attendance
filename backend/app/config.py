"""
Backend Configuration
"""
from pydantic_settings import BaseSettings
from pydantic import Field, PostgresDsn
from typing import Optional


class Settings(BaseSettings):
    """Application settings"""

    # API Settings
    APP_NAME: str = Field(default="Face Recognition Attendance API")
    APP_VERSION: str = Field(default="1.0.0")
    API_PREFIX: str = Field(default="/api/v1")
    DEBUG: bool = Field(default=False)

    # Server
    HOST: str = Field(default="0.0.0.0")
    PORT: int = Field(default=8000)
    WORKERS: int = Field(default=4)

    # Database
    DATABASE_URL: PostgresDsn = Field(...)
    DB_POOL_SIZE: int = Field(default=20)
    DB_MAX_OVERFLOW: int = Field(default=10)

    # Redis Cache
    REDIS_URL: str = Field(default="redis://localhost:6379/0")
    CACHE_TTL_SCHEDULE: int = Field(default=600)  # 10 minutes
    CACHE_TTL_EMBEDDINGS: int = Field(default=3600)  # 1 hour

    # Message Queue
    CELERY_BROKER_URL: str = Field(default="redis://localhost:6379/1")
    CELERY_RESULT_BACKEND: str = Field(default="redis://localhost:6379/2")

    # Security
    SECRET_KEY: str = Field(...)
    ALGORITHM: str = Field(default="HS256")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(default=1440)  # 24 hours

    # CORS
    CORS_ORIGINS: list = Field(default=["http://localhost:3000"])

    # Rate Limiting
    RATE_LIMIT_PER_MINUTE: int = Field(default=100)

    # Monitoring
    ENABLE_METRICS: bool = Field(default=True)

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
