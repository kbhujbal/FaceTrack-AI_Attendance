"""
Attendance API Endpoint
Receives attendance records from Raspberry Pi devices
"""
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import List
from datetime import datetime
from loguru import logger

from app.database import get_db
from app.schemas import AttendanceRecord, AttendanceBatchRequest, AttendanceBatchResponse

router = APIRouter()


async def process_attendance_async(records: List[dict], db: Session):
    """
    Background task to process attendance records
    This runs asynchronously so the API returns immediately
    """
    try:
        for record in records:
            # Insert attendance log
            query = text("""
                INSERT INTO attendance_logs (
                    student_id,
                    course_id,
                    classroom_id,
                    timestamp,
                    confidence_score,
                    device_id,
                    status
                ) VALUES (
                    :student_id,
                    :course_id,
                    :classroom_id,
                    :timestamp,
                    :confidence,
                    :device_id,
                    'present'
                )
                ON CONFLICT DO NOTHING
            """)

            db.execute(query, {
                "student_id": record["student_id"],
                "course_id": record["course_id"],
                "classroom_id": record.get("classroom_id", "UNKNOWN"),
                "timestamp": record["timestamp"],
                "confidence": record["confidence"],
                "device_id": record["device_id"]
            })

        db.commit()
        logger.info(f"Processed {len(records)} attendance records")

    except Exception as e:
        db.rollback()
        logger.error(f"Error processing attendance: {e}", exc_info=True)


@router.post("/attendance", response_model=AttendanceBatchResponse, status_code=202)
async def submit_attendance(
    request: AttendanceBatchRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """
    Submit batch of attendance records from Raspberry Pi

    Returns 202 Accepted immediately and processes records in background
    This prevents the Pi from waiting for database writes

    Design Pattern: Store-and-Forward with Async Processing
    - Pi gets immediate acknowledgment (< 50ms)
    - Records are queued for background processing
    - Database writes happen asynchronously
    - Handles thundering herd problem at 9:00 AM
    """

    if not request.records:
        raise HTTPException(status_code=400, detail="No records provided")

    if len(request.records) > 100:
        raise HTTPException(status_code=400, detail="Batch size too large (max 100)")

    # Validate record structure
    for record in request.records:
        if not all(k in record for k in ["student_id", "course_id", "timestamp", "confidence"]):
            raise HTTPException(status_code=400, detail="Invalid record structure")

    # Add device_id to each record
    records_with_device = [
        {**record, "device_id": request.device_id}
        for record in request.records
    ]

    # Schedule background processing
    background_tasks.add_task(process_attendance_async, records_with_device, db)

    logger.info(f"Accepted {len(request.records)} records from {request.device_id}")

    return AttendanceBatchResponse(
        status="accepted",
        records_received=len(request.records),
        message="Attendance records queued for processing"
    )


@router.get("/attendance/student/{student_id}")
async def get_student_attendance(
    student_id: str,
    course_id: str = None,
    db: Session = Depends(get_db)
):
    """
    Get attendance history for a student

    Query Parameters:
    - course_id (optional): Filter by specific course
    """

    try:
        if course_id:
            query = text("""
                SELECT
                    al.timestamp,
                    al.course_id,
                    c.course_name,
                    al.confidence_score,
                    al.status
                FROM attendance_logs al
                JOIN courses c ON al.course_id = c.course_id
                WHERE al.student_id = :student_id
                  AND al.course_id = :course_id
                ORDER BY al.timestamp DESC
                LIMIT 100
            """)
            results = db.execute(query, {"student_id": student_id, "course_id": course_id}).fetchall()
        else:
            query = text("""
                SELECT
                    al.timestamp,
                    al.course_id,
                    c.course_name,
                    al.confidence_score,
                    al.status
                FROM attendance_logs al
                JOIN courses c ON al.course_id = c.course_id
                WHERE al.student_id = :student_id
                ORDER BY al.timestamp DESC
                LIMIT 100
            """)
            results = db.execute(query, {"student_id": student_id}).fetchall()

        attendance_records = []
        for row in results:
            timestamp, course_id, course_name, confidence, status = row
            attendance_records.append({
                "timestamp": timestamp.isoformat(),
                "course_id": course_id,
                "course_name": course_name,
                "confidence": float(confidence) if confidence else None,
                "status": status
            })

        return {
            "student_id": student_id,
            "total_records": len(attendance_records),
            "attendance": attendance_records
        }

    except Exception as e:
        logger.error(f"Error fetching student attendance: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch attendance")


@router.get("/attendance/course/{course_id}")
async def get_course_attendance(
    course_id: str,
    date: str = None,
    db: Session = Depends(get_db)
):
    """
    Get attendance summary for a course

    Query Parameters:
    - date (optional): Filter by specific date (YYYY-MM-DD)
    """

    try:
        if date:
            query = text("""
                SELECT
                    s.student_id,
                    s.first_name,
                    s.last_name,
                    al.timestamp,
                    al.confidence_score
                FROM students s
                JOIN enrollments e ON s.student_id = e.student_id
                LEFT JOIN attendance_logs al ON s.student_id = al.student_id
                    AND al.course_id = :course_id
                    AND DATE(al.timestamp) = :date
                WHERE e.course_id = :course_id
                  AND e.status = 'enrolled'
                ORDER BY s.last_name, s.first_name
            """)
            results = db.execute(query, {"course_id": course_id, "date": date}).fetchall()
        else:
            # Get today's attendance
            query = text("""
                SELECT
                    s.student_id,
                    s.first_name,
                    s.last_name,
                    al.timestamp,
                    al.confidence_score
                FROM students s
                JOIN enrollments e ON s.student_id = e.student_id
                LEFT JOIN attendance_logs al ON s.student_id = al.student_id
                    AND al.course_id = :course_id
                    AND DATE(al.timestamp) = CURRENT_DATE
                WHERE e.course_id = :course_id
                  AND e.status = 'enrolled'
                ORDER BY s.last_name, s.first_name
            """)
            results = db.execute(query, {"course_id": course_id}).fetchall()

        attendance_summary = []
        present_count = 0

        for row in results:
            student_id, first_name, last_name, timestamp, confidence = row
            is_present = timestamp is not None

            if is_present:
                present_count += 1

            attendance_summary.append({
                "student_id": student_id,
                "name": f"{first_name} {last_name}",
                "status": "present" if is_present else "absent",
                "timestamp": timestamp.isoformat() if timestamp else None,
                "confidence": float(confidence) if confidence else None
            })

        total_enrolled = len(attendance_summary)
        attendance_percentage = (present_count / total_enrolled * 100) if total_enrolled > 0 else 0

        return {
            "course_id": course_id,
            "date": date or datetime.now().date().isoformat(),
            "total_enrolled": total_enrolled,
            "present": present_count,
            "absent": total_enrolled - present_count,
            "attendance_percentage": round(attendance_percentage, 2),
            "students": attendance_summary
        }

    except Exception as e:
        logger.error(f"Error fetching course attendance: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch course attendance")
