import json
from pathlib import Path
from datetime import datetime
from uuid import uuid4

from fastapi import APIRouter
from fastapi import File
from fastapi import Header
from fastapi import HTTPException
from fastapi import UploadFile
from fastapi.responses import HTMLResponse
from fastapi.responses import FileResponse
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from pydantic import Field

from redis import Redis

from app.config import settings
from app.schemas import ContentMode
from app.schemas import ContentOption
from app.schemas import GenerateOptionsRequest
from app.schemas import GenerateOptionsResponse
from app.schemas import JobPayload
from app.services.chat_service import ChatService
from app.services.llm_service import LLMService
from app.services.queue_service import QueueService

router = APIRouter(prefix="/web", tags=["web"])
redis_client = Redis.from_url(settings.redis_url, decode_responses=True)
queue = QueueService(redis_url=settings.redis_url, queue_name=settings.job_queue_name)
llm = LLMService()
chat = ChatService(redis=redis_client, llm=llm, queue=queue)


class ChatMessageRequest(BaseModel):
    session_id: str
    message: str


class CreateWebJobRequest(BaseModel):
    mode: str = "horror"
    title: str = Field(min_length=3, max_length=500)
    content: str = Field(min_length=50, max_length=10000)
    language: str = "en"
    tone: str = "friendly"
    use_gemini_refine: bool = False
    create_audio: bool = True
    create_video: bool = True
    video_source_type: str = "self"
    video_keyword: str | None = None
    voice_sample_filename: str | None = None
    edge_tts_voice: str | None = None
    kokoro_voice: str | None = "af_heart"
    user_video_path: str | None = None
    notify_telegram: bool = True
    telegram_chat_id: str | None = None


def _check_token(token: str | None) -> None:
    if not token or token != settings.web_admin_token:
        raise HTTPException(status_code=401, detail="Unauthorized")


