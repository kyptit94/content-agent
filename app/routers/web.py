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
      :root {
        --bg: #f6f7fb;
        --card: #ffffff;
        --text: #131722;
        --muted: #5f6b84;
        --line: #dde3ef;
        --accent: #0f766e;
        --accent-2: #0b5f58;
        --chip: #e8f7f5;
      }

      * { box-sizing: border-box; }
      body {
        margin: 0;
        color: var(--text);
        background:
          radial-gradient(circle at 5% 0%, #dff8f4 0, transparent 38%),
          radial-gradient(circle at 95% 20%, #ebf6ff 0, transparent 32%),
          var(--bg);
        font-family: "Avenir Next", "Nunito Sans", "Segoe UI", sans-serif;
      }

      .wrap {
        max-width: 1120px;
        margin: 24px auto 40px;
        padding: 0 16px;
      }

      .hero {
        background: linear-gradient(120deg, #0f766e, #1f9a8d);
        color: #fff;
        border-radius: 20px;
        padding: 24px;
        box-shadow: 0 20px 35px -26px rgba(15, 118, 110, 0.9);
      }

      .hero h1 { margin: 0; font-size: 28px; }
      .hero p { margin: 8px 0 0; opacity: 0.92; }

      .step-flow {
        margin-top: 16px;
        display: flex;
        flex-wrap: wrap;
        gap: 10px;
      }

      .step-chip {
        display: inline-flex;
        align-items: center;
        gap: 8px;
        font-size: 13px;
        background: rgba(255, 255, 255, 0.18);
        border: 1px solid rgba(255, 255, 255, 0.28);
        border-radius: 999px;
        padding: 8px 12px;
      }

      .step-chip.active {
        background: #ffffff;
        color: #0d5b54;
        border-color: #ffffff;
      }

      .step-chip.done {
        background: #d7f5ef;
        color: #0b4b44;
        border-color: #d7f5ef;
      }

      .agent-box {
        margin-top: 16px;
        background: rgba(255, 255, 255, 0.14);
        border: 1px solid rgba(255, 255, 255, 0.32);
        border-radius: 14px;
        padding: 12px;
      }

      .agent-head {
        font-size: 13px;
        opacity: 0.9;
      }

      .agent-message {
        margin-top: 6px;
        font-size: 15px;
        font-weight: 700;
      }

      .progress-track {
        margin-top: 10px;
        width: 100%;
        height: 8px;
        border-radius: 999px;
        background: rgba(255, 255, 255, 0.25);
        overflow: hidden;
      }

      .progress-fill {
        height: 100%;
        width: 0;
        background: linear-gradient(120deg, #dbfff7, #ffffff);
        transition: width 0.35s ease;
      }

      .grid {
        margin-top: 18px;
        display: grid;
        grid-template-columns: repeat(12, minmax(0, 1fr));
        gap: 14px;
      }

      .card {
        grid-column: span 12;
        background: var(--card);
        border: 1px solid var(--line);
        border-radius: 16px;
        padding: 16px;
        box-shadow: 0 10px 26px -24px rgba(11, 30, 65, 0.55);
      }

      .step-title {
        display: flex;
        align-items: center;
        gap: 10px;
        margin-bottom: 10px;
      }

      .badge {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        width: 30px;
        height: 30px;
        border-radius: 50%;
        background: var(--chip);
        color: var(--accent-2);
        font-weight: 700;
      }

      .card h3 { margin: 0; }
      .hint { color: var(--muted); font-size: 13px; margin: 4px 0 0; }

      .row {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 12px;
      }

      label {
        display: block;
        font-size: 13px;
        color: #1d2a44;
        margin-top: 10px;
      }

      input, select, button, textarea {
        width: 100%;
        padding: 10px 12px;
        border-radius: 10px;
        border: 1px solid #cfd8e7;
        font: inherit;
      }

      textarea { min-height: 92px; resize: vertical; }

      button {
        cursor: pointer;
        border: 0;
        color: #fff;
        background: linear-gradient(120deg, var(--accent), #149688);
        font-weight: 700;
      }

      button.secondary {
        background: #eff3fa;
        color: #203050;
        border: 1px solid #d5dfef;
      }

      .check-grid {
        margin-top: 10px;
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 10px;
      }

      .check-item {
        display: flex;
        align-items: center;
        gap: 8px;
        padding: 10px;
        border: 1px solid var(--line);
        border-radius: 10px;
      }

      .check-item input {
        width: auto;
        margin: 0;
      }

      .status {
        margin-top: 10px;
        font-size: 13px;
        color: #294268;
        background: #f2f6ff;
        border: 1px solid #d8e2f5;
        border-radius: 10px;
        padding: 8px 10px;
        word-break: break-word;
      }

      pre {
        margin: 0;
        background: #0f172a;
        color: #d3ddf9;
        padding: 12px;
        border-radius: 12px;
        overflow: auto;
        min-height: 120px;
      }

      .span-6 { grid-column: span 6; }

      .is-disabled {
        opacity: 0.6;
        pointer-events: none;
      }

      @media (max-width: 860px) {
        .row, .check-grid { grid-template-columns: 1fr; }
        .span-6 { grid-column: span 12; }
      }
    </style>
  </head>
  <body>
    <div class=\"wrap\">
      <div class=\"hero\">
        <h1>AI Agent Console</h1>
        <p>Giao dien chay job theo tung buoc, de theo doi va thao tac nhanh.</p>
        <div class=\"step-flow\">
          <span id=\"chip1\" class=\"step-chip\">1. Token</span>
          <span id=\"chip2\" class=\"step-chip\">2. Upload Video</span>
          <span id=\"chip3\" class=\"step-chip\">3. Goi Y Topic</span>
          <span id=\"chip4\" class=\"step-chip\">4. Cau Hinh Job</span>
          <span id=\"chip5\" class=\"step-chip\">5. Theo Doi Ket Qua</span>
        </div>

        <div class=\"agent-box\">
          <div class=\"agent-head\">AI Agent Guide</div>
          <div id=\"agentMessage\" class=\"agent-message\">Bat dau tu Buoc 1: nhap token roi bam Luu token.</div>
          <div class=\"progress-track\"><div id=\"progressFill\" class=\"progress-fill\"></div></div>
        </div>
      </div>

      <div class=\"grid\">
        <div id="step2Card" class="card span-6 is-disabled">
          <div class=\"step-title\">
            <span class=\"badge\">1</span>
            <h3>Xac thuc Admin Token</h3>
          </div>
          <p class=\"hint\">Nhap WEB_ADMIN_TOKEN de su dung API web.</p>
          <label>Admin token</label>
          <input id=\"token\" placeholder=\"WEB_ADMIN_TOKEN\" />
          <button onclick=\"saveToken()\">Luu token</button>
        </div>

        <div class=\"card span-6\">
        <div id="step3Card" class="card span-6 is-disabled">
            <span class=\"badge\">2</span>
            <h3>Upload Video Goc</h3>
          </div>
          <p class=\"hint\">Neu chon nguon self thi can upload truoc.</p>
          <label>File video</label>
          <input id=\"videoFile\" type=\"file\" accept=\"video/*\" />
          <button onclick=\"uploadVideo()\">Upload</button>
          <div id=\"uploadResult\" class=\"status\">Chua co file nao duoc upload.</div>
        </div>

        <div class=\"card span-6\">
          <div class=\"step-title\">
            <span class=\"badge\">3</span>
            <h3>Goi Y Chu De</h3>
          </div>
          <p class=\"hint\">Lay topic nhanh de dua vao buoc tao job.</p>
          <div class=\"row\">
            <div>
              <label>Mode</label>
              <select id=\"mode\"><option value=\"sales\">sales</option><option value=\"story\">story</option></select>
        <div id="step4Card" class="card is-disabled">
            <div>
              <label>Language</label>
              <input id=\"language\" value=\"vi\" />
            </div>
          </div>
          <button onclick=\"suggestTopic()\">Suggest Topic</button>
          <label>Topic</label>
          <textarea id=\"topic\" rows=\"3\" placeholder=\"Nhap topic o day\"></textarea>
        </div>

        <div class=\"card\">
          <div class=\"step-title\">
            <span class=\"badge\">4</span>
            <h3>Cau Hinh Va Chay Job</h3>
          </div>
          <p class=\"hint\">Thiet lap nguon video, tone, thong bao roi bam Run.</p>

          <div class=\"row\">
            <div>
              <label>Nguon video</label>
              <select id=\"videoSourceType\">
                <option value=\"self\">self - dung video da upload</option>
                <option value=\"internet\">internet - tim clip stock</option>
              </select>
            </div>
            <div>
              <label>Tone</label>
              <input id=\"tone\" value=\"friendly\" />
            </div>
          </div>

          <div class=\"row\">
            <div>
              <label>Video source path (self)</label>
              <input id=\"videoPath\" placeholder=\"/app/data/uploads/...\" />
            </div>
            <div>
              <label>Video keyword (internet)</label>
              <input id=\"videoKeyword\" placeholder=\"book reading, study desk...\" />
            </div>
          </div>

        <div id="step5aCard" class="card span-6 is-disabled">
            <label class=\"check-item\"><input id=\"createAudio\" type=\"checkbox\" /> Create audio</label>
            <label class=\"check-item\"><input id=\"useGemini\" type=\"checkbox\" /> Gemini refine</label>
            <label class=\"check-item\"><input id=\"notifyTelegram\" type=\"checkbox\" checked /> Notify Telegram</label>
            <label class=\"check-item\">Telegram Chat ID<input id=\"telegramChatId\" placeholder=\"optional\" /></label>
          </div>

          <button onclick=\"createJob()\">Run Job</button>
          <div id=\"jobResult\" class=\"status\">Chua tao job.</div>
        </div>
        <div id="step5bCard" class="card span-6 is-disabled">
        <div class=\"card span-6\">
          <div class=\"step-title\">
            <span class=\"badge\">5</span>
            <h3>Video Da Upload</h3>
          </div>
          <p class=\"hint\">Kiem tra duong dan video de chon cho nguon self.</p>
          <button class=\"secondary\" onclick=\"loadVideos()\">Refresh Videos</button>
          <pre id=\"videos\"></pre>
        </div>

        <div class=\"card span-6\">
          <div class=\"step-title\">
            <span class=\"badge\">5</span>
            <h3>Job Gan Day</h3>
          </div>
          <p class=\"hint\">Theo doi trang thai queued, running, completed, failed.</p>
          <button class=\"secondary\" onclick=\"loadJobs()\">Refresh Jobs</button>
          <pre id=\"jobs\"></pre>
        </div>
      </div>
    </div>

    <script>
      const tokenInput = document.getElementById('token');
      tokenInput.value = localStorage.getItem('adminToken') || '';
      const progressFill = document.getElementById('progressFill');
      const agentMessage = document.getElementById('agentMessage');

      const stepState = {
        1: Boolean(tokenInput.value.trim()),
        2: false,
        3: false,
        4: false,
        5: false,
      };

      function setStepActive(stepNumber) {
        for (let i = 1; i <= 5; i++) {
          const chip = document.getElementById('chip' + i);
          chip.classList.remove('active');
          chip.classList.remove('done');
          if (stepState[i]) chip.classList.add('done');
        }
        const activeChip = document.getElementById('chip' + stepNumber);
        if (activeChip) activeChip.classList.add('active');
      }

      function setCardEnabled(cardId, enabled) {
        const card = document.getElementById(cardId);
        if (!card) return;
        card.classList.toggle('is-disabled', !enabled);
      }

      function updateGuide() {
        const completedCount = Object.values(stepState).filter(Boolean).length;
        progressFill.style.width = ((completedCount / 5) * 100) + '%';

        if (!stepState[1]) {
          agentMessage.innerText = 'Buoc 1: luu token de Agent co quyen goi API.';
          setStepActive(1);
        } else if (!stepState[2]) {
          agentMessage.innerText = 'Buoc 2: upload video goc (neu dung nguon self).';
          setStepActive(2);
        } else if (!stepState[3]) {
          agentMessage.innerText = 'Buoc 3: bam Suggest Topic hoac nhap topic thu cong.';
          setStepActive(3);
        } else if (!stepState[4]) {
          agentMessage.innerText = 'Buoc 4: cau hinh va bam Run Job.';
          setStepActive(4);
        } else {
          agentMessage.innerText = 'Buoc 5: theo doi job, refresh de xem trang thai moi nhat.';
          setStepActive(5);
        }

        setCardEnabled('step2Card', stepState[1]);
        setCardEnabled('step3Card', stepState[1]);
        setCardEnabled('step4Card', stepState[1] && stepState[3]);
        setCardEnabled('step5aCard', stepState[1]);
        setCardEnabled('step5bCard', stepState[1]);
      }

      function getToken(){ return localStorage.getItem('adminToken') || ''; }
      function saveToken(){
        const value = tokenInput.value.trim();
        localStorage.setItem('adminToken', value);
        stepState[1] = Boolean(value);
        updateGuide();
        alert('Token da duoc luu');
      }

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
          stepState[2] = true;
          document.getElementById('uploadResult').innerText = 'Upload thanh cong: ' + data.saved_path;
          document.getElementById('videoPath').value = data.saved_path;
          updateGuide();
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
          stepState[3] = true;
          updateGuide();
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
          stepState[4] = true;
          stepState[5] = true;
          document.getElementById('jobResult').innerText = 'Job da tao: ' + data.job_id;
          updateGuide();
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

      if (stepState[1]) {
        stepState[5] = true;
      }
      updateGuide();
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
