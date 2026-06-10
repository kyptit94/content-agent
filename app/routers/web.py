from datetime import datetime
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter
from fastapi import File
from fastapi import Header
from fastapi import HTTPException
from fastapi import UploadFile
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from pydantic import Field

from app.config import settings
from app.schemas import JobPayload
from app.services.llm_service import LLMService
from app.services.queue_service import QueueService

router = APIRouter(prefix="/web", tags=["web"])
queue = QueueService(redis_url=settings.redis_url, queue_name=settings.job_queue_name)
llm = LLMService()


class SuggestTopicRequest(BaseModel):
    mode: str = "sales"
    language: str = "vi"


class CreateWebJobRequest(BaseModel):
    mode: str = "sales"
    topic: str = Field(min_length=3, max_length=500)
    language: str = "vi"
    tone: str = "friendly"
    use_gemini_refine: bool = False
    create_audio: bool = False
    create_video: bool = True
    video_source_type: str = "self"
    video_keyword: str | None = None
    voice_sample_filename: str | None = None
    user_video_path: str | None = None
    notify_telegram: bool = True
    telegram_chat_id: str | None = None


def _check_token(token: str | None) -> None:
    if not token or token != settings.web_admin_token:
        raise HTTPException(status_code=401, detail="Unauthorized")


def _token_from_header(x_admin_token: str | None = Header(default=None)) -> str | None:
    return x_admin_token


@router.get("", response_class=HTMLResponse)
def web_home() -> str:
    return """
<!doctype html>
<html>
  <head>
    <meta charset=\"utf-8\" />
    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
    <title>AI Agent Console</title>
    <style>
      body { font-family: 'Segoe UI', sans-serif; max-width: 980px; margin: 24px auto; padding: 0 16px; }
      .card { border: 1px solid #ddd; border-radius: 12px; padding: 14px; margin-bottom: 14px; }
      input, select, button, textarea { padding: 8px; margin: 4px 0; width: 100%; box-sizing: border-box; }
      button { cursor: pointer; }
      .row { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
      pre { background: #111; color: #eee; padding: 12px; border-radius: 10px; overflow: auto; }
    </style>
  </head>
  <body>
    <h2>AI Agent Web Console</h2>
    <div class=\"card\">
      <label>Admin token</label>
      <input id=\"token\" placeholder=\"WEB_ADMIN_TOKEN\" />
      <button onclick=\"saveToken()\">Save token</button>
    </div>

    <div class=\"card\">
      <h3>1) Upload Video Goc</h3>
      <input id=\"videoFile\" type=\"file\" accept=\"video/*\" />
      <button onclick=\"uploadVideo()\">Upload</button>
      <div id=\"uploadResult\"></div>
    </div>

    <div class=\"card\">
      <h3>2) Goi Y Chu De (15p ban tu quyet dinh)</h3>
      <div class=\"row\">
        <select id=\"mode\"><option value=\"sales\">sales</option><option value=\"story\">story</option></select>
        <input id=\"language\" value=\"vi\" />
      </div>
      <button onclick=\"suggestTopic()\">Suggest Topic</button>
      <textarea id=\"topic\" rows=\"3\" placeholder=\"topic\"></textarea>
    </div>

    <div class=\"card\">
      <h3>3) Chay Job</h3>
      <label>Nguon video</label>
      <select id=\"videoSourceType\">
        <option value=\"self\">2) Tu minh quay</option>
        <option value=\"internet\">1) Tim tren internet</option>
      </select>
      <label>Video source path (chon tu danh sach duoi)</label>
      <input id=\"videoPath\" placeholder=\"/app/data/uploads/...\" />
      <label>Video keyword (chi dung khi chon internet)</label>
      <input id=\"videoKeyword\" placeholder=\"book reading, library, study...\" />
      <label>Tone</label>
      <input id=\"tone\" value=\"friendly\" />
      <div class=\"row\">
        <label><input id=\"createAudio\" type=\"checkbox\" /> Create audio</label>
        <label><input id=\"useGemini\" type=\"checkbox\" /> Gemini refine</label>
      </div>
      <div class=\"row\">
        <label><input id=\"notifyTelegram\" type=\"checkbox\" checked /> Notify Telegram done/error</label>
        <input id=\"telegramChatId\" placeholder=\"Telegram chat id (optional)\" />
      </div>
      <button onclick=\"createJob()\">Run</button>
      <div id=\"jobResult\"></div>
    </div>

    <div class=\"card\">
      <h3>4) Video Da Upload</h3>
      <button onclick=\"loadVideos()\">Refresh</button>
      <pre id=\"videos\"></pre>
    </div>

    <div class=\"card\">
      <h3>5) Job Gan Day</h3>
      <button onclick=\"loadJobs()\">Refresh</button>
      <pre id=\"jobs\"></pre>
    </div>

    <script>
      const tokenInput = document.getElementById('token');
      tokenInput.value = localStorage.getItem('adminToken') || '';

      function getToken(){ return localStorage.getItem('adminToken') || ''; }
      function saveToken(){ localStorage.setItem('adminToken', tokenInput.value.trim()); alert('saved'); }

      async function api(url, options={}) {
        const headers = options.headers || {};
        headers['x-admin-token'] = getToken();
        options.headers = headers;
        const res = await fetch(url, options);
        if (!res.ok) throw new Error(await res.text());
        return await res.json();
      }

      async function uploadVideo(){
        try {
          const fileInput = document.getElementById('videoFile');
          if (!fileInput.files.length) return;
          const fd = new FormData();
          fd.append('file', fileInput.files[0]);
          const out = await fetch('/web/upload', { method: 'POST', headers: {'x-admin-token': getToken()}, body: fd });
          const data = await out.json();
          if (!out.ok) throw new Error(JSON.stringify(data));
          document.getElementById('uploadResult').innerText = data.saved_path;
          document.getElementById('videoPath').value = data.saved_path;
          await loadVideos();
        } catch (e) { alert(e.message); }
      }

      async function suggestTopic(){
        try {
          const body = {
            mode: document.getElementById('mode').value,
            language: document.getElementById('language').value
          };
          const data = await api('/web/suggest-topic', { method: 'POST', headers: {'content-type':'application/json'}, body: JSON.stringify(body) });
          document.getElementById('topic').value = data.topic;
        } catch (e) { alert(e.message); }
      }

      async function createJob(){
        try {
          const body = {
            mode: document.getElementById('mode').value,
            topic: document.getElementById('topic').value,
            language: document.getElementById('language').value,
            tone: document.getElementById('tone').value,
            use_gemini_refine: document.getElementById('useGemini').checked,
            create_audio: document.getElementById('createAudio').checked,
            create_video: true,
            video_source_type: document.getElementById('videoSourceType').value,
            user_video_path: document.getElementById('videoPath').value || null,
            video_keyword: document.getElementById('videoKeyword').value || null,
            notify_telegram: document.getElementById('notifyTelegram').checked,
            telegram_chat_id: document.getElementById('telegramChatId').value || null
          };
          const data = await api('/web/jobs', { method: 'POST', headers: {'content-type':'application/json'}, body: JSON.stringify(body) });
          document.getElementById('jobResult').innerText = data.job_id;
          await loadJobs();
        } catch (e) { alert(e.message); }
      }

      async function loadVideos(){
        try {
          const data = await api('/web/videos');
          document.getElementById('videos').innerText = JSON.stringify(data, null, 2);
        } catch (e) { alert(e.message); }
      }

      async function loadJobs(){
        try {
          const data = await api('/web/jobs?limit=20');
          document.getElementById('jobs').innerText = JSON.stringify(data, null, 2);
        } catch (e) { alert(e.message); }
      }

      loadVideos();
      loadJobs();
    </script>
  </body>
</html>
"""