@router.get("", response_class=HTMLResponse)
def web_home() -> str:
    return """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Creator AI — Chat</title>
    <style>
      :root {
        --bg: #0b0d14;
        --card: #141725;
        --text: #e4e8f1;
        --muted: #6b7280;
        --line: #1f2240;
        --accent: #7c3aed;
        --accent-glow: #a78bfa;
        --user-bubble: #1e1b4b;
        --ai-bubble: #141725;
        --green: #10b981;
        --red: #ef4444;
        --warning: #f59e0b;
      }
      * { box-sizing: border-box; margin: 0; padding: 0; }
      body {
        font-family: "Inter", "Segoe UI", system-ui, sans-serif;
        background: var(--bg);
        color: var(--text);
        height: 100vh;
        display: flex;
        flex-direction: column;
        overflow: hidden;
      }
      /* -- Header -- */
      header {
        background: var(--card);
        border-bottom: 1px solid var(--line);
        padding: 12px 16px;
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 12px;
        flex-shrink: 0;
      }
      header .title {
        font-weight: 800;
        font-size: 16px;
        background: linear-gradient(135deg, var(--accent-glow), #818cf8);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
      }
      header .token-box {
        display: flex;
        gap: 6px;
        align-items: center;
      }
      header input {
        width: 180px;
        padding: 6px 10px;
        border-radius: 8px;
        border: 1px solid var(--line);
        background: var(--bg);
        color: var(--text);
        font-size: 12px;
      }
      header button {
        padding: 6px 12px;
        border-radius: 8px;
        border: 0;
        background: var(--accent);
        color: #fff;
        font-weight: 600;
        font-size: 12px;
        cursor: pointer;
      }
      header button.secondary {
        background: var(--line);
      }
      /* -- Chat area -- */
      .chat-wrap {
        flex: 1;
        overflow-y: auto;
        padding: 16px;
        display: flex;
        flex-direction: column;
        gap: 12px;
        scroll-behavior: smooth;
      }
      .bubble {
        max-width: 80%;
        padding: 10px 14px;
        border-radius: 14px;
        font-size: 14px;
        line-height: 1.55;
        word-break: break-word;
        animation: fadeIn 0.25s ease;
      }
      @keyframes fadeIn { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: translateY(0); } }
      .bubble.user {
        align-self: flex-end;
        background: var(--user-bubble);
        border-bottom-right-radius: 4px;
      }
      .bubble.ai {
        align-self: flex-start;
        background: var(--ai-bubble);
        border: 1px solid var(--line);
        border-bottom-left-radius: 4px;
      }
      .bubble.ai .action-tag {
        display: inline-block;
        margin-top: 6px;
        padding: 3px 8px;
        border-radius: 6px;
        font-size: 11px;
        font-weight: 600;
        background: #7c3aed22;
        color: var(--accent-glow);
      }
      .bubble .time {
        font-size: 10px;
        color: var(--muted);
        margin-top: 4px;
      }
      /* -- Options cards inside chat -- */
      .options-inline {
        margin-top: 8px;
        display: grid;
        gap: 6px;
      }
      .opt-chip {
        padding: 8px 12px;
        border-radius: 10px;
        border: 1px solid var(--line);
        background: var(--bg);
        cursor: pointer;
        font-size: 12px;
        transition: all 0.15s;
      }
      .opt-chip:hover { border-color: var(--accent); }
      .opt-chip .opt-t { font-weight: 700; margin-bottom: 2px; }
      .opt-chip .opt-c { color: var(--muted); font-size: 11px; max-height: 40px; overflow: hidden; }
      /* -- Input bar -- */
      .input-bar {
        background: var(--card);
        border-top: 1px solid var(--line);
        padding: 10px 14px;
        display: flex;
        gap: 8px;
        flex-shrink: 0;
      }
      .input-bar textarea {
        flex: 1;
        padding: 10px 12px;
        border-radius: 12px;
        border: 1px solid var(--line);
        background: var(--bg);
        color: var(--text);
        font: inherit;
        font-size: 14px;
        resize: none;
        min-height: 44px;
        max-height: 120px;
      }
      .input-bar button {
        padding: 10px 18px;
        border-radius: 12px;
        border: 0;
        background: var(--accent);
        color: #fff;
        font-weight: 700;
        cursor: pointer;
        white-space: nowrap;
        transition: opacity 0.15s;
      }
      .input-bar button:disabled { opacity: 0.4; cursor: not-allowed; }
      /* -- Typing indicator -- */
      .typing {
        align-self: flex-start;
        padding: 10px 14px;
        color: var(--muted);
        font-size: 14px;
        font-style: italic;
      }
      .typing::after {
        content: '';
        animation: dots 1.4s infinite;
      }
      @keyframes dots {
        0%, 20% { content: '.'; }
        40% { content: '..'; }
        60%, 100% { content: '...'; }
      }
      /* -- Jobs modal -- */
      .modal-backdrop {
        position: fixed; inset: 0;
        background: rgba(5,7,16,0.85);
        display: none; align-items: center; justify-content: center;
        padding: 20px; z-index: 50;
      }
      .modal-backdrop.open { display: flex; }
      .modal {
        width: min(700px, 100%);
        max-height: 80vh; overflow: auto;
        background: var(--card); border-radius: 16px;
        border: 1px solid var(--line); padding: 20px;
      }
      .modal-head {
        display: flex; align-items: center; justify-content: space-between;
        gap: 12px; margin-bottom: 14px;
      }
      .modal-head h3 { color: var(--accent-glow); }
      .job-card {
        background: var(--bg); border: 1px solid var(--line);
        border-radius: 10px; padding: 10px; margin-bottom: 8px;
        font-size: 12px;
      }
      .job-card .j-title { font-weight: 700; }
      .job-card .j-meta { color: var(--muted); margin-top: 2px; }
      .badge {
        display: inline-block; padding: 2px 8px; border-radius: 999px;
        font-size: 10px; font-weight: 700; margin-left: 6px;
      }
      .badge.completed { background: #10b98122; color: var(--green); }
      .badge.running { background: #f59e0b22; color: var(--warning); }
      .badge.failed { background: #ef444422; color: var(--red); }
      .badge.queued { background: #6366f122; color: #818cf8; }
      button { cursor: pointer; }
    </style>
  </head>
  <body>
    <header>
      <span class="title">🤖 Creator AI Chat</span>
      <div class="token-box">
        <input id="tokenInput" placeholder="Admin token" />
        <button onclick="saveToken()">Auth</button>
        <button class="secondary" onclick="openJobs()">📋 Jobs</button>
        <button class="secondary" onclick="exportChat()">📥 Export</button>
      </div>
    </header>

    <div id="chatWrap" class="chat-wrap">
      <div class="bubble ai">
        👋 Hi! I'm <strong>Creator AI</strong> — your writing & video partner.<br/><br/>
        Just tell me what to write. Teach me your style — I'll learn as we go. When you're happy, say <em>"make video"</em> and I'll produce it.
      </div>
    </div>

    <div class="input-bar">
      <input type="file" id="imageUpload" accept="image/*" style="display:none" onchange="uploadImage(event)" />
      <button id="imageBtn" onclick="document.getElementById('imageUpload').click()" style="width:auto;padding:10px 12px;margin-top:0" title="Upload background image">🖼️</button>
      <textarea id="msgInput" placeholder="Type your message..." rows="1" onkeydown="if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();sendMessage()}"></textarea>
      <button id="sendBtn" onclick="sendMessage()">Send</button>
      <button id="audioBtn" onclick="submitQuickJob(false)" style="width:auto;background:#ef444422;color:#fca5a5;border:1px solid #ef444455" title="Generate audio from last AI message">🎙️ Audio</button>
      <button id="videoBtn" onclick="submitQuickJob(true)" style="width:auto" title="Generate video from last AI message">🎬 Video</button>
    </div>

    <!-- Jobs Modal -->
    <div id="jobsBackdrop" class="modal-backdrop" onclick="if(event.target===this)closeJobs()">
      <div class="modal">
        <div class="modal-head">
          <h3>Recent Jobs</h3>
          <button class="secondary" onclick="closeJobs()">Close</button>
        </div>
        <button class="secondary" onclick="loadJobs()" style="margin-bottom:10px">Refresh</button>
        <div id="jobsList"></div>
      </div>
    </div>

    <script>
      let sessionId = localStorage.getItem('chatSession') || '';
      let isSending = false;
      const tokenInput = document.getElementById('tokenInput');
      tokenInput.value = localStorage.getItem('adminToken') || '';

      function getToken() { return localStorage.getItem('adminToken') || ''; }
      function escapeHtml(v) { return String(v).replaceAll('&','&').replaceAll('<','<').replaceAll('>','>').replaceAll('"','"'); }

      async function api(url, opts = {}) {
        opts.headers = opts.headers || {};
        opts.headers['x-admin-token'] = getToken();
        const r = await fetch(url, opts);
        if (!r.ok) throw new Error(await r.text());
        return r.json();
      }

      async function ensureSession() {
        if (sessionId) return;
        const data = await api('/web/chat/new', { method: 'POST' });
        sessionId = data.session_id;
        localStorage.setItem('chatSession', sessionId);
      }

      function saveToken() {
        localStorage.setItem('adminToken', tokenInput.value.trim());
        if (!sessionId) ensureSession();
      }

      function addBubble(role, text, extra = '') {
        const wrap = document.getElementById('chatWrap');
        const div = document.createElement('div');
        div.className = 'bubble ' + role;
        div.innerHTML = text + extra;
        wrap.appendChild(div);
        wrap.scrollTop = wrap.scrollHeight;
      }

      function addTyping() {
        const wrap = document.getElementById('chatWrap');
        const el = document.createElement('div');
        el.className = 'typing';
        el.id = 'typingIndicator';
        el.innerText = 'Creator AI is thinking';
        wrap.appendChild(el);
        wrap.scrollTop = wrap.scrollHeight;
      }
      function removeTyping() {
        const el = document.getElementById('typingIndicator');
        if (el) el.remove();
      }

      function renderActionResults(results) {
        const wrap = document.getElementById('chatWrap');
        for (const r of results) {
          if (!r) continue;
          if (r.type === 'options') {
            const opts = r.data || [];
            const html = opts.map((o, i) => `
              <div class="opt-chip" onclick="pickOption(${i})">
                <div class="opt-t">${i+1}. ${escapeHtml(o.title)}</div>
                <div class="opt-c">${escapeHtml(o.content.slice(0,100))}...</div>
              </div>
            `).join('');
            const div = document.createElement('div');
            div.className = 'bubble ai';
            div.innerHTML = '<strong>📝 Generated options — click one to pick:</strong><div class="options-inline">' + html + '</div>';
            wrap.appendChild(div);
          } else if (r.type === 'selected') {
            addBubble('ai', `✅ Selected: <strong>${escapeHtml(r.title)}</strong>`);
          } else if (r.type === 'job_submitted') {
            addBubble('ai', `🚀 Job submitted! <strong>ID: ${escapeHtml(r.job_id)}</strong><br/>Check status with "Show my jobs" or click the 📋 button.`);
          } else if (r.type === 'jobs') {
            renderJobsInline(r.data || []);
          } else if (r.type === 'error') {
            addBubble('ai', `⚠️ ${escapeHtml(r.message)}`);
          }
          wrap.scrollTop = wrap.scrollHeight;
        }
      }

      function renderJobsInline(jobs) {
        const wrap = document.getElementById('chatWrap');
        if (!jobs.length) {
          addBubble('ai', 'No jobs found yet.');
          return;
        }
        const statusLabels = {queued:'Queued', running:'Running', completed:'Completed', failed:'Failed'};
        const html = jobs.map(j => {
          const s = j.status || 'unknown';
          return `<div class="job-card">
            <span class="j-title">${escapeHtml(j.title||j.topic||'Untitled')}</span>
            <span class="badge ${s}">${statusLabels[s]||s}</span>
            <div class="j-meta">ID: ${escapeHtml(j.job_id||'')} · Mode: ${escapeHtml(j.mode||'')}</div>
            ${j.error ? '<div style="color:var(--red);font-size:11px;margin-top:2px">'+escapeHtml(j.error.slice(0,200))+'</div>' : ''}
          </div>`;
        }).join('');
        const div = document.createElement('div');
        div.className = 'bubble ai';
        div.innerHTML = '<strong>📋 Recent Jobs:</strong><div style="margin-top:6px">'+html+'</div>';
        wrap.appendChild(div);
        wrap.scrollTop = wrap.scrollHeight;
      }

      async function sendMessage() {
        if (isSending) return;
        const input = document.getElementById('msgInput');
        const msg = input.value.trim();
        if (!msg) return;
        if (!getToken()) { alert('Enter admin token first'); return; }
        await ensureSession();

        isSending = true;
        input.value = '';
        input.style.height = 'auto';
        document.getElementById('sendBtn').disabled = true;
        addBubble('user', escapeHtml(msg));
        addTyping();

        try {
          const data = await api('/web/chat', {
            method: 'POST',
            headers: {'content-type': 'application/json'},
            body: JSON.stringify({ session_id: sessionId, message: msg }),
          });
          removeTyping();
          addBubble('ai', escapeHtml(data.message || '(no response)'));
          if (data.action_results) renderActionResults(data.action_results);
        } catch (e) {
          removeTyping();
          addBubble('ai', '⚠️ Error: ' + escapeHtml(e.message));
        }
        document.getElementById('sendBtn').disabled = false;
        isSending = false;
      }

      window.pickOption = async function(idx) {
        addBubble('user', `Pick option ${idx+1}`);
        addTyping();
        try {
          await ensureSession();
          const data = await api('/web/chat', {
            method: 'POST',
            headers: {'content-type': 'application/json'},
            body: JSON.stringify({ session_id: sessionId, message: `select option ${idx}` }),
          });
          removeTyping();
          addBubble('ai', escapeHtml(data.message || '(no response)'));
          if (data.action_results) renderActionResults(data.action_results);
        } catch (e) {
          removeTyping();
          addBubble('ai', '⚠️ Error: ' + escapeHtml(e.message));
        }
      };

      // Jobs modal
      function openJobs() { document.getElementById('jobsBackdrop').classList.add('open'); loadJobs(); }
      function closeJobs() { document.getElementById('jobsBackdrop').classList.remove('open'); }
      async function loadJobs() {
        const container = document.getElementById('jobsList');
        try {
          const data = await api('/web/jobs?limit=20');
          const items = data.items || [];
          if (!items.length) { container.innerHTML = '<div style="color:var(--muted)">No jobs yet.</div>'; return; }
          const labels = {queued:'Queued',running:'Running',completed:'Completed',failed:'Failed'};
          container.innerHTML = items.map(j => {
            const s = j.status||'unknown';
            return `<div class="job-card">
              <span class="j-title">${escapeHtml(j.title||j.topic||'Untitled')}</span><span class="badge ${s}">${labels[s]||s}</span>
              <div class="j-meta">ID: ${escapeHtml(j.job_id||'')} · Mode: ${escapeHtml(j.mode||'')}</div>
              ${j.error ? '<div style="color:var(--red);font-size:11px;margin-top:2px">'+escapeHtml(j.error.slice(0,300))+'</div>' : ''}
              ${j.progress_percent ? '<div style="margin-top:4px"><div style="height:4px;background:var(--line);border-radius:2px"><div style="height:100%;width:'+j.progress_percent+'%;background:var(--accent);border-radius:2px"></div></div></div>' : ''}
            </div>`;
          }).join('');
        } catch (e) { container.innerHTML = '<div style="color:var(--red)">Error loading jobs.</div>'; }
      }

      async function exportChat() {
        if (!sessionId) return alert('No active session');
        const token = getToken();
        window.open('/web/chat/export?session_id=' + sessionId + '&token=' + encodeURIComponent(token), '_blank');
      }

      let uploadedImagePath = '';

      async function submitQuickJob(createVideo) {
        if (!getToken()) { alert('Enter admin token first'); return; }
        await ensureSession();
        const sesh = await api('/web/chat/session/' + sessionId);
        const msgs = sesh.messages || [];
        // Find last assistant message with substantial content
        let content = '';
        for (let i = msgs.length - 1; i >= 0; i--) {
          if (msgs[i].role === 'assistant' && msgs[i].content.length > 100) {
            content = msgs[i].content;
            break;
          }
        }
        if (!content) { alert('No content generated yet. Chat with AI first!'); return; }
        const title = content.split('.')[0].trim().slice(0, 120);
        addBubble('user', createVideo ? '🎬 Create video from last content' : '🎙️ Create audio from last content');
        addTyping();
        try {
          const data = await api('/web/quick-submit', {
            method: 'POST',
            headers: {'content-type': 'application/json'},
            body: JSON.stringify({ session_id: sessionId, create_video: createVideo }),
          });
          removeTyping();
          addBubble('ai', `🚀 Job submitted! <strong>ID: ${data.job_id}</strong><br/><a href="/web/jobs/${data.job_id}/audio?token=${encodeURIComponent(getToken())}" target="_blank">Download when ready</a>`);
        } catch (e) {
          removeTyping();
          addBubble('ai', '⚠️ Error: ' + escapeHtml(e.message));
        }
      }

      async function uploadImage(event) {
        const file = event.target.files[0];
        if (!file) return;
        if (!getToken()) { alert('Enter admin token first'); return; }
        await ensureSession();

        addBubble('user', `🖼️ Uploading: ${escapeHtml(file.name)}`);
        addTyping();

        const formData = new FormData();
        formData.append('file', file);
        formData.append('session_id', sessionId);

        try {
          const resp = await fetch('/web/image-upload', {
            method: 'POST',
            headers: { 'x-admin-token': getToken() },
            body: formData,
          });
          if (!resp.ok) throw new Error(await resp.text());
          const data = await resp.json();
          uploadedImagePath = data.path;
          removeTyping();
          addBubble('ai', `✅ Image uploaded! It will be used as background for your next video.<br/><em>Now you can submit your video.</em>`);
        } catch (e) {
          removeTyping();
          addBubble('ai', '⚠️ Upload failed: ' + escapeHtml(e.message));
        }
        event.target.value = '';
      }

      // Auto-resize textarea
      document.getElementById('msgInput').addEventListener('input', function() {
        this.style.height = 'auto';
        this.style.height = Math.min(this.scrollHeight, 120) + 'px';
      });

      // Init
      (async () => {
        if (getToken()) await ensureSession();
      })();
    </script>
  </body>
</html>
"""


