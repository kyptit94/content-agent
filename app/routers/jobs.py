from datetime import datetime
from uuid import uuid4

from fastapi import APIRouter

from app.config import HealthStatus
from app.config import settings
from app.schemas import JobAccepted
from app.schemas import JobPayload
from app.schemas import JobRequest
from app.services.queue_service import QueueService

router = APIRouter(prefix="/jobs", tags=["jobs"])
queue = QueueService(redis_url=settings.redis_url, queue_name=settings.job_queue_name)


@router.post("", response_model=JobAccepted)
def create_job(job: JobRequest) -> JobAccepted:
    payload = JobPayload(
        job_id=str(uuid4()),
        created_at=datetime.utcnow().isoformat(),
        **job.model_dump(),
    )
    queue.enqueue(payload.model_dump())
    queue.set_job_status(
        job_id=payload.job_id,
        payload={
            "job_id": payload.job_id,
            "status": "queued",
            "topic": payload.topic,
            "mode": payload.mode,
            "queued_at": datetime.utcnow().isoformat(),
        },
    )

    return JobAccepted(
        job_id=payload.job_id,
        status="queued",
        queued_at=datetime.utcnow(),
    )


@router.get("/health", response_model=HealthStatus)
def health_check() -> HealthStatus:
    return HealthStatus(
        queue=settings.job_queue_name,
        local_model=settings.local_llm_model,
        gemini_enabled=bool(settings.gemini_api_key),
        telegram_enabled=settings.telegram_enabled,
    )
