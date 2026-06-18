from fastapi.responses import HTMLResponse, FileResponse
from fastapi import FastAPI
import json, os
from datetime import datetime

app = FastAPI()

@app.get("/")
def root():
    return {"service": "content-agent-v2", "status": "running"}

@app.get("/web/jobs")
def list_jobs(limit: int = 20):
    import redis
    r = redis.from_url(os.getenv("REDIS_URL", "redis://redis:6379/0"), decode_responses=True)
    job_ids = r.lrange("jobs:recent", 0, limit-1)
    jobs = []
    for jid in job_ids:
        raw = r.get(f"job:{jid}")
        if raw:
            jobs.append(json.loads(raw))
    return {"items": jobs}

@app.get("/web/jobs/{job_id}/audio")
def get_audio(job_id: str):
    path = f"/app/data/outputs/{job_id}.mp3"
    if os.path.exists(path):
        return FileResponse(path, media_type="audio/mpeg")
    return {"error": "not found"}

@app.get("/web/jobs/{job_id}/video")
def get_video(job_id: str):
    path = f"/app/data/outputs/{job_id}.mp4"
    if os.path.exists(path):
        return FileResponse(path, media_type="video/mp4")
    return {"error": "not found"}

@app.get("/web", response_class=HTMLResponse)
def dashboard():
    return """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Content Agent v2</title>
<style>
:root{--bg:#0b0d14;--card:#141725;--text:#e4e8f1;--muted:#6b7280;--line:#1f2240;--accent:#7c3aed;--green:#10b981;--red:#ef4444;--warn:#f59e0b}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:system-ui,sans-serif;background:var(--bg);color:var(--text);padding:20px;max-width:800px;margin:0 auto}
h1{font-size:22px;margin-bottom:4px;background:linear-gradient(135deg,#a78bfa,#818cf8);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.sub{color:var(--muted);font-size:13px;margin-bottom:20px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px;margin-bottom:12px}
.card h3{margin-bottom:8px;color:var(--accent)}
.status-ok{color:var(--green)} .status-warn{color:var(--warn)} .status-err{color:var(--red)}
.job{border:1px solid var(--line);border-radius:8px;padding:10px;margin-bottom:8px;background:var(--bg)}
.job .title{font-weight:600}
.job .meta{color:var(--muted);font-size:12px;margin-top:4px}
.badge{padding:2px 8px;border-radius:99px;font-size:11px;font-weight:700}
.badge.completed{background:#10b98122;color:var(--green)}
.badge.running{background:#f59e0b22;color:var(--warn)}
.badge.failed{background:#ef444422;color:var(--red)}
audio{width:100%;max-width:400px;height:32px;margin-top:6px}
.refresh{color:var(--accent);cursor:pointer;font-size:12px;text-decoration:underline}
.vid-link{color:var(--accent);font-size:12px;text-decoration:underline;margin-top:4px;display:inline-block}
</style>
</head>
<body>
<h1>🤖 Content Agent v2</h1>
<p class="sub">Auto pipeline: Scrape → TTS → Image → Video → Publish</p>
<div class="card">
<h3>📊 System Status</h3>
<div id="status">Loading...</div>
</div>
<div class="card">
<h3>📋 Recent Jobs <span class="refresh" onclick="load()">(refresh)</span></h3>
<div id="jobs">Loading...</div>
</div>
<script>
async function load(){
try{
const r=await fetch('/web/jobs');
const d=await r.json();
const jobs=d.items||[];
document.getElementById('status').innerHTML='<span class="status-ok">✅ Running</span> · Jobs: '+jobs.length;
let html='';
for(const j of jobs){
html+='<div class="job"><span class="title">'+escapeHtml(j.title||'Untitled')+'</span> <span class="badge '+(j.status||'')+'">'+(j.status||'?')+'</span>';
if(j.outputs&&j.outputs.audio_path){
html+='<div><audio controls preload="metadata" src="/web/jobs/'+j.job_id+'/audio"></audio></div>';
}
html+='<div><a class="vid-link" href="/web/jobs/'+j.job_id+'/video" target="_blank">🎬 Download Video</a></div>';
html+='<div class="meta">ID: '+j.job_id+'</div></div>';
}
document.getElementById('jobs').innerHTML=html||'No jobs yet.';
}catch(e){document.getElementById('jobs').innerHTML='Error loading.';}
}
function escapeHtml(v){return String(v).replace(/&/g,'&').replace(/</g,'<').replace(/>/g,'>');}
load();setInterval(load,15000);
</script>
</body>
</html>"""