# === Chat API endpoints ===

class QuickSubmitRequest(BaseModel):
    session_id: str
    create_video: bool = True


@router.get("/chat/session/{session_id}")
def get_chat_session(session_id: str, x_admin_token: str | None = Header(default=None)) -> dict:
    _check_token(x_admin_token)
    return chat.get_session(session_id)


@router.post("/quick-submit")
def quick_submit(body: QuickSubmitRequest, x_admin_token: str | None = Header(default=None)) -> dict:
    _check_token(x_admin_token)
    session = chat.get_session(body.session_id)
    messages = session.get("messages", [])
    content = ""
    for msg in reversed(messages):
        if msg["role"] == "assistant" and len(msg.get("content", "")) > 100:
            content = msg["content"]
            break
    if not content:
        raise HTTPException(status_code=400, detail="No content found. Chat with AI first!")
    title = content.split(".")[0].strip()[:120]
    job_id = str(uuid4())
    payload = JobPayload(
        job_id=job_id, created_at=datetime.utcnow().isoformat(),
        mode="horror", title=title, content=content, language="en", tone="friendly",
        use_gemini_refine=False, create_audio=True,
        create_video=body.create_video,
        video_source_type="internet",
        kokoro_voice="af_heart",
        notify_telegram=True,
        telegram_chat_id=settings.telegram_chat_id,
    )
    queue.enqueue(payload.model_dump())
    queue.set_job_status(job_id=job_id, payload={
        "job_id": job_id, "status": "queued", "title": title, "mode": "horror",
        "queued_at": datetime.utcnow().isoformat(), "payload": payload.model_dump(),
    })
    return {"job_id": job_id, "status": "queued"}


