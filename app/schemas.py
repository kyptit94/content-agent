from datetime import datetime
from enum import Enum
from pydantic import BaseModel
from pydantic import Field


class ContentMode(str, Enum):
    sales = "sales"
    story = "story"


class JobRequest(BaseModel):
    mode: ContentMode
    topic: str = Field(min_length=3, max_length=500)
    language: str = Field(default="vi")
    tone: str = Field(default="friendly")
    use_gemini_refine: bool = Field(default=False)
    create_audio: bool = Field(default=True)
    create_video: bool = Field(default=False)
    video_source_type: str = Field(default="self", description="self or internet")
    user_video_path: str | None = Field(default=None)
    voice_sample_filename: str | None = Field(default=None)
    edge_tts_voice: str | None = Field(default=None)
    video_keyword: str | None = Field(default=None)
    feedback_note: str | None = Field(default=None, max_length=500)
    revision_of_job_id: str | None = Field(default=None)
    feedback_round: int = Field(default=0)
    notify_telegram: bool = Field(default=False)
    telegram_chat_id: str | None = Field(default=None)


class JobPayload(JobRequest):
    job_id: str
    created_at: str


class JobAccepted(BaseModel):
    job_id: str
    status: str
    queued_at: datetime


class SynthesisRequest(BaseModel):
    text: str
    language: str = "vi"
    speaker_wav: str
    output_name: str
