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
from pydantic import BaseModel
from pydantic import Field

from app.config import settings
from app.schemas import ContentMode
from app.schemas import ContentOption
from app.schemas import GenerateOptionsRequest
from app.schemas import GenerateOptionsResponse
from app.schemas import JobPayload
from app.services.llm_service import LLMService
from app.services.queue_service import QueueService

router = APIRouter(prefix="/web", tags=["web"])
queue = QueueService(redis_url=settings.redis_url, queue_name=settings.job_queue_name)
llm = LLMService()


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


def _token_from_header(x_admin_token: str | None = Header(default=None)) -> str | None:
    return x_admin_token


@router.get("", response_class=HTMLResponse)
def web_home() -> str:
    return """<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>AI Short Content Generator (EN)</title>
    <style>
      :root {
        --bg: #0f1119;
        --card: #181b28;
        --text: #e8ecf4;
        --muted: #8b90a5;
        --line: #262a38;
        --accent: #7c3aed;
        --accent-glow: #a78bfa;
        --green: #10b981;
        --red: #ef4444;
        --chip-bg: #1f2233;
        --chip-active: #7c3aed22;
        --chip-border: #7c3aed55;
      }

      * { box-sizing: border-box; }
      body {
        margin: 0;
        color: var(--text);
        background: var(--bg);
        font-family: "Inter", "Segoe UI", system-ui, sans-serif;
        min-height: 100vh;
      }

      .wrap {
        max-width: 900px;
        margin: 0 auto;
        padding: 24px 16px 48px;
      }

      .hero {
        text-align: center;
        padding: 32px 16px 20px;
      }
      .hero h1 {
        margin: 0;
        font-size: 28px;
        background: linear-gradient(135deg, #c084fc, #818cf8);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
      }
      .hero p {
        margin: 8px 0 0;
        color: var(--muted);
        font-size: 14px;
      }

      .step-row {
        display: flex;
        justify-content: center;
        gap: 8px;
        margin: 20px 0 4px;
        flex-wrap: wrap;
      }
      .step-dot {
        width: 34px; height: 34px;
        border-radius: 50%;
        display: flex; align-items: center; justify-content: center;
        font-weight: 700; font-size: 13px;
        background: var(--chip-bg);
        border: 2px solid var(--line);
        color: var(--muted);
        transition: all 0.3s;
      }
      .step-dot.active {
        border-color: var(--accent);
        background: var(--chip-active);
        color: var(--accent-glow);
        box-shadow: 0 0 12px var(--chip-border);
      }
      .step-dot.done {
        border-color: var(--green);
        background: #10b98122;
        color: var(--green);
      }

      .card {
        background: var(--card);
        border: 1px solid var(--line);
        border-radius: 16px;
        padding: 20px;
        margin-bottom: 14px;
      }
      .card h3 {
        margin: 0 0 4px;
        font-size: 16px;
        color: var(--accent-glow);
      }
      .card .hint {
        margin: 0 0 14px;
        color: var(--muted);
        font-size: 12px;
      }

      .row {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 12px;
      }
      @media (max-width: 600px) { .row { grid-template-columns: 1fr; } }

      label {
        display: block;
        font-size: 12px;
        color: var(--muted);
        margin-top: 10px;
        text-transform: uppercase;
        letter-spacing: 0.5px;
      }
      input, select, button, textarea {
        width: 100%;
        padding: 10px 12px;
        border-radius: 10px;
        border: 1px solid var(--line);
        background: var(--bg);
        color: var(--text);
        font: inherit;
        font-size: 14px;
      }
      textarea { min-height: 80px; resize: vertical; }
      button {
        cursor: pointer;
        border: 0;
        font-weight: 600;
        margin-top: 10px;
        transition: all 0.2s;
      }
      button.primary {
        background: linear-gradient(135deg, var(--accent), #6366f1);
        color: #fff;
      }
      button.primary:hover { box-shadow: 0 0 20px var(--chip-border); }
      button.secondary {
        background: var(--chip-bg);
        color: var(--text);
        border: 1px solid var(--line);
      }
      button.secondary:hover { border-color: var(--accent); }
      button.danger {
        background: #ef444422;
        color: var(--red);
        border: 1px solid #ef444455;
      }

      .mode-grid {
        display: grid;
        grid-template-columns: repeat(2, 1fr);
        gap: 10px;
        margin: 10px 0;
      }
      @media (max-width: 500px) { .mode-grid { grid-template-columns: 1fr; } }

      .mode-card {
        background: var(--chip-bg);
        border: 2px solid var(--line);
        border-radius: 14px;
        padding: 14px;
        cursor: pointer;
        text-align: center;
        transition: all 0.2s;
      }
      .mode-card:hover { border-color: var(--accent); }
      .mode-card.selected {
        border-color: var(--accent);
        background: var(--chip-active);
        box-shadow: 0 0 16px var(--chip-border);
      }
      .mode-card .icon { font-size: 28px; margin-bottom: 4px; }
      .mode-card .name { font-weight: 700; font-size: 14px; }
      .mode-card .desc { font-size: 11px; color: var(--muted); margin-top: 4px; }

      .option-card {
        background: var(--bg);
        border: 2px solid var(--line);
        border-radius: 14px;
        padding: 14px;
        margin-top: 8px;
        cursor: pointer;
        transition: all 0.2s;
        position: relative;
      }
      .option-card:hover { border-color: var(--accent); }
      .option-card.selected {
        border-color: var(--accent);
        box-shadow: 0 0 14px var(--chip-border);
      }
      .option-card .option-title {
        font-weight: 700;
        font-size: 14px;
        margin: 0 0 6px;
      }
      .option-card .option-content {
        font-size: 12px;
        color: var(--muted);
        max-height: 120px;
        overflow: hidden;
        line-height: 1.5;
        position: relative;
      }
      .option-card .option-content::after {
        content: '';
        position: absolute;
        bottom: 0;
        left: 0;
        right: 0;
        height: 30px;
        background: linear-gradient(transparent, var(--bg));
      }
      .option-card.selected .option-content { max-height: none; color: var(--text); }
      .option-card.selected .option-content::after { display: none; }
      .option-badge {
        position: absolute;
        top: 10px; right: 10px;
        background: var(--accent);
        color: #fff;
        font-size: 10px;
        font-weight: 700;
        padding: 3px 8px;
        border-radius: 999px;
        display: none;
      }
      .option-card.selected .option-badge { display: block; }

      .is-hidden { display: none !important; }
      .status-msg {
        margin-top: 10px;
        padding: 8px 12px;
        border-radius: 10px;
        font-size: 12px;
        background: #7c3aed15;
        border: 1px solid var(--chip-border);
        word-break: break-word;
      }
      .status-msg.error {
        background: #ef444415;
        border-color: #ef444455;
        color: #fca5a5;
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
        font-size: 13px;
      }
      .check-item input { width: auto; margin: 0; accent-color: var(--accent); }
      pre {
        margin: 8px 0 0;
        background: #0b0d14;
        color: #a5b4fc;
        padding: 12px;
        border-radius: 10px;
        overflow: auto;
        font-size: 11px;
        max-height: 300px;
        white-space: pre-wrap;
        border: 1px solid var(--line);
      }

      /* ---- Modal ---- */
      .modal-backdrop {
        position: fixed;
        inset: 0;
        background: rgba(5, 7, 16, 0.85);
        display: none;
        align-items: center;
        justify-content: center;
        padding: 20px;
        z-index: 50;
      }
      .modal-backdrop.open { display: flex; }
      .modal {
        width: min(900px, 100%);
        max-height: 85vh;
        overflow: auto;
        background: var(--card);
        border-radius: 16px;
        border: 1px solid var(--line);
        box-shadow: 0 30px 80px rgba(5, 7, 16, 0.6);
        padding: 20px;
      }
      .modal-head {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 12px;
        margin-bottom: 14px;
      }
      .modal-title { margin: 0; font-size: 18px; font-weight: 800; color: var(--accent-glow); }

      .job-list { display: grid; gap: 10px; }
      .job-card {
        background: var(--bg);
        border: 1px solid var(--line);
        border-radius: 12px;
        padding: 12px;
      }
      .job-card.failed { border-color: #ef444444; background: #ef44440a; }
      .job-head {
        display: flex;
        justify-content: space-between;
        gap: 12px;
        align-items: flex-start;
      }
      .job-title-text { font-weight: 700; margin: 0; }
      .job-status-badge {
        font-size: 11px;
        font-weight: 700;
        padding: 2px 8px;
        border-radius: 999px;
        white-space: nowrap;
      }
      .job-status-badge.queued { background: #6366f122; color: #818cf8; }
      .job-status-badge.running { background: #f59e0b22; color: #fbbf24; }
      .job-status-badge.completed { background: #10b98122; color: #34d399; }
      .job-status-badge.failed { background: #ef444422; color: #fca5a5; }
      .job-meta {
        margin-top: 6px;
        color: var(--muted);
        font-size: 11px;
        line-height: 1.5;
      }
      .job-actions {
        display: flex;
        gap: 6px;
        flex-wrap: wrap;
        margin-top: 10px;
      }
      .job-actions button { margin-top: 0; font-size: 12px; padding: 6px 10px; width: auto; }
      .job-error {
        margin-top: 8px;
        color: #fca5a5;
        background: #ef444412;
        border: 1px solid #ef444433;
        border-radius: 8px;
        padding: 6px 10px;
        font-size: 11px;
        white-space: pre-wrap;
        max-height: 80px;
        overflow: auto;
      }
      .mini-progress {
        margin-top: 8px;
      }
      .mini-progress-bar {
        height: 6px;
        border-radius: 999px;
        background: var(--line);
        overflow: hidden;
      }
      .mini-progress-fill {
        height: 100%;
        background: linear-gradient(135deg, var(--accent), #6366f1);
        transition: width 0.3s;
      }
      .mini-progress-label {
        margin-top: 4px;
        color: var(--muted);
        font-size: 11px;
      }
    </style>
  </head>
  <body>
    <div class="wrap">
      <div class="hero">
        <h1>AI Short Content Generator</h1>
        <p>Horror Stories · Wealth Tips · Soft Skills · World Mysteries — All in English</p>
        <div class="step-row">
          <span id="stepDot1" class="step-dot active">1</span>
          <span id="stepDot2" class="step-dot">2</span>
          <span id="stepDot3" class="step-dot">3</span>
          <span id="stepDot4" class="step-dot">4</span>
        </div>
        <div style="margin-top:14px">
          <button class="secondary" onclick="openResultsModal()" style="width:auto;margin-top:0">📋 View All Jobs</button>
        </div>
      </div>

      <!-- STEP 1: Admin token -->
      <div id="step1Card" class="card">
        <h3>Step 1: Admin Token</h3>
        <p class="hint">Enter your admin token to begin.</p>
        <input id="tokenInput" placeholder="WEB_ADMIN_TOKEN" />
        <button class="primary" onclick="saveToken()">Continue</button>
      </div>

      <!-- STEP 2: Pick mode & generate options, then select one -->
      <div id="step2Card" class="card is-hidden">
        <h3>Step 2: Choose Content Mode & Select Script</h3>
        <p class="hint">Pick a category, then generate title + content options. Click one to select.</p>

        <div class="mode-grid">
          <div class="mode-card selected" data-mode="horror" onclick="selectMode('horror')">
            <div class="icon">👻</div>
            <div class="name">Horror Story</div>
            <div class="desc">Chilling tales that keep viewers on edge</div>
          </div>
          <div class="mode-card" data-mode="wealth" onclick="selectMode('wealth')">
            <div class="icon">💰</div>
            <div class="name">Wealth & Success</div>
            <div class="desc">Money principles & success mindsets</div>
          </div>
          <div class="mode-card" data-mode="softskills" onclick="selectMode('softskills')">
            <div class="icon">🗣️</div>
            <div class="name">Soft Skills</div>
            <div class="desc">Communication, leadership & life skills</div>
          </div>
          <div class="mode-card" data-mode="mystery" onclick="selectMode('mystery')">
            <div class="icon">🔮</div>
            <div class="name">World Mysteries</div>
            <div class="desc">Unsolved cases, conspiracies & paranormal</div>
          </div>
        </div>

        <div class="row">
          <div>
            <label>Language</label>
            <input id="langInput" value="en" />
          </div>
          <div>
            <label>Tone</label>
            <select id="toneInput">
              <option value="friendly">Friendly</option>
              <option value="dramatic">Dramatic</option>
              <option value="calm">Calm</option>
              <option value="suspenseful">Suspenseful</option>
              <option value="authoritative">Authoritative</option>
            </select>
          </div>
        </div>

        <label>Number of options</label>
        <select id="optionCount">
          <option value="3">3 options</option>
          <option value="4">4 options</option>
          <option value="5">5 options</option>
        </select>

        <button class="primary" onclick="generateOptions()">Generate Options</button>
        <button class="secondary" onclick="regenerateOptions()">Regenerate</button>
        <div id="optionsContainer" style="margin-top:10px"></div>
        <div id="step2Status" class="status-msg">Select a content mode and generate options.</div>
        <button id="step2ConfirmBtn" class="primary is-hidden" onclick="confirmSelection()">Confirm Selection & Continue</button>
      </div>

      <!-- STEP 3: Audio & Video options -->
      <div id="step3Card" class="card is-hidden">
        <h3>Step 3: Audio & Video Settings</h3>
        <p class="hint">Configure voice, video source, and other options.</p>

        <div class="row">
          <div>
            <label>Kokoro Voice</label>
            <select id="kokoroVoice">
              <option value="af_heart">Female - Heart (warm)</option>
              <option value="af_bella">Female - Bella (soft)</option>
              <option value="af_nicole">Female - Nicole (clear)</option>
              <option value="am_adam">Male - Adam (deep)</option>
              <option value="am_michael">Male - Michael (calm)</option>
            </select>
          </div>
          <div>
            <label>Video Source</label>
            <select id="videoSourceType" onchange="syncVideoInputs()">
              <option value="self">Your own video</option>
              <option value="internet">Internet - stock footage</option>
            </select>
          </div>
        </div>

        <div class="row">
          <div>
            <label>Source Video Path (if own video)</label>
            <input id="videoPath" placeholder="/app/data/uploads/video.mp4" />
          </div>
          <div>
            <label>Video Keyword (internet search)</label>
            <input id="videoKeyword" placeholder="dark forest, haunted..." />
          </div>
        </div>

        <div class="row">
          <div>
            <label>Telegram Chat ID (optional)</label>
            <input id="telegramChatId" placeholder="Chat ID" />
          </div>
          <div></div>
        </div>

        <div class="check-grid">
          <label class="check-item"><input id="createAudio" type="checkbox" checked /> Create Audio</label>
          <label class="check-item"><input id="createVideo" type="checkbox" checked /> Create Video</label>
          <label class="check-item"><input id="useGemini" type="checkbox" /> Gemini Refine</label>
          <label class="check-item"><input id="notifyTelegram" type="checkbox" checked /> Notify Telegram</label>
        </div>

        <button class="primary" onclick="confirmAudioVideo()">Continue to Finalize</button>
        <div id="step3Status" class="status-msg">Configure your audio and video settings.</div>
      </div>

      <!-- STEP 4: Review & Submit -->
      <div id="step4Card" class="card is-hidden">
        <h3>Step 4: Review & Submit</h3>
        <p class="hint">Review your selected content and settings, then run the job.</p>

        <div id="reviewBlock">
          <div style="margin-bottom:8px">
            <strong>Mode:</strong> <span id="reviewMode"></span> &nbsp;
            <strong>Language:</strong> <span id="reviewLang"></span> &nbsp;
            <strong>Tone:</strong> <span id="reviewTone"></span>
          </div>
          <div style="margin-bottom:8px">
            <strong>Voice:</strong> <span id="reviewVoice"></span> &nbsp;
            <strong>Video Source:</strong> <span id="reviewVideoSrc"></span>
          </div>
          <div style="margin-bottom:4px"><strong>Title:</strong></div>
          <div id="reviewTitle" style="font-weight:700;font-size:15px;margin-bottom:8px"></div>
          <div style="margin-bottom:4px"><strong>Content Preview:</strong></div>
          <pre id="reviewContent"></pre>
        </div>

        <button class="primary" onclick="submitJob()">Run Job</button>
        <div id="jobResult" class="status-msg" style="margin-top:12px"></div>
        <div id="jobActions" style="margin-top:8px;display:flex;gap:8px;flex-wrap:wrap"></div>
      </div>
    </div>

    <!-- Results Modal -->
    <div id="resultsModalBackdrop" class="modal-backdrop" onclick="if (event.target === this) closeResultsModal()">
      <div class="modal">
        <div class="modal-head">
          <h3 class="modal-title">Job Results</h3>
          <button class="secondary" onclick="closeResultsModal()" style="margin-top:0;width:auto">Close</button>
        </div>
        <div class="modal-body">
          <button class="secondary" onclick="loadJobs()" style="width:auto">Refresh List</button>
          <div id="jobsList" class="job-list" style="margin-top:10px"></div>
        </div>
      </div>
    </div>

    <!-- Detail Modal -->
    <div id="detailModalBackdrop" class="modal-backdrop" onclick="if (event.target === this) closeDetailModal()">
      <div class="modal">
        <div class="modal-head">
          <h3 id="detailModalTitle" class="modal-title">Job Detail</h3>
          <button class="secondary" onclick="closeDetailModal()" style="margin-top:0;width:auto">Close</button>
        </div>
        <div id="detailModalBody" class="modal-body"></div>
      </div>
    </div>

    <script>
      const tokenInput = document.getElementById('tokenInput');
      let currentMode = 'horror';
      let currentOptions = [];
      let selectedOptionIndex = -1;
      let selectedTitle = '';
      let selectedContent = '';
      let currentStep = 1;
      let activeVideoObjectUrl = '';

      tokenInput.value = localStorage.getItem('adminToken') || '';
      syncVideoInputs();

      function getToken() { return localStorage.getItem('adminToken') || ''; }
      function escapeHtml(v) { return String(v).replaceAll('&','&').replaceAll('<','<').replaceAll('>','>').replaceAll('"','"'); }

      async function api(url, options = {}) {
        const headers = options.headers || {};
        headers['x-admin-token'] = getToken();
        options.headers = headers;
        const resp = await fetch(url, options);
        if (!resp.ok) throw new Error(await resp.text());
        return await resp.json();
      }

      async function fetchBlob(url) {
        const resp = await fetch(url, { headers: { 'x-admin-token': getToken() } });
        if (!resp.ok) throw new Error(await resp.text());
        return await resp.blob();
      }

      function setStep(n) {
        currentStep = n;
        for (let i = 1; i <= 4; i++) {
          const dot = document.getElementById('stepDot' + i);
          dot.classList.remove('active', 'done');
          if (i < n) dot.classList.add('done');
          if (i === n) dot.classList.add('active');
        }
        document.getElementById('step1Card').classList.toggle('is-hidden', n !== 1);
        document.getElementById('step2Card').classList.toggle('is-hidden', n !== 2);
        document.getElementById('step3Card').classList.toggle('is-hidden', n !== 3);
        document.getElementById('step4Card').classList.toggle('is-hidden', n !== 4);
      }

      function saveToken() {
        const v = tokenInput.value.trim();
        if (!v) return alert('Enter token');
        localStorage.setItem('adminToken', v);
        setStep(2);
      }

      function selectMode(mode) {
        currentMode = mode;
        document.querySelectorAll('.mode-card').forEach(c => c.classList.remove('selected'));
        document.querySelector(`[data-mode="${mode}"]`).classList.add('selected');
        selectedOptionIndex = -1;
        selectedTitle = '';
        selectedContent = '';
        document.getElementById('step2ConfirmBtn').classList.add('is-hidden');
      }

      async function generateOptions() {
        const count = parseInt(document.getElementById('optionCount').value) || 3;
        const lang = document.getElementById('langInput').value || 'en';
        const tone = document.getElementById('toneInput').value || 'friendly';
        const container = document.getElementById('optionsContainer');
        const status = document.getElementById('step2Status');
        const confirmBtn = document.getElementById('step2ConfirmBtn');

        container.innerHTML = '<div class="status-msg">Generating options...</div>';
        confirmBtn.classList.add('is-hidden');
        selectedOptionIndex = -1;

        try {
          const data = await api('/web/generate-options', {
            method: 'POST',
            headers: {'content-type': 'application/json'},
            body: JSON.stringify({ mode: currentMode, language: lang, tone, count }),
          });
          currentOptions = data.options || [];
          if (!currentOptions.length) throw new Error('No options returned');
          renderOptions(currentOptions);
          status.innerText = `${currentOptions.length} options generated. Click one to select.`;
          status.className = 'status-msg';
        } catch (e) {
          status.innerText = 'Error: ' + e.message;
          status.className = 'status-msg error';
          container.innerHTML = '';
        }
      }

      async function regenerateOptions() {
        const container = document.getElementById('optionsContainer');
        container.innerHTML = '<div class="status-msg">Regenerating...</div>';
        await generateOptions();
      }

      function renderOptions(options) {
        const container = document.getElementById('optionsContainer');
        container.innerHTML = options.map((opt, i) => `
          <div class="option-card" data-index="${i}" onclick="pickOption(${i})">
            <span class="option-badge">SELECTED</span>
            <div class="option-title">${escapeHtml(opt.title)}</div>
            <div class="option-content">${escapeHtml(opt.content)}</div>
          </div>
        `).join('');
      }

      function pickOption(index) {
        if (index < 0 || index >= currentOptions.length) return;
        selectedOptionIndex = index;
        selectedTitle = currentOptions[index].title;
        selectedContent = currentOptions[index].content;

        document.querySelectorAll('.option-card').forEach((c, i) => {
          c.classList.toggle('selected', i === index);
        });
        document.getElementById('step2ConfirmBtn').classList.remove('is-hidden');
        document.getElementById('step2Status').innerText = 'Option ' + (index + 1) + ' selected. Review it above, then confirm.';
      }

      function confirmSelection() {
        if (selectedOptionIndex < 0) return alert('Select an option first');
        setStep(3);
      }

      function syncVideoInputs() {
        const srcType = document.getElementById('videoSourceType').value;
        document.getElementById('videoPath').disabled = (srcType !== 'self');
        document.getElementById('videoKeyword').disabled = (srcType !== 'internet');
      }

      function confirmAudioVideo() {
        const lang = document.getElementById('langInput').value || 'en';
        const tone = document.getElementById('toneInput').value || 'friendly';
        const kokoroVoice = document.getElementById('kokoroVoice').value;
        const videoSrc = document.getElementById('videoSourceType').value;

        const voiceLabels = {
          'af_heart': 'Female - Heart (warm)',
          'af_bella': 'Female - Bella (soft)',
          'af_nicole': 'Female - Nicole (clear)',
          'am_adam': 'Male - Adam (deep)',
          'am_michael': 'Male - Michael (calm)',
        };

        document.getElementById('reviewMode').innerText = currentMode;
        document.getElementById('reviewLang').innerText = lang;
        document.getElementById('reviewTone').innerText = tone;
        document.getElementById('reviewVoice').innerText = voiceLabels[kokoroVoice] || kokoroVoice;
        document.getElementById('reviewVideoSrc').innerText = videoSrc === 'internet' ? 'Internet Stock' : 'Own Video';
        document.getElementById('reviewTitle').innerText = selectedTitle;
        document.getElementById('reviewContent').innerText = selectedContent;

        setStep(4);
      }

      async function submitJob() {
        if (!selectedTitle || !selectedContent) return alert('No content selected. Go back to Step 2.');

        const body = {
          mode: currentMode,
          title: selectedTitle,
          content: selectedContent,
          language: document.getElementById('langInput').value || 'en',
          tone: document.getElementById('toneInput').value || 'friendly',
          use_gemini_refine: document.getElementById('useGemini').checked,
          create_audio: document.getElementById('createAudio').checked,
          create_video: document.getElementById('createVideo').checked,
          video_source_type: document.getElementById('videoSourceType').value,
          user_video_path: document.getElementById('videoPath').value || null,
          video_keyword: document.getElementById('videoKeyword').value || null,
          kokoro_voice: document.getElementById('kokoroVoice').value || 'af_heart',
          notify_telegram: document.getElementById('notifyTelegram').checked,
          telegram_chat_id: document.getElementById('telegramChatId').value || null,
        };

        try {
          const data = await api('/web/jobs', {
            method: 'POST',
            headers: {'content-type': 'application/json'},
            body: JSON.stringify(body),
          });
          document.getElementById('jobResult').innerText = 'Job submitted: ' + data.job_id;
          document.getElementById('jobResult').className = 'status-msg';
          document.getElementById('jobActions').innerHTML = `
            <button class="secondary" onclick="viewJobDetail('${data.job_id}')">View Details</button>
          `;
        } catch (e) {
          document.getElementById('jobResult').innerText = 'Error: ' + e.message;
          document.getElementById('jobResult').className = 'status-msg error';
        }
      }

      // ---- Jobs Modal ----
      function openResultsModal() {
        document.getElementById('resultsModalBackdrop').classList.add('open');
        loadJobs();
      }
      function closeResultsModal() {
        document.getElementById('resultsModalBackdrop').classList.remove('open');
      }

      async function loadJobs() {
        const container = document.getElementById('jobsList');
        container.innerHTML = '<div class="status-msg">Loading...</div>';
        try {
          const data = await api('/web/jobs?limit=30');
          renderJobs(data.items || []);
        } catch (e) {
          container.innerHTML = `<div class="status-msg error">Error: ${escapeHtml(e.message)}</div>`;
        }
      }

      function renderJobs(items) {
        const container = document.getElementById('jobsList');
        if (!items.length) {
          container.innerHTML = '<div class="status-msg">No jobs yet.</div>';
          return;
        }

        const statusLabels = { queued: 'Queued', running: 'Running', review_pending: 'Review', completed: 'Completed', failed: 'Failed' };

        container.innerHTML = items.map(item => {
          const status = item.status || 'unknown';
          const title = escapeHtml(item.title || item.topic || 'Untitled');
          const jobId = escapeHtml(item.job_id || '');
          const mode = escapeHtml(item.mode || '');
          const stage = escapeHtml(item.current_stage || item.stage_detail || '');
          const pct = Math.max(0, Math.min(Number(item.progress_percent || 0), 100));

          const meta = [
            `ID: ${jobId}`,
            `Mode: ${mode}`,
            item.started_at ? `Started: ${item.started_at}` : '',
            item.completed_at ? `Completed: ${item.completed_at}` : '',
            item.failed_at ? `Failed: ${item.failed_at}` : '',
          ].filter(Boolean).join('<br/>');

          const errorBlock = item.error ? `<div class="job-error">${escapeHtml(item.error)}</div>` : '';

          const progressBlock = (status === 'running' || status === 'completed')
            ? `<div class="mini-progress">
                <div class="mini-progress-bar"><div class="mini-progress-fill" style="width:${pct}%"></div></div>
                <div class="mini-progress-label">${stage || 'Processing'} &bull; ${pct}%</div>
              </div>`
            : '';

          const actions = [];
          if (status === 'completed') {
            actions.push(`<button class="secondary" onclick="window.open('/web/jobs/${jobId}/video?token='+encodeURIComponent(getToken()), '_blank')">Preview Video</button>`);
          }
          if (status === 'failed') {
            actions.push(`<button class="secondary" onclick="retryJob('${jobId}')">Retry</button>`);
          }
          actions.push(`<button class="secondary" onclick="viewJobDetail('${jobId}')">View Details</button>`);
          actions.push(`<button class="danger" onclick="deleteJob('${jobId}')">Delete</button>`);

          return `
            <div class="job-card ${status === 'failed' ? 'failed' : ''}">
              <div class="job-head">
                <p class="job-title-text">${title}</p>
                <span class="job-status-badge ${status}">${escapeHtml(statusLabels[status] || status)}</span>
              </div>
              <div class="job-meta">${meta}</div>
              ${progressBlock}
              ${errorBlock}
              <div class="job-actions">${actions.join('')}</div>
            </div>
          `;
        }).join('');
      }

      async function viewJobDetail(jobId) {
        try {
          const data = await api(`/web/jobs/${jobId}`);
          let videoHtml = '';
          if (data.outputs && data.outputs.video_path) {
            videoHtml = `<video controls playsinline style="width:100%;max-height:50vh;border-radius:12px;background:#000" src="/web/jobs/${jobId}/video?token=${encodeURIComponent(getToken())}"></video>`;
          } else {
            videoHtml = '<div class="status-msg">No video yet.</div>';
          }
          document.getElementById('detailModalTitle').innerText = `Job ${jobId}`;
          document.getElementById('detailModalBody').innerHTML = `
            ${videoHtml}
            <pre style="margin-top:12px">${escapeHtml(JSON.stringify(data, null, 2))}</pre>
          `;
          document.getElementById('detailModalBackdrop').classList.add('open');
        } catch (e) {
          alert(e.message);
        }
      }
      function closeDetailModal() {
        if (activeVideoObjectUrl) { URL.revokeObjectURL(activeVideoObjectUrl); activeVideoObjectUrl = ''; }
        document.getElementById('detailModalBackdrop').classList.remove('open');
      }

      async function deleteJob(jobId) {
        if (!confirm('Delete job ' + jobId + '?')) return;
        try {
          await api('/web/jobs/' + jobId, { method: 'DELETE' });
          await loadJobs();
        } catch (e) {
          alert(e.message);
        }
      }

      async function retryJob(jobId) {
        try {
          const data = await api('/web/jobs/' + jobId + '/retry', { method: 'POST' });
          alert('Retry job created: ' + data.job_id);
          await loadJobs();
        } catch (e) {
          alert(e.message);
        }
      }

      // Initial
      if (getToken() && tokenInput.value.trim()) {
        setStep(2);
      } else {
        setStep(1);
      }
    </script>
  </body>
</html>
"""