@router.post("/chat/new")
def chat_new_session(x_admin_token: str | None = Header(default=None)) -> dict:
    _check_token(x_admin_token)
    sid = chat.create_session()
    return {"session_id": sid}


@router.post("/chat")
def chat_message(body: ChatMessageRequest, x_admin_token: str | None = Header(default=None)) -> dict:
    _check_token(x_admin_token)
    return chat.process_message(body.session_id, body.message)


@router.get("/chat/export")
def chat_export(session_id: str, token: str | None = None, x_admin_token: str | None = Header(default=None)):
    actual_token = x_admin_token or token
    _check_token(actual_token)
    data = chat.export_chat(session_id)
    return PlainTextResponse(data, media_type="application/x-jsonlines", headers={
        "Content-Disposition": f"attachment; filename=chat_{session_id}.jsonl"
    })


# === Existing API endpoints (kept for backward compat) ===

@router.post("/generate-options", response_model=GenerateOptionsResponse)
def generate_options(body: GenerateOptionsRequest, x_admin_token: str | None = Header(default=None)) -> dict:
    _check_token(x_admin_token)
    mode = body.mode.value if hasattr(body.mode, 'value') else body.mode
    options_raw = llm.generate_options(mode=mode, language=body.language, tone=body.tone, count=body.count)
    options = [ContentOption(title=opt["title"], content=opt["content"]) for opt in options_raw]
    return {"options": options}


