#!/bin/bash
# ============================================================
# Content Agent v3 — Single Bash Script Pipeline
# Scrape → TTS → Image → Video Compose (MC PIP) → Publish
# Chạy trực tiếp trên server, tận dụng GPU GTX 1070
# ============================================================
set -e

# ---- CONFIG ----
OLLAMA_HOST="${OLLAMA_HOST:-localhost:11434}"
MODEL="${MODEL:-mistral:7b}"
OUTPUT_DIR="${OUTPUT_DIR:-./data/outputs}"
MC_VIDEO="${MC_VIDEO:-./data/mc_video.mp4}"
MC_SCALE="${MC_SCALE:-0.7}"
PEXELS_KEY="${PEXELS_KEY:-}"
PIXABAY_KEY="${PIXABAY_KEY:-}"
TELEGRAM_BOT="${TELEGRAM_BOT:-}"
TELEGRAM_CHAT="${TELEGRAM_CHAT:-}"
SLEEP_MIN="${SLEEP_MIN:-5}"

mkdir -p "$OUTPUT_DIR"

# ============================================================
# 1. SCRAPE TRUYỆN
# ============================================================
scrape() {
    local topic="${1:-a haunted house story}"
    echo "[SCRAPE] Topic: $topic" >&2
    
    local prompt="Write a short, engaging horror story (200-400 words) about: $topic. Output ONLY the story, no title, no commentary."
    
    local content=$(curl -s "http://${OLLAMA_HOST}/api/generate" \
        -d "{\"model\":\"${MODEL}\",\"prompt\":$(echo "$prompt" | python3 -c 'import sys,json; print(json.dumps(sys.stdin.read()))'),\"stream\":false,\"options\":{\"temperature\":0.9,\"num_predict\":800}}" \
        2>/dev/null | python3 -c 'import sys,json; print(json.load(sys.stdin).get("response",""))' 2>/dev/null)
    
    if [ -z "$content" ]; then
        echo "[SCRAPE] FAILED" >&2
        return 1
    fi
    
    echo "[SCRAPE] Words: $(echo "$content" | wc -w)" >&2
    echo "$content"
}

# ============================================================
# 2. TTS (gTTS)
# ============================================================
tts() {
    local text="$1"
    local job_id="$2"
    local output="${OUTPUT_DIR}/${job_id}.mp3"
    
    echo "[TTS] Generating audio..."
    python3 -c "
from gtts import gTTS
tts = gTTS(text='''${text}'''[:3000], lang='en', slow=False)
tts.save('${output}')
" 2>/dev/null
    
    if [ -f "$output" ] && [ -s "$output" ]; then
        echo "[TTS] Done: $output ($(du -h "$output" | cut -f1))"
        echo "$output"
    else
        echo "[TTS] FAILED"
        return 1
    fi
}

# ============================================================
# 3. ẢNH NỀN
# ============================================================
image() {
    local job_id="$1"
    local story="$2"
    local output="${OUTPUT_DIR}/${job_id}.jpg"
    
    # Try Pexels first
    if [ -n "$PEXELS_KEY" ]; then
        local keywords=$(echo "$story" | head -1 | tr ' ' ',' | cut -c1-50)
        local url=$(curl -s "https://api.pexels.com/v1/search?query=${keywords}&per_page=1&orientation=portrait" \
            -H "Authorization: ${PEXELS_KEY}" 2>/dev/null | \
            python3 -c 'import sys,json; hits=json.load(sys.stdin).get("photos",[]); print(hits[0]["src"]["portrait"]) if hits else print("")' 2>/dev/null)
        if [ -n "$url" ]; then
            curl -s "$url" -o "$output" 2>/dev/null
            if [ -f "$output" ] && [ -s "$output" ]; then
                echo "[IMAGE] Downloaded from Pexels: $output"
                echo "$output"
                return 0
            fi
        fi
    fi
    
    # Fallback: solid color image
    echo "[IMAGE] Creating fallback image..."
    ffmpeg -y -f lavfi -i "color=c=0x1a1a2e:s=1080x1920:d=1,drawtext=text='StoryTime':fontcolor=white:fontsize=60:x=(w-text_w)/2:y=(h-text_h)/2" \
        -frames:v 1 "$output" 2>/dev/null
    echo "[IMAGE] Fallback: $output"
    echo "$output"
}