# === API endpoints ===

@router.post("/generate-options", response_model=GenerateOptionsResponse)
def generate_options(body: GenerateOptionsRequest, x_admin_token: str | None = Header(default=None)) -> dict:
    _check_token(x_admin_token)
    mode = body.mode.value if hasattr(body.mode, 'value') else body.mode
    options_raw = llm.generate_options(
        mode=mode,
        language=body.language,
        tone=body.tone,
        count=body.count,
    )
    options = [
        ContentOption(title=opt["title"], content=opt["content"])
        for opt in options_raw
    ]
    return {"options": options}


@router.post("/jobs")
def create_web_job(body: CreateWebJobRequest, x_admin_token: str | None = Header(default=None)) -> dict:
    _check_token(x_admin_token)

    valid_modes = {"horror", "wealth", "softskills", "mystery", "sales", "story"}
    mode = body.mode if body.mode in valid_modes else "horror"

    job_id = str(uuid4())
    payload = JobPayload(
        job_id=job_id,
        created_at=datetime.utcnow().isoformat(),
        mode=mode,
        title=body.title,
        content=body.content,
        language=body.language,
        tone=body.tone,
        use_gemini_refine=body.use_gemini_refine,
        create_audio=body.create_audio,
        create_video=body.create_video,
        video_source_type=("internet" if body.video_source_type == "internet" else "self"),
        video_keyword=body.video_keyword,
        user_video_path=body.user_video_path,
        voice_sample_filename=body.voice_sample_filename,
        edge_tts_voice=body.edge_tts_voice,
        kokoro_voice=body.kokoro_voice,
        notify_telegram=body.notify_telegram,
        telegram_chat_id=body.telegram_chat_id,
    )

    queue.enqueue(payload.model_dump())
    queue.set_job_status(
        job_id=job_id,
        payload={
            "job_id": job_id,
            "status": "queued",
            "title": body.title,
            "mode": mode,
            "queued_at": datetime.utcnow().isoformat(),
            "payload": payload.model_dump(),
        },
    )
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
    items = sorted(
        path.name for path in voices_dir.iterdir()
        if path.is_file() and path.suffix.lower() in allowed_ext
    )
    return {"items": items}


