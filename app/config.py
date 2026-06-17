from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Core
    redis_url: str = Field(default="redis://redis:6379/0")
    job_queue_name: str = Field(default="content_jobs")

    # Ollama (native host, GPU)
    ollama_host: str = Field(default="http://ollama:11434")
    local_llm_model: str = Field(default="mistral:7b")
    scraper_llm: str = Field(default="qwen2.5:3b")

    # Kokoro TTS
    voice_api_url: str = Field(default="http://voice:8010")
    kokoro_voice: str = Field(default="af_heart")

    # Video compose
    video_size: str = Field(default="portrait")
    video_reencode_crf: int = Field(default=28)
    video_reencode_preset: str = Field(default="p1")
    video_burn_subtitles: bool = Field(default=False)

    # Stock video
    pexels_api_key: str = Field(default="")
    pixabay_api_key: str = Field(default="")
    stock_video_cache_ttl_sec: int = Field(default=604800)

    # Telegram
    telegram_bot_token: str | None = Field(default=None)
    telegram_chat_id: str | None = Field(default=None)

    # Auto-publish
    auto_publish_enabled: bool = Field(default=True)
    auto_publish_platforms: str = Field(default="facebook,youtube")
    facebook_page_id: str = Field(default="")
    facebook_page_access_token: str = Field(default="")
    youtube_client_id: str = Field(default="")
    youtube_client_secret: str = Field(default="")
    youtube_refresh_token: str = Field(default="")
    youtube_privacy_status: str = Field(default="public")

    # Web admin
    web_admin_token: str = Field(default="change-me")
    ingest_dir: str = Field(default="/app/data/uploads")


settings = Settings()