@router.post("/jobs")
def create_web_job(body: CreateWebJobRequest, x_admin_token: str | None = Header(default=None)) -> dict:
    _check_token(x_admin_token)
    valid_modes = {"horror", "wealth", "softskills", "mystery", "sales", "story"}
    mode = body.mode if body.mode in valid_modes else "horror"
    job_id = str(uuid4())
    payload = JobPayload(
        job_id=job_id, created_at=datetime.utcnow().isoformat(),
        mode=mode, title=body.title, content=body.content,
        language=body.language, tone=body.tone,
        use_gemini_refine=body.use_gemini_refine,
        create_audio=body.create_audio, create_video=body.create_video,
        video_source_type=("internet" if body.video_source_type == "internet" else "self"),
        video_keyword=body.video_keyword, user_video_path=body.user_video_path,
        voice_sample_filename=body.voice_sample_filename,
        edge_tts_voice=body.edge_tts_voice, kokoro_voice=body.kokoro_voice,
        notify_telegram=body.notify_telegram, telegram_chat_id=body.telegram_chat_id,
    )
    queue.enqueue(payload.model_dump())
    queue.set_job_status(job_id=job_id, payload={
        "job_id": job_id, "status": "queued", "title": body.title, "mode": mode,
        "queued_at": datetime.utcnow().isoformat(), "payload": payload.model_dump(),
    })
    return {"job_id": job_id, "status": "queued"}


