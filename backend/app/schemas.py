"""
Pydantic schemas for request/response validation
"""
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime


class StudentEmbedding(BaseModel):
    """Student with face embedding"""
    student_id: str
    name: str
    email: str
    face_encoding: bytes


class ScheduleResponse(BaseModel):
    """Response for schedule endpoint"""
    schedule_id: str
    course_id: str
    course_code: str
    course_name: str
    start_time: str
    end_time: str
    classroom_id: str
    enrolled_students: List[Dict[str, Any]]


class AttendanceRecord(BaseModel):
    """Single attendance record"""
    student_id: str
    course_id: str
    timestamp: str
    confidence: float = Field(ge=0.0, le=1.0)


class AttendanceBatchRequest(BaseModel):
    """Batch attendance submission from Pi"""
    device_id: str
    records: List[Dict[str, Any]]


class AttendanceBatchResponse(BaseModel):
    """Response for batch attendance submission"""
    status: str
    records_received: int
    message: str


class HeartbeatRequest(BaseModel):
    """Heartbeat from Raspberry Pi"""
    device_id: str
    timestamp: str
    metrics: Dict[str, Any]


class HeartbeatResponse(BaseModel):
    """Heartbeat acknowledgment"""
    status: str
    server_time: str
    message: str
