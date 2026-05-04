#!/usr/bin/env python3
"""
YouTube Content Extract — transcript extraction and video understanding.

Uses yt-dlp for subtitles/transcripts, Gemini Web for visual analysis.

Usage:
  youtube-extract.py https://youtube.com/watch?v=VIDEO_ID
  youtube-extract.py https://youtu.be/VIDEO_ID --lang zh
  youtube-extract.py https://youtube.com/watch?v=VIDEO_ID --gemini "What is shown?"
  youtube-extract.py https://youtube.com/watch?v=VIDEO_ID --save /tmp/transcript.md
"""

import argparse
import glob
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional

YOUTUBE_RE = re.compile(
    r"(?:https?://)?(?:www\.)?(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/shorts/|youtube\.com/live/)([a-zA-Z0-9_-]{11})"
)


def extract_transcript_ytdlp(url: str, lang: str = "en") -> Optional[str]:
    """Extract transcript via yt-dlp subtitles."""
    m = YOUTUBE_RE.search(url)
    if not m:
        return None
    video_id = m.group(1)

    with tempfile.TemporaryDirectory(prefix="yt-") as tmpdir:
        out_pattern = os.path.join(tmpdir, f"{video_id}")

        # Try auto-generated subtitles first, then manual
        for sub_flag in ["--write-auto-sub", "--write-sub"]:
            result = subprocess.run(
                ["yt-dlp", "--skip-download", sub_flag,
                 "--sub-lang", f"{lang},en,zh-Hans,zh,zh-Hant,ja,ko",
                 "--sub-format", "vtt",
                 "--output", out_pattern,
                 url],
                capture_output=True, text=True, timeout=60,
            )

            # Find subtitle files
            sub_files = glob.glob(f"{out_pattern}*.vtt") + glob.glob(f"{out_pattern}*.srv1")
            if sub_files:
                break

        if not sub_files:
            return None

        # Parse VTT to plain text
        with open(sub_files[0], "r", errors="replace") as f:
            vtt = f.read()

        lines = []
        for line in vtt.split("\n"):
            line = line.strip()
            if not line or line.startswith("WEBVTT") or line.startswith("Kind:") or line.startswith("Language:"):
                continue
            if re.match(r"^\d{2}:\d{2}", line):
                continue
            if re.match(r"^[\d\s\->:.,]+$", line):
                continue
            clean = re.sub(r"<[^>]+>", "", line)
            if clean and (not lines or clean != lines[-1]):
                lines.append(clean)

        transcript = "\n".join(lines)
        return transcript if len(transcript) > 50 else None


def extract_video_info(url: str) -> dict:
    """Get video metadata via yt-dlp."""
    try:
        result = subprocess.run(
            ["yt-dlp", "--skip-download", "--dump-json", "--no-playlist", url],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0:
            info = json.loads(result.stdout)
            return {
                "title": info.get("title", ""),
                "description": info.get("description", ""),
                "duration": info.get("duration", 0),
                "uploader": info.get("uploader", ""),
                "upload_date": info.get("upload_date", ""),
                "view_count": info.get("view_count", 0),
            }
    except Exception:
        pass
    return {}


def extract_gemini_analysis(url: str, prompt: str = None) -> Optional[str]:
    """Use Gemini Web for video understanding (visual + transcript)."""
    script_dir = Path(__file__).parent
    gemini_script = script_dir / "gemini-web.py"

    if not gemini_script.exists():
        return None

    query = prompt or f"Extract the full transcript and summarize the key content of this YouTube video: {url}"

    try:
        result = subprocess.run(
            [sys.executable, str(gemini_script), "query", query, "--url", url],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode == 0 and len(result.stdout.strip()) > 100:
            return result.stdout.strip()
    except Exception as e:
        print(f"[gemini] Failed: {e}", file=sys.stderr)

    return None


def main():
    parser = argparse.ArgumentParser(description="YouTube content extraction")
    parser.add_argument("url", help="YouTube video URL")
    parser.add_argument("--lang", default="en", help="Preferred subtitle language")
    parser.add_argument("--gemini", help="Ask Gemini a specific question about the video")
    parser.add_argument("--save", help="Save output to file")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    m = YOUTUBE_RE.search(args.url)
    if not m:
        print("Error: Not a YouTube URL", file=sys.stderr)
        sys.exit(1)

    video_id = m.group(1)
    print(f"[youtube] Video ID: {video_id}", file=sys.stderr)

    # Get video metadata
    info = extract_video_info(args.url)
    title = info.get("title", video_id)

    # Extract transcript
    print("[youtube] Extracting transcript...", file=sys.stderr)
    transcript = extract_transcript_ytdlp(args.url, args.lang)

    # Gemini analysis (if requested or transcript failed)
    gemini_result = None
    if args.gemini or not transcript:
        if not transcript:
            print("[youtube] No transcript found, trying Gemini Web...", file=sys.stderr)
        else:
            print("[youtube] Running Gemini analysis...", file=sys.stderr)
        gemini_result = extract_gemini_analysis(args.url, args.gemini)

    # Build output
    output = f"# YouTube: {title}\n\n"
    output += f"- URL: {args.url}\n"
    output += f"- Video ID: {video_id}\n"
    if info.get("uploader"):
        output += f"- Channel: {info['uploader']}\n"
    if info.get("duration"):
        dur = info["duration"]
        output += f"- Duration: {dur // 60}:{dur % 60:02d}\n"
    output += "\n"

    if transcript:
        output += f"## Transcript\n\n{transcript}\n\n"

    if gemini_result:
        output += f"## Gemini Analysis\n\n{gemini_result}\n\n"

    if not transcript and not gemini_result:
        output += "**No transcript or analysis available.** Video may lack subtitles.\n"
        output += "Try: `pip install yt-dlp` and retry, or use CDP browser to view directly.\n"

    if args.save:
        Path(args.save).parent.mkdir(parents=True, exist_ok=True)
        Path(args.save).write_text(output, encoding="utf-8")
        print(f"[saved] {args.save}", file=sys.stderr)

    if args.json:
        print(json.dumps({
            "video_id": video_id,
            "title": title,
            "info": info,
            "transcript": transcript,
            "gemini_analysis": gemini_result,
        }, ensure_ascii=False, indent=2))
    else:
        print(output)


if __name__ == "__main__":
    main()