@router.get("/jobs")
def list_jobs(limit: int = 20, x_admin_token: str | None = Header(default=None)) -> dict:
    _check_token(x_admin_token)
    return {"items": queue.list_recent_jobs(limit=limit)}


@router.get("/voice-samples")
def list_voice_samples(x_admin_token: str | None = Header(default=None)) -> dict:
    _check_token(x_admin_token)
    voices_dir = Path("/app/data/voices")
    if not voices_dir.exists():
        return {"items": []}
    allowed_ext = {".wav", ".mp3", ".m4a", ".ogg", ".flac"}
    items = sorted(p.name for p in voices_dir.iterdir() if p.is_file() and p.suffix.lower() in allowed_ext)
    return {"items": items}


@router.post("/image-upload")
def upload_image(
    file: UploadFile = File(...),
    session_id: str = Header(default=""),
    x_admin_token: str | None = Header(default=None),
) -> dict:
    _check_token(x_admin_token)
    if not file.filename:
        raise HTTPException(status_code=400, detail="missing filename")
    uploads_dir = Path("/app/data/uploads")
    uploads_dir.mkdir(parents=True, exist_ok=True)
    safe_name = Path(file.filename).name
    suffix = Path(safe_name).suffix.lower()
    if suffix not in {".jpg", ".jpeg", ".png", ".webp", ".bmp"}:
        raise HTTPException(status_code=400, detail="unsupported image format")
    # Read FormData session_id properly — may come as form field
    target = uploads_dir / f"{uuid4().hex[:8]}_{safe_name}"
    target.write_bytes(file.file.read())
    path = str(target)
    # Store in chat session state if session_id provided
    if session_id:
        session = chat.get_session(session_id)
        state = session.get("state", {})
        state["image_path"] = path
        session["state"] = state
        chat._save_session(session_id, session)
    return {"path": path, "filename": target.name}