# ============================================================
# 4. INTRO GENERATION (MC full screen + text + AI voice)
# ============================================================
create_intro() {
    local job_id="$1"
    local mc="${2:-}"
    local intro_text="${3:-Learn English with Stories}"
    local intro_audio="${OUTPUT_DIR}/${job_id}_intro.mp3"
    local intro_video="${OUTPUT_DIR}/${job_id}_intro.mp4"
    
    # Generate intro TTS (~3 seconds)
    echo "[INTRO] Generating intro voice..."
    python3 -c "
from gtts import gTTS
tts = gTTS(text='${intro_text}', lang='en', slow=False)
tts.save('${intro_audio}')
" 2>/dev/null
    
    if [ ! -f "$intro_audio" ] || [ ! -s "$intro_audio" ]; then
        echo "[INTRO] TTS failed"
        return 1
    fi
    
    local intro_dur=$(ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 "$intro_audio" 2>/dev/null || echo 3)
    
    # Compose intro video: MC full screen + text overlay
    if [ -n "$mc" ] && [ -f "$mc" ]; then
        echo "[INTRO] Composing ${intro_dur}s intro with MC full screen..."
        ffmpeg -y -hwaccel auto -stream_loop -1 -i "$mc" -i "$intro_audio" \
            -filter_complex "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,fps=30,drawtext=text='Learn English with Stories':fontcolor=white:fontsize=64:box=1:boxcolor=black@0.5:boxborderw=10:x=(w-text_w)/2:y=h/3[v]" \
            -map "[v]" -map 1:a \
            -t "$intro_dur" \
            -c:v h264_nvenc -preset p1 -qp 28 -c:a aac -b:a 192k \
            "$intro_video" 2>/dev/null
    else
        # No MC video — just text on black background + TTS
        ffmpeg -y -f lavfi -i "color=c=0x1a1a2e:s=1080x1920:d=${intro_dur},drawtext=text='Learn English with Stories':fontcolor=white:fontsize=64:box=1:boxcolor=black@0.5:boxborderw=10:x=(w-text_w)/2:y=h/3" \
            -i "$intro_audio" -map 0:v -map 1:a \
            -c:v h264_nvenc -preset p1 -qp 28 -c:a aac -b:a 192k \
            "$intro_video" 2>/dev/null
    fi
    
    if [ -f "$intro_video" ] && [ -s "$intro_video" ]; then
        echo "[INTRO] Done: $intro_video ($(du -h "$intro_video" | cut -f1))"
        echo "$intro_video"
    else
        echo "[INTRO] FAILED"
        return 1
    fi
}

# ============================================================
# 5. VIDEO COMPOSE (Image BG + MC PIP + Story Audio)
# ============================================================
compose_story() {
    local job_id="$1"
    local bg_image="$2"
    local audio="$3"
    local mc="${4:-}"
    local output="${OUTPUT_DIR}/${job_id}_story.mp4"
    
    local duration=$(ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 "$audio" 2>/dev/null || echo 60)
    
    local inputs=(-y -hwaccel auto -loop 1 -i "$bg_image")
    local filters="[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,zoompan=z='min(zoom+0.0002,1.04)':d=1:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1080x1920:fps=30[vbg]"
    local map_v="[vout]"
    local map_a="1:a"
    local input_count=1
    
    if [ -n "$mc" ] && [ -f "$mc" ]; then
        inputs+=(-stream_loop -1 -i "$mc")
        filters+=";[${input_count}:v]scale=w=iw*0.35:h=ih*0.35,setsar=1,format=rgba,colorchannelmixer=aa=0.9[vpip]"
        filters+=";[vbg][vpip]overlay=10:H-h-10[vout]"
        map_a="2:a"
        input_count=2
    else
        filters+=";[vbg]null[vout]"
    fi
    
    inputs+=(-i "$audio")
    
    echo "[STORY] Rendering ${duration}s video..."
    ffmpeg "${inputs[@]}" \
        -filter_complex "$filters" \
        -map "$map_v" -map "$map_a" \
        -t "$duration" \
        -c:v h264_nvenc -preset p1 -qp 28 \
        -c:a aac -b:a 192k \
        "$output" 2>/dev/null
    
    if [ -f "$output" ] && [ -s "$output" ]; then
        echo "[STORY] Done: $output ($(du -h "$output" | cut -f1))"
        echo "$output"
    else
        echo "[STORY] FAILED"
        return 1
    fi
}

