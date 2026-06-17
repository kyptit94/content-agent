from fastapi import FastAPI
import json, os
from datetime import datetime

app = FastAPI()

@app.get("/")
def root():
    return {"service": "content-agent-v2", "status": "running"}

@app.get("/web/jobs")
def list_jobs(limit: int = 20):
    """List recent jobs from Redis."""
    import redis
    r = redis.from_url(os.getenv("REDIS_URL", "redis://redis:6379/0"), decode_responses=True)
    job_ids = r.lrange("jobs:recent", 0, limit-1)
    jobs = []
    for jid in job_ids:
        raw = r.get(f"job:{jid}")
        if raw:
            jobs.append(json.loads(raw))
    return {"items": jobs}

@app.get("/web/jobs/{job_id}/audio")
def get_audio(job_id: str):
    from fastapi.responses import FileResponse
    path = f"/app/data/outputs/{job_id}.mp3"
    import os
    if os.path.exists(path):
        return FileResponse(path, media_type="audio/mpeg")
    return {"error": "not found"}