@router.post("/voice-samples/upload")
def upload_voice_sample(file: UploadFile = File(...), x_admin_token: str | None = Header(default=None)) -> dict:
    _check_token(x_admin_token)
    if not file.filename:
        raise HTTPException(status_code=400, detail="missing filename")
    voices_dir = Path("/app/data/voices")
    voices_dir.mkdir(parents=True, exist_ok=True)
    safe_name = Path(file.filename).name
    suffix = Path(safe_name).suffix.lower()
    if suffix not in {".wav", ".mp3", ".m4a", ".ogg", ".flac"}:
        raise HTTPException(status_code=400, detail="unsupported audio format")
    target = voices_dir / safe_name
    if target.exists():
        target = voices_dir / f"{Path(safe_name).stem}_{int(datetime.utcnow().timestamp())}{suffix}"
    target.write_bytes(file.file.read())
    return {"filename": target.name}


@router.delete("/jobs/{job_id}")
def delete_job(job_id: str, x_admin_token: str | None = Header(default=None)) -> dict:
    _check_token(x_admin_token)
    queue.delete_job(job_id)
    return {"job_id": job_id, "status": "deleted"}


@router.post("/jobs/{job_id}/retry")
def retry_job(job_id: str, x_admin_token: str | None = Header(default=None)) -> dict:
    _check_token(x_admin_token)
    item = queue.get_job_status(job_id)
    if not item:
        raise HTTPException(status_code=404, detail="job not found")
    original_payload = item.get("payload") or {}
    if not isinstance(original_payload, dict):
        original_payload = {}
    if not original_payload:
        original_payload = {
            "mode": item.get("mode", "horror"),
            "title": item.get("title", item.get("topic", "")),
            "content": item.get("content", ""),
            "language": item.get("language", "en"),
            "tone": item.get("tone", "friendly"),
            "use_gemini_refine": item.get("use_gemini_refine", False),
            "create_audio": item.get("create_audio", True),
            "create_video": item.get("create_video", True),
            "video_source_type": item.get("video_source_type", "self"),
            "video_keyword": item.get("video_keyword"),
            "user_video_path": item.get("user_video_path"),
            "notify_telegram": item.get("notify_telegram", True),
            "telegram_chat_id": item.get("telegram_chat_id"),
        }
    retry_payload = dict(original_payload)
    retry_payload["job_id"] = str(uuid4())
    retry_payload["created_at"] = datetime.utcnow().isoformat()
    retry_payload["revision_of_job_id"] = job_id
    retry_payload["feedback_round"] = int(item.get("feedback_round", 0)) + 1
    queue.enqueue(retry_payload)
    queue.set_job_status(job_id=retry_payload["job_id"], payload={
        "job_id": retry_payload["job_id"], "status": "queued",
        "title": retry_payload.get("title"), "mode": retry_payload.get("mode"),
        "queued_at": datetime.utcnow().isoformat(),
        "revision_of_job_id": job_id, "feedback_round": retry_payload["feedback_round"],
        "payload": retry_payload,
    })
    return {"job_id": retry_payload["job_id"], "status": "queued"}


