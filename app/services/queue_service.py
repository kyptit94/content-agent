import json
from redis import Redis


class QueueService:
    def __init__(self, redis_url: str, queue_name: str):
        self._client = Redis.from_url(redis_url, decode_responses=True)
        self._queue_name = queue_name

    def enqueue(self, payload: dict) -> None:
        self._client.rpush(self._queue_name, json.dumps(payload, ensure_ascii=False))

    def dequeue_blocking(self, timeout_seconds: int = 0) -> dict | None:
        result = self._client.blpop(self._queue_name, timeout=timeout_seconds)
        if result is None:
            return None
        _, raw_message = result
        return json.loads(raw_message)

    def set_job_status(self, job_id: str, payload: dict) -> None:
        key = f"job:{job_id}"
        self._client.set(key, json.dumps(payload, ensure_ascii=False))
        self._client.lrem("jobs:recent", 0, job_id)
        self._client.lpush("jobs:recent", job_id)
        self._client.ltrim("jobs:recent", 0, 200)

    def get_job_status(self, job_id: str) -> dict | None:
        raw = self._client.get(f"job:{job_id}")
        if not raw:
            return None
        return json.loads(raw)

    def mark_job_deleted(self, job_id: str) -> None:
        self._client.set(f"job:deleted:{job_id}", "1")

    def is_job_deleted(self, job_id: str) -> bool:
        return bool(self._client.get(f"job:deleted:{job_id}"))

    def delete_job(self, job_id: str) -> None:
        self.mark_job_deleted(job_id)
        self._client.delete(f"job:{job_id}")
        self._client.lrem("jobs:recent", 0, job_id)

    def get_queue_position(self, job_id: str) -> int | None:
        items = self._client.lrange(self._queue_name, 0, -1)
        for index, raw_item in enumerate(items, start=1):
            try:
                payload = json.loads(raw_item)
            except Exception:
                continue
            if payload.get("job_id") == job_id:
                return index
        return None

    def list_recent_jobs(self, limit: int = 30) -> list[dict]:
        job_ids = self._client.lrange("jobs:recent", 0, max(0, limit - 1))
        jobs: list[dict] = []
        for job_id in job_ids:
            item = self.get_job_status(job_id)
            if item:
                if item.get("status") == "queued":
                    item["queue_position"] = self.get_queue_position(job_id)
                jobs.append(item)
        return jobs
