from pathlib import Path


class StorageService:
    def __init__(self) -> None:
        self.jobs_dir = Path("/app/data/jobs")
        self.output_dir = Path("/app/data/outputs")
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def save_markdown(self, job_id: str, content: str) -> str:
        path = self.jobs_dir / f"{job_id}.md"
        path.write_text(content, encoding="utf-8")
        return str(path)
