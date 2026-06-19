"""
Pipeline worker: topic → scrape → translate → TTS → image → compose → publish.
Runs on GPU (NVENC encode + Kokoro TTS).
"""
import os, json, time, subprocess, requests, random
from pathlib import Path
from datetime import datetime
from uuid import uuid4

import redis
import sys

# Redis client
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
redis_client = redis.from_url(REDIS_URL, decode_responses=True)

def log(msg: str):
    """Log to both stdout and Redis for realtime web display."""
    timestamp = datetime.utcnow().strftime("%H:%M:%S")
    full_msg = f"[{timestamp}] {msg}"
    print(full_msg)
    sys.stdout.flush()
    try:
        redis_client.lpush("logs:recent", full_msg)
        redis_client.ltrim("logs:recent", 0, 100)
    except Exception:
        pass

# Config
OLLAMA_URL = os.getenv("OLLAMA_HOST", "http://ollama:11434")
VOICE_URL = os.getenv("VOICE_API_URL", "http://voice:8010")
SCRAPER_MODEL = os.getenv("SCRAPER_LLM", "qwen2.5:3b")
TRANSLATE_MODEL = os.getenv("LOCAL_LLM_MODEL", "mistral:7b")
KOKORO_VOICE = os.getenv("KOKORO_VOICE", "af_heart")
MC_VIDEO_PATH = os.getenv("MC_VIDEO_PATH", "/app/data/mc_video.mp4")

# Stock API keys
PEXELS_KEY = os.getenv("PEXELS_API_KEY", "")
PIXABAY_KEY = os.getenv("PIXABAY_API_KEY", "")

from app.services.scraper_service import ScraperService
from app.services.translator_service import TranslatorService
from app.services.image_service import ImageService
from app.services.video_composer import VideoComposer

scraper = ScraperService(OLLAMA_URL, model=SCRAPER_MODEL)
translator = TranslatorService(OLLAMA_URL, model=TRANSLATE_MODEL)
imager = ImageService(PEXELS_KEY, PIXABAY_KEY, OLLAMA_URL)
composer = VideoComposer(crf=int(os.getenv("VIDEO_REENCODE_CRF", "28")), preset=os.getenv("VIDEO_REENCODE_PRESET", "p1"))

TOPICS = [
    "a haunted house with a dark secret",
    "a mysterious stranger in a small town",
    "a cursed object found in an antique shop",
    "a ghost that can only be seen in mirrors",
    "a door that leads to another dimension",
    "a fortune teller whose predictions always come true",
    "a forest where people go missing",
    "an AI that gains consciousness",
    "a time loop that traps someone in their worst day",
    "a diary found in an abandoned hospital"
]

def call_llm(prompt, model="qwen2.5:3b", temp=0.9):
    try:
        r = requests.post(f"{OLLAMA_URL}/api/generate", json={"model":model,"prompt":prompt,"stream":False,"options":{"temperature":temp,"num_predict":150}}, timeout=60)
        return r.json().get("response","").strip()
    except:
        return ""

def kokoro_tts(text, job_id):
    """Call Kokoro TTS API to generate MP3."""
    try:
        r = requests.post(f"{VOICE_URL}/synthesize_kokoro", json={"text":text[:3000],"language":"en","output_name":f"{job_id}.mp3"}, timeout=300)
        if r.status_code == 200:
            return f"/app/data/outputs/{job_id}.mp3"
    except:
        pass
    return ""

def compose_publish(job_id, audio_path, bg_image, story_title, mc_video=""):
    """Compose video with NVENC and publish to platforms."""
    video_path = composer.compose(job_id, bg_image, audio_path, mc_video)
    if not video_path:
        return False

    # Publish to configured platforms
    platforms = os.getenv("AUTO_PUBLISH_PLATFORMS", "").split(",")
    fb_token = os.getenv("FACEBOOK_PAGE_ACCESS_TOKEN", "")
    fb_page = os.getenv("FACEBOOK_PAGE_ID", "")
    yt_client_id = os.getenv("YOUTUBE_CLIENT_ID", "")

    for plat in platforms:
        plat = plat.strip()
        try:
            if plat == "facebook" and fb_token and fb_page:
                subprocess.run(
                    ["curl", "-s", "-X", "POST",
                     f"https://graph.facebook.com/v19.0/{fb_page}/video_reels",
                     "-F", f"access_token={fb_token}",
                     "-F", f"upload_phase=finish",
                     "-F", f"video_state=PUBLISHED",
                     "-F", f"description={story_title[:100]}",
                     "-F", f"file=@{video_path}"],
                    capture_output=True, timeout=120)
            if plat == "youtube" and yt_client_id:
                # YouTube Short publishing would go here with proper OAuth
                pass
        except:
            pass
    return True

def notify_telegram(text):
    """Send notification via Telegram."""
    bot = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat = os.getenv("TELEGRAM_CHAT_ID", "")
    if not bot or not chat:
        return
    try:
        requests.get(f"https://api.telegram.org/bot{bot}/sendMessage", params={"chat_id":chat,"text":text[:1000]}, timeout=10)
    except:
        pass

