"""
Schedule API Endpoint
Returns current class schedule and enrolled student embeddings
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import List, Optional
from datetime import datetime
import numpy as np
from loguru import logger

from app.database import get_db
from app.schemas import ScheduleResponse, StudentEmbedding

router = APIRouter()


@router.get("/schedule", response_model=Optional[ScheduleResponse])
async def get_schedule(
    room_id: str = Query(..., description="Classroom ID"),
    device_id: str = Query(..., description="Raspberry Pi UUID"),
    db: Session = Depends(get_db)
):
    """
    Get current class schedule and enrolled students for a classroom

    This endpoint is called by the Raspberry Pi every 10 minutes to:
    1. Check what class is scheduled NOW in this classroom
    2. Download face embeddings ONLY for students enrolled in that class

    Returns 204 No Content if no class is scheduled at current time
    """

    try:
        current_time = datetime.now()
        day_of_week = current_time.weekday()  # 0=Monday, 6=Sunday
        current_time_only = current_time.time()
        current_date = current_time.date()

        # Query: Find current schedule using stored function
        query = text("""
            SELECT
                s.schedule_id,
                s.course_id,
                c.course_code,
                c.course_name,
                s.start_time,
                s.end_time,
                s.classroom_id
            FROM schedules s
            JOIN courses c ON s.course_id = c.course_id
            WHERE s.classroom_id = :room_id
              AND s.is_active = TRUE
              AND c.is_active = TRUE
              AND s.day_of_week = :day_of_week
              AND :current_time BETWEEN s.start_time AND s.end_time
              AND :current_date BETWEEN s.effective_from AND s.effective_to
            LIMIT 1
        """)

        result = db.execute(
            query,
            {
                "room_id": room_id,
                "day_of_week": day_of_week,
                "current_time": current_time_only,
                "current_date": current_date
            }
        ).fetchone()

        if not result:
            logger.info(f"No class scheduled for {room_id} at {current_time}")
            return None  # FastAPI returns 204 No Content

        schedule_id, course_id, course_code, course_name, start_time, end_time, classroom_id = result

        # Query: Get enrolled students with face encodings
        students_query = text("""
            SELECT DISTINCT
                s.student_id,
                s.first_name,
                s.last_name,
                s.email,
                s.face_encoding
            FROM students s
            JOIN enrollments e ON s.student_id = e.student_id
            WHERE e.course_id = :course_id
              AND e.status = 'enrolled'
              AND s.status = 'active'
              AND s.face_encoding IS NOT NULL
        """)

        students_result = db.execute(students_query, {"course_id": course_id}).fetchall()

        # Build student list with embeddings
        enrolled_students = []
        for student_row in students_result:
            student_id, first_name, last_name, email, face_encoding_bytes = student_row

            enrolled_students.append({
                "student_id": student_id,
                "name": f"{first_name} {last_name}",
                "email": email,
                "face_encoding": face_encoding_bytes  # Binary data sent directly
            })

        logger.info(
            f"Schedule for {room_id}: {course_name} "
            f"({len(enrolled_students)} students enrolled)"
        )

        return ScheduleResponse(
            schedule_id=str(schedule_id),
            course_id=course_id,
            course_code=course_code,
            course_name=course_name,
            start_time=start_time.isoformat(),
            end_time=end_time.isoformat(),
            classroom_id=classroom_id,
            enrolled_students=enrolled_students
        )

    except Exception as e:
        logger.error(f"Error fetching schedule: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch schedule")


@router.get("/schedule/preview", response_model=List[dict])
async def preview_schedule(
    room_id: str = Query(..., description="Classroom ID"),
    db: Session = Depends(get_db)
):
    """
    Preview week's schedule for a classroom (for debugging/admin)
    """

    try:
        query = text("""
            SELECT
                s.day_of_week,
                s.start_time,
                s.end_time,
                c.course_code,
                c.course_name,
                COUNT(DISTINCT e.student_id) as enrolled_count
            FROM schedules s
            JOIN courses c ON s.course_id = c.course_id
            LEFT JOIN enrollments e ON c.course_id = e.course_id
                AND e.status = 'enrolled'
            WHERE s.classroom_id = :room_id
              AND s.is_active = TRUE
              AND c.is_active = TRUE
              AND CURRENT_DATE BETWEEN s.effective_from AND s.effective_to
            GROUP BY s.day_of_week, s.start_time, s.end_time,
                     c.course_code, c.course_name
            ORDER BY s.day_of_week, s.start_time
        """)

        results = db.execute(query, {"room_id": room_id}).fetchall()

        day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

        schedule_preview = []
        for row in results:
            day_of_week, start_time, end_time, course_code, course_name, enrolled_count = row
            schedule_preview.append({
                "day": day_names[day_of_week],
                "start_time": start_time.isoformat(),
                "end_time": end_time.isoformat(),
                "course": f"{course_code} - {course_name}",
                "enrolled_students": enrolled_count
            })

        return schedule_preview

    except Exception as e:
        logger.error(f"Error fetching schedule preview: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch schedule preview")
