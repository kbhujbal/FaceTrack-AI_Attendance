"""
Heartbeat API Endpoint
Receives health metrics from Raspberry Pi devices
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import datetime
from loguru import logger

from app.database import get_db
from app.schemas import HeartbeatRequest, HeartbeatResponse

router = APIRouter()


@router.post("/heartbeat", response_model=HeartbeatResponse)
async def device_heartbeat(
    request: HeartbeatRequest,
    db: Session = Depends(get_db)
):
    """
    Receive heartbeat from Raspberry Pi

    Heartbeats include:
    - Device health metrics (CPU temp, disk usage, etc.)
    - Current app version
    - Last sync time
    - Queue depth

    This allows the cloud to:
    - Monitor device health
    - Detect offline devices
    - Trigger alerts for overheating/disk full
    """

    try:
        # Update device record
        query = text("""
            UPDATE edge_devices
            SET
                last_heartbeat = :timestamp,
                status = 'online',
                cpu_temp_celsius = :cpu_temp,
                disk_usage_percent = :disk_usage,
                cache_size_mb = :cache_size,
                app_version = :app_version,
                updated_at = CURRENT_TIMESTAMP
            WHERE device_uuid = :device_id
            RETURNING device_name, classroom_id
        """)

        result = db.execute(query, {
            "device_id": request.device_id,
            "timestamp": request.timestamp,
            "cpu_temp": request.metrics.get("cpu_temp"),
            "disk_usage": request.metrics.get("disk_usage"),
            "cache_size": request.metrics.get("cache_size"),
            "app_version": request.metrics.get("app_version")
        }).fetchone()

        if not result:
            # Device not found - auto-register
            insert_query = text("""
                INSERT INTO edge_devices (
                    device_uuid,
                    device_name,
                    last_heartbeat,
                    status,
                    cpu_temp_celsius,
                    disk_usage_percent
                ) VALUES (
                    :device_id,
                    :device_name,
                    :timestamp,
                    'online',
                    :cpu_temp,
                    :disk_usage
                )
                RETURNING device_name, classroom_id
            """)

            result = db.execute(insert_query, {
                "device_id": request.device_id,
                "device_name": f"PI-{request.device_id[:8]}",
                "timestamp": request.timestamp,
                "cpu_temp": request.metrics.get("cpu_temp"),
                "disk_usage": request.metrics.get("disk_usage")
            }).fetchone()

        db.commit()

        device_name, classroom_id = result if result else (None, None)

        logger.debug(f"Heartbeat from {device_name or request.device_id}")

        return HeartbeatResponse(
            status="acknowledged",
            server_time=datetime.utcnow().isoformat(),
            message="Heartbeat received"
        )

    except Exception as e:
        db.rollback()
        logger.error(f"Error processing heartbeat: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to process heartbeat")