def main():
    # Monkey-patch stdout to also write to Redis for realtime web logs
    import io
    class _LogStream(io.StringIO):
        def write(self, s):
            super().write(s)
            # Also write to Redis (trim prefix to keep clean)
            for line in s.strip().split("\n"):
                line = line.strip()
                if line:
                    full_msg = f"[{datetime.utcnow().strftime('%H:%M:%S')}] {line}"
                    try:
                        redis_client.lpush("logs:recent", full_msg)
                        redis_client.ltrim("logs:recent", 0, 100)
                    except Exception:
                        pass
            return len(s)
    sys.stdout = _LogStream()

    log("Pipeline worker starting...")
    while True:
        try:
            # Check for pending job requests from web UI
            topic = None
            pending_id = None
            try:
                pending_id = redis_client.rpop("jobs:pending")
                if pending_id:
                    print(f"[WORKER] Picked pending job: {pending_id}")
                    # Use a default topic for user-requested jobs
                    topic = random.choice(TOPICS)
                    # Update job status to running
                    job_data = json.loads(redis_client.get(f"job:{pending_id}") or "{}")
                    job_data["status"] = "running"
                    redis_client.set(f"job:{pending_id}", json.dumps(job_data))
            except Exception:
                pass

            # Fallback: pick a random topic if no pending job
            if not topic:
                topic = random.choice(TOPICS)

            print(f"\n[WORKER] === New job: {topic[:80]} ===")
            notify_telegram(f"📖 Scraping: {topic[:100]}")

            # Use pending job_id if available, otherwise generate new one
            job_id = pending_id if pending_id else str(uuid4())

            # 1. Scrape/generate story
            story = scraper.scrape(topic, language="en")
            if not story["content"]:
                print("[WORKER] Scrape failed, skipping")
                if pending_id:
                    redis_client.set(f"job:{pending_id}", json.dumps({
                        "job_id": pending_id, "status": "failed",
                        "title": "Scrape failed",
                    }))
                time.sleep(10)
                continue

            # 2. Translate to English (if needed)
            if story["language"] != "en" and story["language"] != "english":
                en = translator.translate_to_english(story["content"], story["language"])
                if en and len(en) > 50:
                    story["content"] = en

            # 3. Generate TTS audio
            audio_path = kokoro_tts(story["content"], job_id)
            if not audio_path:
                print("[WORKER] TTS failed, skipping")
                if pending_id:
                    redis_client.set(f"job:{pending_id}", json.dumps({
                        "job_id": pending_id, "status": "failed",
                        "title": story.get("title", "TTS failed"),
                    }))
                time.sleep(10)
                continue
            print(f"[WORKER] Audio created: {audio_path}")
            notify_telegram(f"🎙️ TTS done: [{job_id}] {story['title'][:80]}")

            # 4. Generate AI images — one per sentence
            print(f"[WORKER] Generating AI images for {story['title'][:80]}...")
            image_paths = imager.generate_images_for_sentences(job_id, story["content"])
            if not image_paths:
                # Fallback: single background image
                bg_image = imager.generate_background(job_id, story["content"])
                image_paths = [bg_image]
            print(f"[WORKER] Generated {len(image_paths)} images")
            notify_telegram(f"🖼️ {len(image_paths)} images ready: [{job_id}]")

            # 5. Compose slideshow video with MC PIP + NVENC
            mc_video = MC_VIDEO_PATH if Path(MC_VIDEO_PATH).exists() else ""
            try:
                video_path = composer.compose_slideshow(job_id, image_paths, audio_path, mc_video)
                if video_path and Path(video_path).exists() and Path(video_path).stat().st_size > 1000:
                    print(f"[WORKER] Slideshow created: {video_path}")
                    notify_telegram(f"🎬 Video ready: [{job_id}] {story['title'][:80]}")
                    ok = compose_publish(job_id, audio_path, image_paths[0], story["title"], mc_video)
                else:
                    print(f"[WORKER] Slideshow compose failed, output 0 bytes")
            except Exception as ve:
                print(f"[WORKER] Slideshow compose error: {ve}")

            # Track job
            redis_client.set(f"job:{job_id}", json.dumps({
                "job_id": job_id, "status": "completed", "title": story["title"],
                "completed_at": datetime.utcnow().isoformat(),
                "outputs": {
                    "audio_path": audio_path,
                    "image_count": len(image_paths),
                    "image_path": image_paths[0] if image_paths else ""
                }
            }))
            redis_client.lpush("jobs:recent", job_id)
            redis_client.ltrim("jobs:recent", 0, 50)

            # Wait before next job
            print("[WORKER] Waiting 5 minutes before next job...")
            time.sleep(300)

        except Exception as e:
            print(f"[WORKER] Error: {e}")
            notify_telegram(f"❌ Pipeline error: {str(e)[:200]}")
            time.sleep(30)

if __name__ == "__main__":
    main()
