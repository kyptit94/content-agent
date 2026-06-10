from pydantic import BaseModel
from pydantic import Field
from pydantic import computed_field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    redis_url: str = Field(default="redis://redis:6379/0", alias="REDIS_URL")
    job_queue_name: str = Field(default="content_jobs", alias="JOB_QUEUE_NAME")

    ollama_base_url: str = Field(default="http://ollama:11434", alias="OLLAMA_BASE_URL")
    local_llm_model: str = Field(default="qwen2.5:3b", alias="LOCAL_LLM_MODEL")

    gemini_api_key: str | None = Field(default=None, alias="GEMINI_API_KEY")
    gemini_model: str = Field(default="gemini-1.5-flash", alias="GEMINI_MODEL")
    gemini_precheck_mode: str = Field(default="risky", alias="GEMINI_PRECHECK_MODE")
    gemini_precheck_cache_ttl_sec: int = Field(default=86400, alias="GEMINI_PRECHECK_CACHE_TTL_SEC")
    gemini_refine_cache_ttl_sec: int = Field(default=604800, alias="GEMINI_REFINE_CACHE_TTL_SEC")

    telegram_bot_token: str | None = Field(default=None, alias="TELEGRAM_BOT_TOKEN")
    telegram_chat_id: str | None = Field(default=None, alias="TELEGRAM_CHAT_ID")
    delete_output_after_telegram: bool = Field(
        default=True,
        alias="DELETE_OUTPUT_AFTER_TELEGRAM",
    )
    feedback_max_rounds: int = Field(default=1, alias="FEEDBACK_MAX_ROUNDS")
    feedback_note_max_chars: int = Field(default=180, alias="FEEDBACK_NOTE_MAX_CHARS")
    auto_topic_interval_minutes: int = Field(default=15, alias="AUTO_TOPIC_INTERVAL_MINUTES")
    auto_topic_default_mode: str = Field(default="sales", alias="AUTO_TOPIC_DEFAULT_MODE")

    voice_api_url: str = Field(default="http://voice:8010", alias="VOICE_API_URL")
    pexels_api_key: str | None = Field(default=None, alias="PEXELS_API_KEY")
    pixabay_api_key: str | None = Field(default=None, alias="PIXABAY_API_KEY")
    video_size: str = Field(default="portrait", alias="VIDEO_SIZE")
    stock_video_cache_ttl_sec: int = Field(default=604800, alias="STOCK_VIDEO_CACHE_TTL_SEC")
    video_preserve_quality: bool = Field(default=True, alias="VIDEO_PRESERVE_QUALITY")
    video_text_overlay: bool = Field(default=False, alias="VIDEO_TEXT_OVERLAY")
    video_reencode_crf: int = Field(default=18, alias="VIDEO_REENCODE_CRF")
    video_reencode_preset: str = Field(default="medium", alias="VIDEO_REENCODE_PRESET")

    auto_publish_enabled: bool = Field(default=False, alias="AUTO_PUBLISH_ENABLED")
    auto_publish_platforms_raw: str = Field(default="youtube", alias="AUTO_PUBLISH_PLATFORMS")
    social_webhook_url: str | None = Field(default=None, alias="SOCIAL_WEBHOOK_URL")

    youtube_client_id: str | None = Field(default=None, alias="YOUTUBE_CLIENT_ID")
    youtube_client_secret: str | None = Field(default=None, alias="YOUTUBE_CLIENT_SECRET")
    youtube_refresh_token: str | None = Field(default=None, alias="YOUTUBE_REFRESH_TOKEN")
    youtube_privacy_status: str = Field(default="private", alias="YOUTUBE_PRIVACY_STATUS")

    facebook_page_id: str | None = Field(default=None, alias="FACEBOOK_PAGE_ID")
    facebook_page_access_token: str | None = Field(default=None, alias="FACEBOOK_PAGE_ACCESS_TOKEN")

    web_admin_token: str = Field(default="change-me", alias="WEB_ADMIN_TOKEN")
    ingest_dir: str = Field(default="/app/data/uploads", alias="INGEST_DIR")

    @computed_field
    @property
    def telegram_enabled(self) -> bool:
        return bool(self.telegram_bot_token)

    @computed_field
    @property
    def auto_publish_platforms(self) -> list[str]:
        return [item.strip() for item in self.auto_publish_platforms_raw.split(",") if item.strip()]


settings = Settings()


class HealthStatus(BaseModel):
    status: str = "ok"
    queue: str
    local_model: str
    gemini_enabled: bool
    telegram_enabled: bool
