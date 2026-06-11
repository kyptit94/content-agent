from datetime import datetime
from uuid import uuid4

from fastapi import APIRouter
from fastapi import Header
from fastapi import HTTPException
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
    <title>AI Agent Điều Phối Nội Dung</title>
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
        <h1>AI Agent Điều Phối Nội Dung</h1>
        <p>Trợ lý này sẽ dẫn bạn đi từng bước để lên ý tưởng, chọn nguồn video và chạy job rõ ràng.</p>
        <div class="step-flow">
          <span id="chip1" class="step-chip">1. Xác thực</span>
          <span id="chip2" class="step-chip">2. Gợi ý chủ đề</span>
          <span id="chip3" class="step-chip">3. Chọn nguồn video</span>
          <span id="chip4" class="step-chip">4. Hoàn thiện job</span>
          <span id="chip5" class="step-chip">5. Theo dõi kết quả</span>
        </div>

        <div class="agent-box">
          <div class="agent-head">Hướng dẫn của AI Agent</div>
          <div id="agentMessage" class="agent-message">Bắt đầu từ Bước 1: nhập token rồi bấm Lưu token.</div>
          <div class="progress-track"><div id="progressFill" class="progress-fill"></div></div>
        </div>
      </div>

      <div class="grid">
        <div id="step1Card" class="card">
          <div class="step-title">
            <span class="badge">1</span>
            <h3>Xác thực Admin Token</h3>
          </div>
          <p class="hint">Nhập WEB_ADMIN_TOKEN để Agent có quyền gọi các API nội bộ.</p>
          <label>Admin token</label>
          <input id="token" placeholder="WEB_ADMIN_TOKEN" />
          <button onclick="saveToken()">Lưu token</button>
        </div>

        <div id="step2Card" class="card is-hidden">
          <div class="step-title">
            <span class="badge">2</span>
            <h3>Gợi ý và duyệt chủ đề</h3>
          </div>
          <p class="hint">Yêu cầu Agent gợi ý một chủ đề ngắn, cụ thể và dễ triển khai thành video. Bấm Đồng ý để chốt, bấm Từ chối để lấy chủ đề khác.</p>
          <div class="row">
            <div>
              <label>Loại nội dung</label>
              <select id="mode">
                <option value="sales">Bán sách</option>
                <option value="story">Kể chuyện</option>
              </select>
            </div>
            <div>
              <label>Ngôn ngữ</label>
              <input id="language" value="vi" />
            </div>
          </div>
          <button onclick="suggestTopic()">Gợi ý chủ đề</button>
          <label>Chủ đề</label>
          <textarea id="topic" rows="3" placeholder="Nhập chủ đề ở đây"></textarea>
          <div id="topicStatus" class="status">Chưa có chủ đề để duyệt.</div>
          <button onclick="approveTopic()">Đồng ý chủ đề này</button>
          <button class="secondary" onclick="rejectTopic()">Từ chối, gợi ý chủ đề khác</button>
        </div>

        <div id="step3Card" class="card is-hidden">
          <div class="step-title">
            <span class="badge">3</span>
            <h3>Chọn nguồn video</h3>
          </div>
          <p class="hint">Sau khi có chủ đề, chọn bạn muốn dùng video có sẵn hay để Agent tự tìm video stock trên internet.</p>
          <label>Nguồn video</label>
          <select id="videoSourceType" onchange="updateVideoSourceHint()">
            <option value="self">Video có sẵn của bạn</option>
            <option value="internet">Internet - tìm clip stock</option>
          </select>
          <div id="videoSourceHint" class="status">Nếu chọn video có sẵn, bước sau bạn chỉ cần dán đường dẫn file video đã có.</div>
          <button onclick="confirmVideoSource()">Tiếp tục</button>
        </div>

        <div id="step4Card" class="card is-hidden">
          <div class="step-title">
            <span class="badge">4</span>
            <h3>Hoàn thiện job và chạy</h3>
          </div>
          <p class="hint">Hoàn thiện đầu vào theo nguồn video bạn đã chọn, sau đó chạy job.</p>

          <div class="row">
            <div>
              <label>Giọng điệu</label>
              <input id="tone" value="thân thiện" />
            </div>
            <div>
              <label>Chat ID Telegram</label>
              <input id="telegramChatId" placeholder="không bắt buộc" />
            </div>
          </div>

          <div class="row">
            <div>
              <label>Đường dẫn video nguồn</label>
              <input id="videoPath" placeholder="/app/data/uploads/video.mp4" />
            </div>
            <div>
              <label>Từ khóa video (internet)</label>
              <input id="videoKeyword" placeholder="đọc sách, bàn học, thư viện..." />
            </div>
          </div>

          <div id="videoInputHint" class="status">Nếu chọn video có sẵn, hãy dán đường dẫn file video vào ô bên trái.</div>

          <div class="check-grid">
            <label class="check-item"><input id="createAudio" type="checkbox" /> Tạo audio</label>
            <label class="check-item"><input id="useGemini" type="checkbox" /> Gemini tinh chỉnh</label>
            <label class="check-item"><input id="notifyTelegram" type="checkbox" checked /> Báo Telegram</label>
            <label class="check-item"><input id="preserveQuality" type="checkbox" checked disabled /> Giữ chất lượng video</label>
          </div>

          <button onclick="createJob()">Chạy job</button>
          <div id="jobResult" class="status">Chưa tạo job.</div>
        </div>

        <div id="step5Card" class="card is-hidden">
          <div class="step-title">
            <span class="badge">5</span>
            <h3>Job gần đây</h3>
          </div>
          <p class="hint">Theo dõi trạng thái đang chờ, đang chạy, hoàn tất hoặc thất bại.</p>
          <button class="secondary" onclick="loadJobs()">Làm mới danh sách job</button>
          <pre id="jobs"></pre>
        </div>
      </div>
    </div>

    <script>
      const tokenInput = document.getElementById('token');
      const topicInput = document.getElementById('topic');
      const topicStatus = document.getElementById('topicStatus');
      const progressFill = document.getElementById('progressFill');
      const agentMessage = document.getElementById('agentMessage');

      tokenInput.value = localStorage.getItem('adminToken') || '';

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
        if (!stepState[4]) return 4;
        return 5;
      }

      function updateVideoSourceHint() {
        const sourceType = document.getElementById('videoSourceType').value;
        const sourceHint = document.getElementById('videoSourceHint');
        const inputHint = document.getElementById('videoInputHint');

        if (sourceType === 'self') {
          sourceHint.innerText = 'Bạn đã chọn video có sẵn. Bước sau chỉ cần dán đường dẫn file video.';
          inputHint.innerText = 'Bạn đang dùng video có sẵn. Hãy dán đường dẫn file video vào ô bên trái.';
        } else {
          sourceHint.innerText = 'Bạn đã chọn internet. Bước sau Agent sẽ dùng từ khóa để tìm clip stock.';
          inputHint.innerText = 'Bạn đang dùng internet. Chỉ cần nhập từ khóa video ở ô bên phải.';
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
          videoKeyword.placeholder = 'Không dùng khi chọn video có sẵn';
        } else {
          videoPath.disabled = true;
          videoPath.value = '';
          videoKeyword.disabled = false;
          videoKeyword.placeholder = 'đọc sách, bàn học, thư viện...';
        }
      }

      function updateGuide() {
        const currentStep = getCurrentStep();
        const completedCount = Object.values(stepState).filter(Boolean).length;
        progressFill.style.width = ((completedCount / 5) * 100) + '%';

        if (currentStep === 1) {
          agentMessage.innerText = 'Bước 1: lưu token để Agent có quyền gọi API.';
        } else if (currentStep === 2) {
          agentMessage.innerText = 'Bước 2: tạo hoặc nhập chủ đề bạn muốn làm nội dung.';
        } else if (currentStep === 3) {
          agentMessage.innerText = 'Bước 3: chọn bạn sẽ dùng video có sẵn hay video tìm trên internet.';
        } else if (currentStep === 4) {
          agentMessage.innerText = 'Bước 4: hoàn thiện đầu vào và bấm Chạy job.';
        } else {
          agentMessage.innerText = 'Bước 5: theo dõi job và làm mới để xem trạng thái mới nhất.';
        }

        setStepActive(currentStep);
        setCardVisible('step1Card', currentStep === 1);
        setCardVisible('step2Card', currentStep === 2);
        setCardVisible('step3Card', currentStep === 3);
        setCardVisible('step4Card', currentStep === 4);
        setCardVisible('step5Card', currentStep === 5);
        updateVideoSourceHint();
        syncStep4Inputs();
      }

      function getToken() {
        return localStorage.getItem('adminToken') || '';
      }

      function saveToken() {
        const value = tokenInput.value.trim();
        localStorage.setItem('adminToken', value);
        stepState[1] = Boolean(value);
        updateGuide();
        alert('Token đã được lưu');
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

      async function suggestTopic() {
        try {
          const body = {
            mode: document.getElementById('mode').value,
            language: document.getElementById('language').value,
          };
          const data = await api('/web/suggest-topic', {
            method: 'POST',
            headers: { 'content-type': 'application/json' },
            body: JSON.stringify(body),
          });
          topicInput.value = data.topic;
          stepState[2] = false;
          topicStatus.innerText = 'Chủ đề đã được gợi ý. Hãy đồng ý hoặc từ chối để Agent gợi ý lại.';
          updateGuide();
        } catch (error) {
          alert(error.message);
        }
      }

      function approveTopic() {
        const value = topicInput.value.trim();
        if (!value) {
          alert('Bạn chưa có chủ đề để duyệt. Hãy bấm Gợi ý chủ đề trước.');
          return;
        }
        stepState[2] = true;
        topicStatus.innerText = 'Chủ đề đã được duyệt.';
        updateGuide();
      }

      async function rejectTopic() {
        const sourceTopic = topicInput.value.trim();
        if (sourceTopic) {
          topicStatus.innerText = 'Đang gợi ý một chủ đề khác...';
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
          const body = {
            mode: document.getElementById('mode').value,
            topic: topicInput.value,
            language: document.getElementById('language').value,
            tone: document.getElementById('tone').value,
            use_gemini_refine: document.getElementById('useGemini').checked,
            create_audio: document.getElementById('createAudio').checked,
            create_video: true,
            video_source_type: document.getElementById('videoSourceType').value,
            user_video_path: document.getElementById('videoPath').value || null,
            video_keyword: document.getElementById('videoKeyword').value || null,
            notify_telegram: document.getElementById('notifyTelegram').checked,
            telegram_chat_id: document.getElementById('telegramChatId').value || null,
          };
          const data = await api('/web/jobs', {
            method: 'POST',
            headers: { 'content-type': 'application/json' },
            body: JSON.stringify(body),
          });
          stepState[4] = true;
          stepState[5] = true;
          document.getElementById('jobResult').innerText = 'Đã tạo job: ' + data.job_id;
          updateGuide();
          await loadJobs();
        } catch (error) {
          alert(error.message);
        }
      }

      async function loadJobs() {
        try {
          const data = await api('/web/jobs?limit=20');
          document.getElementById('jobs').innerText = JSON.stringify(data, null, 2);
        } catch (error) {
          alert(error.message);
        }
      }

      topicInput.addEventListener('input', (event) => {
        stepState[2] = false;
        topicStatus.innerText = event.target.value.trim() ? 'Nhập tay xong, bấm Đồng ý nếu muốn chốt chủ đề này.' : 'Chưa có chủ đề để duyệt.';
        updateGuide();
      });

      updateGuide();
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
