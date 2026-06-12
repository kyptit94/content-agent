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
from app.schemas import JobPayload
from app.services.llm_service import LLMService
from app.services.queue_service import QueueService

router = APIRouter(prefix="/web", tags=["web"])
queue = QueueService(redis_url=settings.redis_url, queue_name=settings.job_queue_name)
llm = LLMService()


class SuggestTopicRequest(BaseModel):
    mode: str = "sales"
    language: str = "en"


class CreateWebJobRequest(BaseModel):
    mode: str = "sales"
    topic: str = Field(min_length=3, max_length=500)
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
    return """
<!doctype html>
<html>
  <head>
    <meta charset=\"utf-8\" />
    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
    <title>AI Agent Content Shorts (EN)</title>
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
        max-width: 960px;
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
        grid-template-columns: 1fr;
        gap: 14px;
      }

      .card {
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
        margin-top: 10px;
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

      .jobs-list {
        display: grid;
        gap: 12px;
      }

      .job-card {
        border: 1px solid var(--line);
        border-radius: 14px;
        background: #f8fbff;
        padding: 12px;
      }

      .job-card.failed {
        background: #fff7f7;
        border-color: #ffd7d7;
      }

      .job-head {
        display: flex;
        justify-content: space-between;
        gap: 12px;
        align-items: start;
      }

      .job-title {
        font-weight: 700;
        margin: 0;
      }

      .job-meta {
        margin-top: 6px;
        color: var(--muted);
        font-size: 12px;
        line-height: 1.55;
      }

      .job-actions {
        display: flex;
        gap: 8px;
        flex-wrap: wrap;
        margin-top: 10px;
      }

      .mini-progress {
        margin-top: 10px;
      }

      .mini-progress-bar {
        height: 8px;
        border-radius: 999px;
        background: #e4ebf7;
        overflow: hidden;
      }

      .mini-progress-fill {
        height: 100%;
        background: linear-gradient(120deg, var(--accent), #149688);
      }

      .mini-progress-label {
        margin-top: 6px;
        color: var(--muted);
        font-size: 12px;
      }

      .modal-backdrop {
        position: fixed;
        inset: 0;
        background: rgba(10, 16, 31, 0.58);
        display: none;
        align-items: center;
        justify-content: center;
        padding: 20px;
        z-index: 50;
      }

      .modal-backdrop.open {
        display: flex;
      }

      .modal {
        width: min(860px, 100%);
        max-height: 90vh;
        overflow: auto;
        background: #fff;
        border-radius: 18px;
        border: 1px solid #dbe3f2;
        box-shadow: 0 30px 80px rgba(7, 18, 40, 0.35);
        padding: 16px;
      }

      .modal-head {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 12px;
      }

      .modal-title {
        margin: 0;
        font-size: 18px;
        font-weight: 800;
      }

      .modal-close {
        width: auto;
        margin-top: 0;
        background: #eff3fa;
        color: #203050;
        border: 1px solid #d5dfef;
      }

      .modal-body {
        margin-top: 12px;
      }

      .modal-body pre {
        min-height: 320px;
      }

      .result-actions {
        display: flex;
        gap: 8px;
        flex-wrap: wrap;
        margin-top: 10px;
      }

      .hero-actions {
        margin-top: 12px;
        display: flex;
        gap: 8px;
        flex-wrap: wrap;
      }

      .job-error {
        margin-top: 10px;
        color: #9a3412;
        background: #fff1ea;
        border: 1px solid #ffd7c2;
        border-radius: 10px;
        padding: 8px 10px;
        font-size: 12px;
        white-space: pre-wrap;
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

      .is-hidden { display: none; }

      @media (max-width: 860px) {
        .row, .check-grid { grid-template-columns: 1fr; }
      }
    </style>
  </head>
  <body>
    <div class="wrap">
      <div class="hero">
        <h1>AI Agent Content Shorts (EN)</h1>
        <p>Generate short videos with Kokoro emotional TTS + Edge TTS fallback.</p>
        <div class="step-flow">
          <span id="chip1" class="step-chip">1. Auth</span>
          <span id="chip2" class="step-chip">2. Topic</span>
          <span id="chip3" class="step-chip">3. Video Source</span>
          <span id="chip4" class="step-chip">4. Run</span>
        </div>

        <div class="agent-box">
          <div class="agent-head">AI Guide</div>
          <div id="agentMessage" class="agent-message">Step 1: Save your admin token to access APIs.</div>
          <div class="progress-track"><div id="progressFill" class="progress-fill"></div></div>
          <div class="hero-actions">
            <button class="secondary" onclick="openResultsModal()">View Results</button>
          </div>
        </div>
      </div>

      <div class="grid">
        <div id="step1Card" class="card">
          <div class="step-title">
            <span class="badge">1</span>
            <h3>Admin Token</h3>
          </div>
          <p class="hint">Enter WEB_ADMIN_TOKEN to allow the Agent to call internal APIs.</p>
          <label>Admin token</label>
          <input id="token" placeholder="WEB_ADMIN_TOKEN" />
          <button onclick="saveToken()">Save token</button>
        </div>

        <div id="step2Card" class="card is-hidden">
          <div class="step-title">
            <span class="badge">2</span>
            <h3>Suggest & Review Topic</h3>
          </div>
          <p class="hint">Ask the Agent to suggest a topic. Approve or reject to get another.</p>
          <div class="row">
            <div>
              <label>Content mode</label>
              <select id="mode">
                <option value="sales">Book Sales</option>
                <option value="story">Storytelling</option>
              </select>
            </div>
            <div>
              <label>Language</label>
              <input id="language" value="en" />
            </div>
          </div>
          <button onclick="suggestTopic()">Suggest Topic</button>
          <label>Topic</label>
          <textarea id="topic" rows="3" placeholder="Enter topic here"></textarea>
          <div id="topicStatus" class="status">No topic approved yet.</div>
          <button onclick="approveTopic()">Approve this topic</button>
          <button class="secondary" onclick="rejectTopic()">Reject, suggest another</button>
        </div>

        <div id="step3Card" class="card is-hidden">
          <div class="step-title">
            <span class="badge">3</span>
            <h3>Video Source</h3>
          </div>
          <p class="hint">Choose whether to use your own video or let the Agent fetch stock footage.</p>
          <label>Video source</label>
          <select id="videoSourceType" onchange="updateVideoSourceHint()">
            <option value="self">Your own video</option>
            <option value="internet">Internet - stock clip</option>
          </select>
          <div id="videoSourceHint" class="status">If you choose your own video, paste the file path in step 4.</div>
          <button onclick="confirmVideoSource()">Continue</button>
        </div>

        <div id="step4Card" class="card is-hidden">
          <div class="step-title">
            <span class="badge">4</span>
            <h3>Finalize & Run</h3>
          </div>
          <p class="hint">Complete the inputs based on your chosen video source, then run the job.</p>

          <div class="row">
            <div>
              <label>Tone</label>
              <input id="tone" value="friendly" />
            </div>
            <div>
              <label>Telegram Chat ID</label>
              <input id="telegramChatId" placeholder="optional" />
            </div>
          </div>

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
              <label>Source video path</label>
              <input id="videoPath" placeholder="/app/data/uploads/video.mp4" />
            </div>
            <div></div>
          </div>

          <div class="row">
            <div>
              <label>Video keyword (internet)</label>
              <input id="videoKeyword" placeholder="reading, library, books..." />
            </div>
            <div></div>
          </div>

          <div id="videoInputHint" class="status">If using your own video, paste the file path above.</div>

          <div class="check-grid">
            <label class="check-item"><input id="createAudio" type="checkbox" checked /> Create audio</label>
            <label class="check-item"><input id="useGemini" type="checkbox" /> Gemini refine</label>
            <label class="check-item"><input id="notifyTelegram" type="checkbox" checked /> Notify Telegram</label>
            <label class="check-item"><input id="preserveQuality" type="checkbox" checked disabled /> Preserve quality</label>
          </div>

          <button onclick="createJob()">Run job</button>
          <div id="jobResult" class="status">No job created yet.</div>
          <div id="jobResultActions" class="result-actions"></div>
        </div>

      </div>
    </div>

    <div id="resultsModalBackdrop" class="modal-backdrop" onclick="if (event.target === this) closeResultsModal()">
      <div class="modal">
        <div class="modal-head">
          <h3 class="modal-title">Job Results</h3>
          <button class="modal-close" onclick="closeResultsModal()">Close</button>
        </div>
        <div class="modal-body">
          <button class="secondary" onclick="loadJobs()">Refresh list</button>
          <div id="jobsList" class="jobs-list"></div>
        </div>
      </div>
    </div>

    <div id="jobModalBackdrop" class="modal-backdrop" onclick="if (event.target === this) closeJobModal()">
      <div class="modal">
        <div class="modal-head">
          <h3 id="jobModalTitle" class="modal-title">Job Detail</h3>
          <button class="modal-close" onclick="closeJobModal()">Close</button>
        </div>
        <div id="jobModalBody" class="modal-body"></div>
      </div>
    </div>

    <script>
      const tokenInput = document.getElementById('token');
      const topicInput = document.getElementById('topic');
      const topicStatus = document.getElementById('topicStatus');
      const progressFill = document.getElementById('progressFill');
      const agentMessage = document.getElementById('agentMessage');
      const lastJobKey = 'lastJobId';
      let activeVideoObjectUrl = '';

      tokenInput.value = localStorage.getItem('adminToken') || '';

      const stepState = {
        1: Boolean(tokenInput.value.trim()),
        2: false,
        3: false,
        4: false,
      };

      function setStepActive(stepNumber) {
        for (let i = 1; i <= 4; i++) {
          const chip = document.getElementById('chip' + i);
          chip.classList.remove('active');
          chip.classList.remove('done');
          if (stepState[i]) {
            chip.classList.add('done');
          }
        }
        document.getElementById('chip' + stepNumber).classList.add('active');
      }

      function setCardVisible(cardId, visible) {
        const card = document.getElementById(cardId);
        if (!card) return;
        card.classList.toggle('is-hidden', !visible);
      }

      function getCurrentStep() {
        if (!stepState[1]) return 1;
        if (!stepState[2]) return 2;
        if (!stepState[3]) return 3;
        return 4;
      }

      function updateVideoSourceHint() {
        const sourceType = document.getElementById('videoSourceType').value;
        const sourceHint = document.getElementById('videoSourceHint');
        const inputHint = document.getElementById('videoInputHint');

        if (sourceType === 'self') {
          sourceHint.innerText = 'You chose your own video. Paste the file path in step 4.';
          inputHint.innerText = 'Using your own video. Paste the file path above.';
        } else {
          sourceHint.innerText = 'You chose internet. The Agent will use keywords to find stock clips.';
          inputHint.innerText = 'Using internet. Just enter a video keyword above.';
        }
      }

      function syncStep4Inputs() {
        const sourceType = document.getElementById('videoSourceType').value;
        const videoPath = document.getElementById('videoPath');
        const videoKeyword = document.getElementById('videoKeyword');

        if (sourceType === 'self') {
          videoPath.disabled = false;
          videoKeyword.disabled = true;
          videoKeyword.value = '';
          videoKeyword.placeholder = 'Not used when using own video';
        } else {
          videoPath.disabled = true;
          videoPath.value = '';
          videoKeyword.disabled = false;
          videoKeyword.placeholder = 'reading, library, books...';
        }
      }

      function updateGuide() {
        const currentStep = getCurrentStep();
        const completedCount = Object.values(stepState).filter(Boolean).length;
        progressFill.style.width = ((completedCount / 4) * 100) + '%';

        const createAudioChecked = document.getElementById('createAudio').checked;
        const voiceSampleValue = document.getElementById('voiceSampleFilename').value.trim();
        if (createAudioChecked && !voiceSampleValue) {
          updateVoiceSampleHint('No voice sample selected. Kokoro (EN emotional TTS) or Edge TTS will be used.', false);
        }

        if (currentStep === 1) {
          agentMessage.innerText = 'Step 1: Save your admin token.';
        } else if (currentStep === 2) {
          agentMessage.innerText = 'Step 2: Create or enter a topic for your content.';
        } else if (currentStep === 3) {
          agentMessage.innerText = 'Step 3: Choose your video source.';
        } else if (currentStep === 4) {
          agentMessage.innerText = 'Step 4: Finalize inputs and run the job.';
        }

        setStepActive(currentStep);
        setCardVisible('step1Card', currentStep === 1);
        setCardVisible('step2Card', currentStep === 2);
        setCardVisible('step3Card', currentStep === 3);
        setCardVisible('step4Card', currentStep === 4);
        updateVideoSourceHint();
        syncStep4Inputs();
      }

      function openResultsModal() {
        document.getElementById('resultsModalBackdrop').classList.add('open');
        loadJobs();
      }

      function closeResultsModal() {
        document.getElementById('resultsModalBackdrop').classList.remove('open');
      }

      function getToken() {
        return localStorage.getItem('adminToken') || '';
      }

      function saveToken() {
        const value = tokenInput.value.trim();
        localStorage.setItem('adminToken', value);
        stepState[1] = Boolean(value);
        updateGuide();
        alert('Token saved');
      }

      function setLatestJob(jobId) {
        localStorage.setItem(lastJobKey, jobId);
        renderLatestJobAction(jobId);
      }

      function getLatestJob() {
        return localStorage.getItem(lastJobKey) || '';
      }

      function renderLatestJobAction(jobId) {
        const container = document.getElementById('jobResultActions');
        if (!jobId) {
          container.innerHTML = '';
          return;
        }
        container.innerHTML = `
          <button class="secondary" onclick="previewJob('${escapeHtml(jobId)}')">Preview video</button>
          <button class="secondary" onclick="viewJob('${escapeHtml(jobId)}')">View details</button>
        `;
      }

      function updateVoiceSampleHint(message, isWarning = false) {
        const hint = document.getElementById('voiceSampleHint');
        hint.innerText = message;
        hint.style.background = isWarning ? '#fff1ea' : '#f2f6ff';
        hint.style.borderColor = isWarning ? '#ffd7c2' : '#d8e2f5';
        hint.style.color = isWarning ? '#9a3412' : '#294268';
      }

      function updateVoiceSourceModeUI() {
        const mode = document.getElementById('voiceSourceMode').value;
        document.getElementById('voiceLibraryPanel').classList.toggle('is-hidden', mode !== 'library');
        document.getElementById('voiceUploadPanel').classList.toggle('is-hidden', mode !== 'upload');
      }

      function pickVoiceFromLibrary() {
        const selected = document.getElementById('voiceLibrarySelect').value;
        if (!selected) {
          updateVoiceSampleHint('Audio library is empty. Upload a file first.', true);
          return;
        }
        document.getElementById('voiceSampleFilename').value = selected;
        updateVoiceSampleHint(`Voice sample selected: ${selected}`);
      }

      async function uploadVoiceSample() {
        const fileInput = document.getElementById('voiceUploadFile');
        const file = fileInput.files && fileInput.files[0];
        if (!file) {
          updateVoiceSampleHint('No file selected for upload.', true);
          return;
        }

        const formData = new FormData();
        formData.append('file', file);

        try {
          const response = await fetch('/web/voice-samples/upload', {
            method: 'POST',
            headers: { 'x-admin-token': getToken() },
            body: formData,
          });
          if (!response.ok) {
            throw new Error(await response.text());
          }
          const data = await response.json();
          document.getElementById('voiceSampleFilename').value = data.filename;
          fileInput.value = '';
          await loadVoiceSamples();
          updateVoiceSampleHint(`Uploaded: ${data.filename}`);
        } catch (error) {
          updateVoiceSampleHint('Upload failed: ' + error.message, true);
        }
      }

      async function loadVoiceSamples() {
        try {
          const data = await api('/web/voice-samples');
          const samples = data.items || [];
          const datalist = document.getElementById('voiceSamples');
          const voiceInput = document.getElementById('voiceSampleFilename');
          const voiceSelect = document.getElementById('voiceLibrarySelect');
          datalist.innerHTML = samples.map((item) => `<option value="${escapeHtml(item)}"></option>`).join('');
          voiceSelect.innerHTML = samples.map((item) => `<option value="${escapeHtml(item)}">${escapeHtml(item)}</option>`).join('');
          if (samples.length && !voiceInput.value.trim()) {
            voiceInput.value = samples[0];
          }
          if (samples.length) {
            updateVoiceSampleHint(`${samples.length} voice sample(s) available.`);
          } else {
            updateVoiceSampleHint('No voice samples. Will use Kokoro (EN) or Edge TTS.', false);
          }
        } catch (error) {
          updateVoiceSampleHint('Could not load voice samples: ' + error.message, true);
        }
      }

      function escapeHtml(value) {
        return String(value)
          .replaceAll('&', '&')
          .replaceAll('<', '<')
          .replaceAll('>', '>')
          .replaceAll('"', '"')
          .replaceAll("'", '&#39;');
      }

      async function api(url, options = {}) {
        const headers = options.headers || {};
        headers['x-admin-token'] = getToken();
        options.headers = headers;
        const response = await fetch(url, options);
        if (!response.ok) {
          throw new Error(await response.text());
        }
        return await response.json();
      }

      async function fetchVideoBlob(jobId) {
        const response = await fetch(`/web/jobs/${jobId}/video`, {
          headers: { 'x-admin-token': getToken() },
        });
        if (!response.ok) {
          throw new Error(await response.text());
        }
        return await response.blob();
      }

      function renderJobs(items) {
        const container = document.getElementById('jobsList');
        if (!items.length) {
          container.innerHTML = '<div class="status">No jobs yet.</div>';
          return;
        }

        const statusLabels = {
          queued: 'Queued',
          running: 'Running',
          review_pending: 'Review',
          completed: 'Completed',
          failed: 'Failed',
        };

        const stageLabels = {
          generating_content: 'Writing content',
          generating_audio: 'Generating audio',
          preparing_video: 'Preparing video',
          composing_video: 'Composing video + audio',
          publishing: 'Publishing',
          completed: 'Completed',
        };

        container.innerHTML = items.map((item) => {
          const status = item.status || 'unknown';
          const title = escapeHtml(item.topic || 'No topic');
          const jobId = escapeHtml(item.job_id || '');
          const stageLabel = escapeHtml(stageLabels[item.current_stage] || item.stage_detail || '');
          const progressPercent = Number(item.progress_percent || 0);
          const metaLines = [
            `Job ID: ${jobId}`,
            `Status: ${escapeHtml(statusLabels[status] || status)}`,
            `Mode: ${escapeHtml(item.mode || '')}`,
            item.queue_position ? `Queue position: ${escapeHtml(String(item.queue_position))}` : '',
            item.created_at ? `Created: ${escapeHtml(item.created_at)}` : '',
            item.started_at ? `Started: ${escapeHtml(item.started_at)}` : '',
            item.completed_at ? `Completed: ${escapeHtml(item.completed_at)}` : '',
            item.failed_at ? `Failed: ${escapeHtml(item.failed_at)}` : '',
          ].filter(Boolean).join('<br/>');

          const errorBlock = item.error ? `<div class="job-error">${escapeHtml(item.error)}</div>` : '';
          const progressBlock = status === 'running' || status === 'completed'
            ? `
              <div class="mini-progress">
                <div class="mini-progress-bar"><div class="mini-progress-fill" style="width:${Math.max(0, Math.min(progressPercent, 100))}%"></div></div>
                <div class="mini-progress-label">${stageLabel || 'Processing'}${progressPercent ? ` \u2022 ${progressPercent}%` : ''}</div>
              </div>
            `
            : status === 'queued' && item.queue_position
              ? `<div class="mini-progress-label">Job waiting in queue, position #${escapeHtml(String(item.queue_position))}.</div>`
              : '';
          const approveButton = status === 'review_pending'
            ? `<button onclick="approveJob('${jobId}')">Approve & Compose Video</button>`
            : '';
          const retryButton = status === 'failed'
            ? `<button class="secondary" onclick="retryJob('${jobId}')">Retry</button>`
            : '';
          const viewButton = `<button class="secondary" onclick="viewJob('${jobId}')">View</button>`;
          const deleteButton = `<button class="secondary" onclick="deleteJob('${jobId}')">Delete</button>`;

          // Show content + audio for review_pending jobs
          const reviewContent = status === 'review_pending' && item.review
            ? `<div style="margin-top:10px;max-height:200px;overflow:auto;background:#fff;border:1px solid #dde3ef;padding:8px;border-radius:8px;font-size:12px;white-space:pre-wrap">${escapeHtml(item.review.content || '')}</div>`
            : '';
          const reviewAudio = status === 'review_pending' && item.review && item.review.audio_path
            ? `<div style="margin-top:6px"><audio controls preload="auto" style="width:100%" src="/web/jobs/${jobId}/audio?token=${encodeURIComponent(getToken())}"></audio></div>`
            : '';

          return `
            <div class="job-card ${status === 'failed' ? 'failed' : ''}">
              <div class="job-head">
                <div>
                  <p class="job-title">${title}</p>
                  <div class="job-meta">${metaLines}</div>
                </div>
                <div class="status">${escapeHtml(statusLabels[status] || status)}</div>
              </div>
              ${progressBlock}
              ${errorBlock}
              ${reviewContent}
              ${reviewAudio}
              <div class="job-actions">
                ${approveButton}
                ${viewButton}
                ${deleteButton}
                ${retryButton}
              </div>
            </div>
          `;
        }).join('');
      }

      function openJobModal(job, videoObjectUrl = '') {
        if (activeVideoObjectUrl) {
          URL.revokeObjectURL(activeVideoObjectUrl);
          activeVideoObjectUrl = '';
        }
        if (videoObjectUrl) {
          activeVideoObjectUrl = videoObjectUrl;
        }

        const backdrop = document.getElementById('jobModalBackdrop');
        const title = document.getElementById('jobModalTitle');
        const body = document.getElementById('jobModalBody');
        title.innerText = `Job ${job.job_id || ''}`;
        const hasVideo = Boolean(job.outputs && job.outputs.video_path);
        const videoBlock = hasVideo
          ? `<video controls autoplay playsinline style="width:100%;max-height:60vh;border-radius:12px;background:#000" src="${escapeHtml(videoObjectUrl || '')}"></video>`
          : '<div class="status">Job has no video yet. Wait for completion or check for errors.</div>';
        body.innerHTML = `
          ${videoBlock}
          <div style="margin-top:12px"><pre>${escapeHtml(JSON.stringify(job, null, 2))}</pre></div>
        `;
        backdrop.classList.add('open');
      }

      function closeJobModal() {
        if (activeVideoObjectUrl) {
          URL.revokeObjectURL(activeVideoObjectUrl);
          activeVideoObjectUrl = '';
        }
        document.getElementById('jobModalBackdrop').classList.remove('open');
      }

      async function viewJob(jobId) {
        try {
          const data = await api(`/web/jobs/${jobId}`);
          let videoObjectUrl = '';
          if (data.outputs && data.outputs.video_path) {
            const blob = await fetchVideoBlob(jobId);
            videoObjectUrl = URL.createObjectURL(blob);
          }
          openJobModal(data, videoObjectUrl);
        } catch (error) {
          alert(error.message);
        }
      }

      async function previewJob(jobId) {
        return await viewJob(jobId);
      }

      async function deleteJob(jobId) {
        if (!confirm('Delete this job?')) {
          return;
        }
        try {
          await api(`/web/jobs/${jobId}`, { method: 'DELETE' });
          document.getElementById('jobResult').innerText = 'Deleted job: ' + jobId;
          await loadJobs();
        } catch (error) {
          alert(error.message);
        }
      }

      async function retryJob(jobId) {
        try {
          const data = await api(`/web/jobs/${jobId}/retry`, {
            method: 'POST',
          });
          document.getElementById('jobResult').innerText = 'Retry job created: ' + data.job_id;
          await loadJobs();
        } catch (error) {
          alert(error.message);
        }
      }

      async function approveJob(jobId) {
        try {
          const data = await api(`/web/jobs/${jobId}/approve`, {
            method: 'POST',
          });
          document.getElementById('jobResult').innerText = 'Approved job: ' + data.job_id + ' — composing video...';
          await loadJobs();
        } catch (error) {
          alert(error.message);
        }
      }

      async function suggestTopic() {
        try {
          const body = {
            mode: document.getElementById('mode').value,
            language: document.getElementById('language').value || 'en',
          };
          const data = await api('/web/suggest-topic', {
            method: 'POST',
            headers: { 'content-type': 'application/json' },
            body: JSON.stringify(body),
          });
          topicInput.value = data.topic;
          stepState[2] = false;
          topicStatus.innerText = 'Topic suggested. Approve or reject.';
          updateGuide();
        } catch (error) {
          alert(error.message);
        }
      }

      function approveTopic() {
        const value = topicInput.value.trim();
        if (!value) {
          alert('No topic to approve. Click Suggest Topic first.');
          return;
        }
        stepState[2] = true;
        topicStatus.innerText = 'Topic approved.';
        updateGuide();
      }

      async function rejectTopic() {
        const sourceTopic = topicInput.value.trim();
        if (sourceTopic) {
          topicStatus.innerText = 'Suggesting another topic...';
        }
        stepState[2] = false;
        await suggestTopic();
      }

      function confirmVideoSource() {
        stepState[3] = true;
        updateGuide();
      }

      async function createJob() {
        try {
          const createAudio = document.getElementById('createAudio').checked;

          const body = {
            mode: document.getElementById('mode').value,
            topic: topicInput.value,
            language: document.getElementById('language').value || 'en',
            tone: document.getElementById('tone').value || 'friendly',
            use_gemini_refine: document.getElementById('useGemini').checked,
            create_audio: createAudio,
            create_video: true,
            video_source_type: document.getElementById('videoSourceType').value,
            user_video_path: document.getElementById('videoPath').value || null,
            video_keyword: document.getElementById('videoKeyword').value || null,
            kokoro_voice: document.getElementById('kokoroVoice').value || 'af_heart',
            notify_telegram: document.getElementById('notifyTelegram').checked,
            telegram_chat_id: document.getElementById('telegramChatId').value || null,
          };
          const data = await api('/web/jobs', {
            method: 'POST',
            headers: { 'content-type': 'application/json' },
            body: JSON.stringify(body),
          });
          stepState[4] = true;
          document.getElementById('jobResult').innerText = 'Job created: ' + data.job_id;
          setLatestJob(data.job_id);
          updateGuide();
          await loadJobs();
        } catch (error) {
          alert(error.message);
        }
      }

      async function loadJobs() {
        try {
          const data = await api('/web/jobs?limit=20');
          renderJobs(data.items || []);
        } catch (error) {
          alert(error.message);
        }
      }

      topicInput.addEventListener('input', (event) => {
        stepState[2] = false;
        topicStatus.innerText = event.target.value.trim() ? 'Manually entered. Click Approve if you want to use this topic.' : 'No topic to approve.';
        updateGuide();
      });

      updateGuide();
      renderLatestJobAction(getLatestJob());
      updateVoiceSourceModeUI();
      loadVoiceSamples();
      loadJobs();
    </script>
  </body>
</html>
"""


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
            "topic": body.topic,
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
            "mode": item.get("mode", "sales"),
            "topic": item.get("topic", ""),
            "language": item.get("language", "en"),
            "tone": item.get("tone", "friendly"),
            "use_gemini_refine": item.get("use_gemini_refine", False),
            "create_audio": item.get("create_audio", False),
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
            "topic": retry_payload.get("topic"),
            "mode": retry_payload.get("mode"),
            "queued_at": datetime.utcnow().isoformat(),
            "revision_of_job_id": job_id,
            "feedback_round": retry_payload["feedback_round"],
            "payload": retry_payload,
        },
    )
    return {"job_id": retry_payload["job_id"], "status": "queued"}
@router.get("/jobs/{job_id}/video")
def get_job_video(job_id: str, x_admin_token: str | None = Header(default=None)) -> FileResponse:
    _check_token(x_admin_token)

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
def get_job_audio(
    job_id: str,
    token: str | None = None,
    x_admin_token: str | None = Header(default=None),
) -> FileResponse:
    # Audio tag in browser cannot send headers — accept token via query param as fallback
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