@router.post("/upload")
def upload_video(file: UploadFile = File(...), x_admin_token: str | None = Header(default=None)) -> dict:
    _check_token(x_admin_token)

    suffix = Path(file.filename or "upload.mp4").suffix.lower()
    if suffix not in {".mp4", ".mov", ".mkv", ".webm"}:
        raise HTTPException(status_code=400, detail="Unsupported video format")

    upload_root = Path(settings.ingest_dir)
    upload_root.mkdir(parents=True, exist_ok=True)
    target = upload_root / f"{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{Path(file.filename or 'video.mp4').name}"

    with target.open("wb") as output:
        output.write(file.file.read())

    return {"saved_path": str(target)}


@router.get("/videos")
def list_videos(x_admin_token: str | None = Header(default=None)) -> dict:
    _check_token(x_admin_token)

    upload_root = Path(settings.ingest_dir)
    upload_root.mkdir(parents=True, exist_ok=True)
    items = []
    for path in sorted(upload_root.glob("*"), key=lambda p: p.stat().st_mtime, reverse=True):
        if not path.is_file():
            continue
        items.append(
            {
                "path": str(path),
                "size_mb": round(path.stat().st_size / 1024 / 1024, 2),
                "modified_at": datetime.utcfromtimestamp(path.stat().st_mtime).isoformat(),
            }
        )
    return {"videos": items}


@router.post("/suggest-topic")
def suggest_topic(body: SuggestTopicRequest, x_admin_token: str | None = Header(default=None)) -> dict:
    _check_token(x_admin_token)

    mode = body.mode if body.mode in {"sales", "story"} else "sales"
    topic = llm.suggest_topic(mode=mode, language=body.language)
    return {"topic": topic, "mode": mode}


@router.post("/jobs")
def create_web_job(body: CreateWebJobRequest, x_admin_token: str | None = Header(default=None)) -> dict:
    _check_token(x_admin_token)

    mode = body.mode if body.mode in {"sales", "story"} else "sales"
    job_id = str(uuid4())
    payload = JobPayload(
        job_id=job_id,
        created_at=datetime.utcnow().isoformat(),
        mode=mode,
        topic=body.topic,
        language=body.language,
        tone=body.tone,
        use_gemini_refine=body.use_gemini_refine,
        create_audio=body.create_audio,
        create_video=body.create_video,
        video_source_type=("internet" if body.video_source_type == "internet" else "self"),
        video_keyword=body.video_keyword,
        user_video_path=body.user_video_path,
        voice_sample_filename=body.voice_sample_filename,
        notify_telegram=body.notify_telegram,
        telegram_chat_id=body.telegram_chat_id,
    )

    queue.enqueue(payload.model_dump())
    queue.set_job_status(
        job_id=job_id,
        payload={
            "job_id": job_id,
            "status": "queued",
            "topic": body.topic,
            "mode": mode,
            "queued_at": datetime.utcnow().isoformat(),
        },
    )
    return {"job_id": job_id, "status": "queued"}


@router.get("/jobs")
def list_jobs(limit: int = 20, x_admin_token: str | None = Header(default=None)) -> dict:
    _check_token(x_admin_token)
    return {"items": queue.list_recent_jobs(limit=limit)}


@router.get("/jobs/{job_id}")
def get_job(job_id: str, x_admin_token: str | None = Header(default=None)) -> dict:
    _check_token(x_admin_token)
    item = queue.get_job_status(job_id)
    if not item:
        raise HTTPException(status_code=404, detail="job not found")
    return item