# ============================================================
# 6. CONCAT INTRO + STORY
# ============================================================
concat_intro_story() {
    local job_id="$1"
    local intro_video="$2"
    local story_video="$3"
    local output="${OUTPUT_DIR}/${job_id}.mp4"
    
    local concat_list="${OUTPUT_DIR}/${job_id}_concat.txt"
    echo "file '${intro_video}'" > "$concat_list"
    echo "file '${story_video}'" >> "$concat_list"
    
    echo "[CONCAT] Merging intro + story..."
    ffmpeg -y -f concat -safe 0 -i "$concat_list" -c copy "$output" 2>/dev/null
    
    if [ -f "$output" ] && [ -s "$output" ]; then
        echo "[CONCAT] Done: $output ($(du -h "$output" | cut -f1))"
        echo "$output"
    else
        echo "[CONCAT] FAILED"
        return 1
    fi
}

# ============================================================
# 5. NOTIFY TELEGRAM
# ============================================================
notify() {
    local msg="$1"
    if [ -n "$TELEGRAM_BOT" ] && [ -n "$TELEGRAM_CHAT" ]; then
        curl -s "https://api.telegram.org/bot${TELEGRAM_BOT}/sendMessage" \
            -d "chat_id=${TELEGRAM_CHAT}&text=$(echo "$msg" | head -c 500)" 2>/dev/null > /dev/null
    fi
}

# ============================================================
# MAIN PIPELINE LOOP
# ============================================================
TOPICS=(
    "a haunted house with a dark secret"
    "a mysterious stranger in a small town"  
    "a cursed object found in an antique shop"
    "a ghost that can only be seen in mirrors"
    "a door that leads to another dimension"
    "a fortune teller whose predictions come true"
    "a forest where people go missing"
    "an AI that gains consciousness"
)

echo "🚀 Content Agent v3 — Pipeline Started"
echo "   Model: $MODEL | Output: $OUTPUT_DIR"

while true; do
    echo ""
    echo "=============================================="
    echo "  $(date '+%H:%M:%S') — Starting new job"
    echo "=============================================="
    
    # Pick topic
    topic="${TOPICS[$RANDOM % ${#TOPICS[@]}]}"
    job_id=$(uuidgen | cut -c1-8)
    
    # 1. Scrape
    story=$(scrape "$topic") || { sleep 10; continue; }
    notify "📖 Scraped: $(echo "$story" | head -1 | cut -c1-80)"
    
    # 2. TTS  
    audio=$(tts "$story" "$job_id") || { sleep 10; continue; }
   
    # 3. Image
    bg=$(image "$job_id" "$story")
   
    # 4. Intro (MC full screen + "Learn English with Stories" ~3s)
    intro=$(create_intro "$job_id" "$MC_VIDEO" "Learn English with Stories") || { sleep 10; continue; }
    
    # 5. Story video (image BG + MC PIP + story audio)
    story_video=$(compose_story "$job_id" "$bg" "$audio" "$MC_VIDEO") || { sleep 10; continue; }
    
    # 6. Concat intro + story
    video=$(concat_intro_story "$job_id" "$intro" "$story_video")
   
    # 7. Notify
    if [ -n "$video" ]; then
        notify "🎬 Video ready! $(echo "$story" | head -1 | cut -c1-80)"
        echo "✅ JOB COMPLETE: $job_id"
        echo "   Audio: $audio"
        echo "   Image: $bg"
        echo "   Video: $video"
    fi
    
    echo "⏳ Waiting ${SLEEP_MIN} minutes..."
    sleep $((SLEEP_MIN * 60))
done