"""Generate TikTok-style ASS subtitles with word highlighting."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path


# TikTok-style ASS header – 1080x1920 portrait, bold yellow text with heavy outline
_ASS_HEADER = """\
[Script Info]
Title: AI Agent Subtitles
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: CC,Arial,90,&H0000FFFF,&H000000FF,&H00000000,&HAA000000,1,0,0,0,100,100,0,0,1,4,0,2,80,80,120,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

_WORDS_PER_LINE = 4


def _srt_time_to_ass(srt_time: str) -> str:
    """Convert 00:00:01,234 -> 0:00:01.23 (ASS format)."""
    srt_time = srt_time.strip().replace(",", ".")
    parts = srt_time.split(":")
    h, m, rest = parts[0], parts[1], parts[2]
    sec_parts = rest.split(".")
    s = sec_parts[0]
    cs = sec_parts[1][:2] if len(sec_parts) > 1 else "00"
    return f"{int(h)}:{m}:{s}.{cs}"


def _parse_srt_blocks(srt_content: str) -> list[dict]:
    """Parse SRT into list of {start, end, text} dicts."""
    blocks = []
    raw_blocks = re.split(r"\n{2,}", srt_content.strip())
    for block in raw_blocks:
        lines = block.strip().splitlines()
        if len(lines) < 3:
            continue
        timing_match = re.match(
            r"(\d{2}:\d{2}:\d{2}[,\.]\d+)\s+-->\s+(\d{2}:\d{2}:\d{2}[,\.]\d+)",
            lines[1],
        )
        if not timing_match:
            continue
        blocks.append(
            {
                "start": timing_match.group(1),
                "end": timing_match.group(2),
                "text": " ".join(lines[2:]).strip(),
            }
        )
    return blocks


def _group_words(blocks: list[dict], words_per_line: int = _WORDS_PER_LINE) -> list[dict]:
    """Group word-level SRT blocks into short phrase chunks."""
    if not blocks:
        return []

    groups: list[dict] = []
    current_words: list[str] = []
    group_start = blocks[0]["start"]
    group_end = blocks[0]["end"]

    for block in blocks:
        current_words.append(block["text"])
        group_end = block["end"]
        if len(current_words) >= words_per_line:
            groups.append(
                {"start": group_start, "end": group_end, "text": " ".join(current_words)}
            )
            current_words = []
            if blocks.index(block) + 1 < len(blocks):
                group_start = blocks[blocks.index(block) + 1]["start"]

    if current_words:
        groups.append(
            {"start": group_start, "end": group_end, "text": " ".join(current_words)}
        )

    return groups


def _escape_ass(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")


def _ass_color_highlight(text: str) -> str:
    """Make first word bright yellow, rest slightly dimmer for TikTok effect."""
    words = text.split()
    if len(words) <= 1:
        return text
    result = f"{{\\c&H00E5FF&\\b1}}{words[0]}{{\\r}} " + " ".join(words[1:])
    return result


def srt_to_ass(srt_content: str, output_path: str) -> str:
    """Convert SRT (word-level) to TikTok-style ASS with first-word highlight."""
    blocks = _parse_srt_blocks(srt_content)
    groups = _group_words(blocks, words_per_line=_WORDS_PER_LINE)

    lines: list[str] = []
    for g in groups:
        start = _srt_time_to_ass(g["start"])
        end = _srt_time_to_ass(g["end"])
        text = _ass_color_highlight(_escape_ass(g["text"]))
        lines.append(f"Dialogue: 0,{start},{end},CC,,0,0,0,,{text}")

    ass_content = _ASS_HEADER + "\n".join(lines) + "\n"
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(ass_content, encoding="utf-8")
    return str(path)


def estimate_ass_from_text(text: str, audio_path: str, output_path: str) -> str:
    """Generate TikTok-style ASS from text + audio duration."""
    duration = _get_audio_duration(audio_path)
    words = text.split()
    if not words or duration <= 0:
        return ""

    total_words = len(words)
    sec_per_word = duration / total_words

    blocks: list[dict] = []
    for i, word in enumerate(words):
        start_sec = i * sec_per_word
        end_sec = (i + 1) * sec_per_word
        blocks.append(
            {
                "start": _sec_to_srt(start_sec),
                "end": _sec_to_srt(end_sec),
                "text": word,
            }
        )

    groups = _group_words(blocks, words_per_line=_WORDS_PER_LINE)

    lines: list[str] = []
    for g in groups:
        start = _srt_time_to_ass(g["start"])
        end = _srt_time_to_ass(g["end"])
        text = _ass_color_highlight(_escape_ass(g["text"]))
        lines.append(f"Dialogue: 0,{start},{end},CC,,0,0,0,,{text}")

    ass_content = _ASS_HEADER + "\n".join(lines) + "\n"
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(ass_content, encoding="utf-8")
    return str(path)


def _sec_to_srt(sec: float) -> str:
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = int(sec % 60)
    ms = int((sec - int(sec)) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _get_audio_duration(audio_path: str) -> float:
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                audio_path,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        return float(result.stdout.strip())
    except Exception:
        return 0.0