@router.get("/jobs/{job_id}/video")
def get_job_video(job_id: str, token: str | None = None, x_admin_token: str | None = Header(default=None)) -> FileResponse:
    actual_token = x_admin_token or token
    _check_token(actual_token)
    item = queue.get_job_status(job_id)
    if not item:
        raise HTTPException(status_code=404, detail="job not found")
    video_path = (item.get("outputs") or {}).get("video_path")
    if not video_path:
        raise HTTPException(status_code=404, detail="video not found")
    path = Path(video_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="video file missing")
    return FileResponse(path, media_type="video/mp4", filename=path.name)


@router.post("/jobs/{job_id}/approve")
def approve_job(job_id: str, x_admin_token: str | None = Header(default=None)) -> dict:
    _check_token(x_admin_token)
    item = queue.get_job_status(job_id)
    if not item:
        raise HTTPException(status_code=404, detail="job not found")
    if item.get("status") != "review_pending":
        raise HTTPException(status_code=400, detail="job is not in review_pending state")
    original_payload = item.get("payload") or {}
    compose_payload = dict(original_payload) if isinstance(original_payload, dict) else {}
    compose_payload["compose_only"] = True
    compose_payload["job_id"] = job_id
    queue.enqueue(compose_payload)
    return {"job_id": job_id, "status": "composing"}


@router.get("/jobs/{job_id}/audio")
def get_job_audio(job_id: str, token: str | None = None, x_admin_token: str | None = Header(default=None)) -> FileResponse:
    actual_token = x_admin_token or token
    _check_token(actual_token)
    item = queue.get_job_status(job_id)
    if not item:
        raise HTTPException(status_code=404, detail="job not found")
    audio_path = (item.get("review") or {}).get("audio_path") or (item.get("outputs") or {}).get("audio_path")
    if not audio_path:
        raise HTTPException(status_code=404, detail="audio not found")
    path = Path(audio_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="audio file missing")
    media_type = "audio/mpeg" if path.suffix == ".mp3" else "audio/wav"
    return FileResponse(path, media_type=media_type, filename=path.name)


@router.get("/jobs/{job_id}")
def get_job(job_id: str, x_admin_token: str | None = Header(default=None)) -> dict:
    _check_token(x_admin_token)
    item = queue.get_job_status(job_id)
    if not item:
        raise HTTPException(status_code=404, detail="job not found")
    return item