@router.post("/voice-samples/upload")
def upload_voice_sample(file: UploadFile = File(...), x_admin_token: str | None = Header(default=None)) -> dict:
    _check_token(x_admin_token)
    if not file.filename:
        raise HTTPException(status_code=400, detail="missing filename")
    voices_dir = Path("/app/data/voices")
    voices_dir.mkdir(parents=True, exist_ok=True)
    safe_name = Path(file.filename).name
    suffix = Path(safe_name).suffix.lower()
    allowed_ext = {".wav", ".mp3", ".m4a", ".ogg", ".flac"}
    if suffix not in allowed_ext:
        raise HTTPException(status_code=400, detail="unsupported audio format")
    stem = Path(safe_name).stem
    target = voices_dir / safe_name
    if target.exists():
        target = voices_dir / f"{stem}_{int(datetime.utcnow().timestamp())}{suffix}"
    content = file.file.read()
    target.write_bytes(content)
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
            "voice_sample_filename": item.get("voice_sample_filename"),
            "edge_tts_voice": item.get("edge_tts_voice", settings.edge_tts_voice),
            "notify_telegram": item.get("notify_telegram", True),
            "telegram_chat_id": item.get("telegram_chat_id"),
        }

    retry_payload = dict(original_payload)
    retry_payload["job_id"] = str(uuid4())
    retry_payload["created_at"] = datetime.utcnow().isoformat()
    retry_payload["revision_of_job_id"] = job_id
    retry_payload["feedback_round"] = int(item.get("feedback_round", 0)) + 1

    queue.enqueue(retry_payload)
    queue.set_job_status(
        job_id=retry_payload["job_id"],
        payload={
            "job_id": retry_payload["job_id"],
            "status": "queued",
            "title": retry_payload.get("title"),
            "mode": retry_payload.get("mode"),
            "queued_at": datetime.utcnow().isoformat(),
            "revision_of_job_id": job_id,
            "feedback_round": retry_payload["feedback_round"],
            "payload": retry_payload,
        },
    )
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
    audio_path = None
    if item.get("review") and item["review"].get("audio_path"):
        audio_path = item["review"]["audio_path"]
    elif item.get("outputs") and item["outputs"].get("audio_path"):
        audio_path = item["outputs"]["audio_path"]
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