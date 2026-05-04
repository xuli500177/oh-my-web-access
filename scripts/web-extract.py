#!/usr/bin/env python3
"""
Unified Web Extract — smart content extraction with automatic fallback chain.

Fallback order:
  1. HTTP fetch + Readability  (fast, no API, works for most static pages)
  2. Jina Reader               (server-side HTML→MD, rate-limited 20 RPM)
  3. Gemini Web extraction     (AI-powered, handles JS/SPA, free via cookies)
  4. Firecrawl                 (headless Chrome, requires API key or self-host)
  5. CDP Browser               (last resort, full browser automation)

Special URL detection:
  - GitHub repos  → git clone + tree + README
  - YouTube       → yt-dlp transcript + Gemini visual analysis
  - PDF           → PyMuPDF text extraction

Usage:
  web-extract.py URL                          # Auto-detect and extract
  web-extract.py URL --format markdown        # Force markdown output
  web-extract.py URL --method jina            # Force specific method
  web-extract.py URL --method firecrawl       # Use Firecrawl
  web-extract.py URL --save /tmp/output.md    # Save to file
  web-extract.py URL --max-chars 50000        # Limit output length
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.request
import urllib.parse
import urllib.error
from pathlib import Path
from typing import Optional, Tuple

# ── Constants ──────────────────────────────────────────────────────────────

JINA_PREFIX = "https://r.jina.ai/"
DEFAULT_MAX_CHARS = 100_000
FIRECRAWL_CLOUD_URL = "https://api.firecrawl.dev/v1"
GEMINI_CACHE = Path.home() / ".hermes" / "gemini-web-cache.json"

# ── URL Classification ─────────────────────────────────────────────────────

GITHUB_URL_RE = re.compile(
    r"https?://(?:www\.)?github\.com/([^/]+)/([^/]+)(?:/tree/[^/]+)?(?:/(.*))?"
)
YOUTUBE_URL_RE = re.compile(
    r"(?:https?://)?(?:www\.)?(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/shorts/|youtube\.com/live/)([a-zA-Z0-9_-]{11})"
)
PDF_URL_RE = re.compile(r"\.pdf(?:\?|$)", re.IGNORECASE)


def classify_url(url: str) -> str:
    """Classify URL type for specialized handling."""
    if GITHUB_URL_RE.match(url):
        return "github"
    if YOUTUBE_URL_RE.search(url):
        return "youtube"
    if PDF_URL_RE.search(url):
        return "pdf"
    return "web"


# ── Method 1: HTTP + Readability ───────────────────────────────────────────

def extract_readability(url: str, max_chars: int = DEFAULT_MAX_CHARS) -> Optional[str]:
    """Fetch URL via HTTP and extract readable content using readability-lxml."""
    try:
        from readability import Document
        import urllib.request

        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="replace")

        doc = Document(html)
        title = doc.title()
        content = doc.summary(html_partial=True)

        # Strip HTML tags for plain text
        import re
        text = re.sub(r"<[^>]+>", "\n", content)
        text = re.sub(r"\n{3,}", "\n\n", text).strip()

        if len(text) < 500:
            return None  # Too little content, probably a SPA shell

        result = f"# {title}\n\n{text}"
        return result[:max_chars] if len(result) > max_chars else result
    except Exception as e:
        print(f"[readability] Failed: {e}", file=sys.stderr)
        return None


# ── Method 2: Structured Data + RSC Parser ────────────────────────────────

def extract_rsc(url: str, max_chars: int = DEFAULT_MAX_CHARS) -> Optional[str]:
    """Parse structured data from HTML: data attributes, RSC flight, __NEXT_DATA__.
    
    Many modern frameworks embed content as:
    - HTML data-* attributes (Astro, SvelteKit, etc.)
    - RSC flight payloads (Next.js App Router)
    - __NEXT_DATA__ JSON (Next.js Pages Router)
    
    This method tries all patterns before falling back to heavier tools.
    """
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml",
            # Request RSC payload alongside HTML
            "RSC": "1",
            "Next-Router-State-Tree": "%5B%22%22%5D",
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("utf-8", errors="replace")

        import re as _re
        extracted = []

        # ── Pattern 1: data-* attributes (Astro, SvelteKit, static SSR) ──
        # Look for repeating structured elements with data attributes
        data_patterns = [
            # Generic: data-*-name + data-*-description/search/title
            (_re.compile(r'data-(?:package|item|card|entry|post)-name="([^"]+)"', _re.I),
             _re.compile(r'data-(?:package|item|card|entry|post)-(?:search|description|title|content)="([^"]+)"', _re.I)),
        ]
        for name_re, desc_re in data_patterns:
            names = name_re.findall(raw)
            descs = desc_re.findall(raw)
            if names and len(names) >= 3:  # Likely a list page
                import html as _html
                pairs = list(zip(names, descs)) if len(descs) >= len(names) else [(n, "") for n in names]
                for name, desc in pairs:
                    name = _html.unescape(name)
                    desc = _html.unescape(desc) if desc else ""
                    if desc:
                        extracted.append(f"- **{name}**: {desc}")
                    else:
                        extracted.append(f"- {name}")
                break

        # ── Pattern 2: __NEXT_DATA__ (Next.js Pages Router) ──
        if not extracted:
            nd_match = _re.search(r'<script[^>]*id="__NEXT_DATA__"[^>]*>(.*?)</script>', raw, _re.DOTALL)
            if nd_match:
                try:
                    obj = json.loads(nd_match.group(1))
                    _extract_text_from_rsc_obj(obj, extracted)
                except Exception:
                    pass

        # ── Pattern 3: RSC flight data (Next.js App Router) ──
        if not extracted and (raw.startswith("1:") or raw.startswith("0:") or "\n$S" in raw):
            for line in raw.split("\n"):
                line = line.strip()
                if not line:
                    continue
                colon_idx = line.find(":")
                if colon_idx > 0 and colon_idx < 4:
                    data_part = line[colon_idx + 1:]
                    try:
                        obj = json.loads(data_part)
                        _extract_text_from_rsc_obj(obj, extracted)
                    except (json.JSONDecodeError, ValueError):
                        if len(data_part) > 10 and not data_part.startswith("$"):
                            extracted.append(data_part)

        # ── Pattern 4: Inline RSC flight in <script> ──
        if not extracted:
            rsc_inline = _re.findall(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)', raw, _re.DOTALL)
            for chunk in rsc_inline:
                _parse_rsc_flight_chunk(chunk, extracted)

        if extracted:
            # Deduplicate
            seen = set()
            deduped = []
            for item in extracted:
                if item not in seen:
                    seen.add(item)
                    deduped.append(item)
            text = "\n".join(deduped)
            if len(text.strip()) > 50:
                result = f"# {url}\n\n{text}"
                return result[:max_chars] if len(result) > max_chars else result

        return None
    except Exception as e:
        print(f"[rsc] Failed: {e}", file=sys.stderr)
        return None

        # Check if response is pure RSC flight data (starts with special markers)
        if raw.startswith("1:") or raw.startswith("0:") or "\n$S" in raw:
            # Parse RSC flight format: lines like `N:type_id:json_data`
            parts = []
            for line in raw.split("\n"):
                line = line.strip()
                if not line:
                    continue
                # Flight format: `TYPE:ID:JSON` or inline data
                colon_idx = line.find(":")
                if colon_idx > 0 and colon_idx < 4:
                    data_part = line[colon_idx + 1:]
                    # Try to extract text content from JSON chunks
                    try:
                        obj = json.loads(data_part)
                        _extract_text_from_rsc_obj(obj, parts)
                    except (json.JSONDecodeError, ValueError):
                        # May be inline string content
                        if len(data_part) > 10 and not data_part.startswith("$"):
                            parts.append(data_part)
                elif len(line) > 20 and not line.startswith("$"):
                    parts.append(line)

            text = "\n".join(parts)
            # Deduplicate consecutive identical lines
            deduped = []
            for l in text.split("\n"):
                if l.strip() and (not deduped or l != deduped[-1]):
                    deduped.append(l)
            text = "\n".join(deduped)

            if len(text.strip()) > 100:
                result = f"# {url}\n\n{text}"
                return result[:max_chars] if len(result) > max_chars else result

        # Otherwise treat as HTML — look for embedded RSC data in script tags
        import re as _re
        # Next.js embeds RSC data in <script> tags with specific patterns
        rsc_patterns = [
            _re.compile(r'<script[^>]*id="__NEXT_DATA__"[^>]*>(.*?)</script>', _re.DOTALL),
            _re.compile(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)', _re.DOTALL),
        ]

        extracted = []
        for pattern in rsc_patterns:
            for match in pattern.finditer(raw):
                try:
                    data = match.group(1)
                    # Unescape JSON string if needed
                    if data.startswith('{'):
                        obj = json.loads(data)
                        # Extract text from Next.js data
                        page_props = obj.get("props", {}).get("pageProps", {})
                        _extract_text_from_rsc_obj(page_props, extracted)
                    else:
                        # RSC flight data embedded in script
                        _parse_rsc_flight_chunk(data, extracted)
                except Exception:
                    pass

        if extracted:
            text = "\n".join(extracted)
            if len(text.strip()) > 100:
                result = f"# {url}\n\n{text}"
                return result[:max_chars] if len(result) > max_chars else result

        # Check if HTML itself has enough content (non-SPA)
        from readability import Document
        doc = Document(raw)
        readable = doc.summary(html_partial=True)
        text = _re.sub(r"<[^>]+>", "\n", readable)
        text = _re.sub(r"\n{3,}", "\n\n", text).strip()
        if len(text) > 300:
            result = f"# {doc.title()}\n\n{text}"
            return result[:max_chars] if len(result) > max_chars else result

        return None
    except Exception as e:
        print(f"[rsc] Failed: {e}", file=sys.stderr)
        return None


def _extract_text_from_rsc_obj(obj, parts: list, depth: int = 0):
    """Recursively extract text content from RSC/JSON objects."""
    if depth > 15:
        return
    if isinstance(obj, str):
        if len(obj) > 5 and not obj.startswith("$") and not obj.startswith("{"):
            parts.append(obj)
    elif isinstance(obj, list):
        for item in obj:
            _extract_text_from_rsc_obj(item, parts, depth + 1)
    elif isinstance(obj, dict):
        for key in ["children", "content", "text", "title", "description",
                     "name", "value", "data", "props", "body"]:
            if key in obj:
                _extract_text_from_rsc_obj(obj[key], parts, depth + 1)
        # Also check for type/content patterns in RSC
        if "type" in obj and "content" in obj:
            _extract_text_from_rsc_obj(obj["content"], parts, depth + 1)


def _parse_rsc_flight_chunk(data: str, parts: list):
    """Parse an RSC flight data chunk from inline script."""
    # Unescape common escape sequences
    data = data.replace('\\n', '\n').replace('\\"', '"').replace('\\\\', '\\')
    # Try line-by-line RSC format
    for line in data.split("\n"):
        line = line.strip()
        if not line or line.startswith("$"):
            continue
        colon = line.find(":")
        if 0 < colon < 4:
            payload = line[colon + 1:]
            try:
                obj = json.loads(payload)
                _extract_text_from_rsc_obj(obj, parts)
            except (json.JSONDecodeError, ValueError):
                if len(payload) > 10:
                    parts.append(payload)


# ── Method 3: Jina Reader ──────────────────────────────────────────────────

def extract_jina(url: str, max_chars: int = DEFAULT_MAX_CHARS) -> Optional[str]:
    """Extract content via Jina Reader (server-side HTML→MD)."""
    try:
        # Strip http(s):// prefix for Jina
        clean_url = re.sub(r"^https?://", "", url)
        jina_url = f"{JINA_PREFIX}{clean_url}"

        req = urllib.request.Request(jina_url, headers={
            "Accept": "text/markdown",
            "User-Agent": "Mozilla/5.0",
        })
        with urllib.request.urlopen(req, timeout=30) as resp:
            content = resp.read().decode("utf-8", errors="replace")

        if len(content.strip()) < 100:
            return None

        return content[:max_chars] if len(content) > max_chars else content
    except Exception as e:
        print(f"[jina] Failed: {e}", file=sys.stderr)
        return None


# ── Method 3: Gemini Web ───────────────────────────────────────────────────

def extract_gemini_web(url: str, max_chars: int = DEFAULT_MAX_CHARS) -> Optional[str]:
    """Extract content via Gemini Web (AI-powered, handles JS/SPA)."""
    script_dir = Path(__file__).parent
    gemini_script = script_dir / "gemini-web.py"

    if not gemini_script.exists():
        print("[gemini] gemini-web.py not found", file=sys.stderr)
        return None

    try:
        result = subprocess.run(
            [sys.executable, str(gemini_script), "extract", url],
            capture_output=True, text=True, timeout=60,
        )
        if result.returncode != 0:
            print(f"[gemini] Failed: {result.stderr}", file=sys.stderr)
            return None

        content = result.stdout.strip()
        if len(content) < 100:
            return None

        return content[:max_chars] if len(content) > max_chars else content
    except Exception as e:
        print(f"[gemini] Failed: {e}", file=sys.stderr)
        return None


# ── Method 4: Firecrawl ────────────────────────────────────────────────────

def extract_firecrawl(url: str, max_chars: int = DEFAULT_MAX_CHARS) -> Optional[str]:
    """Extract content via Firecrawl (headless Chrome). Requires API key."""
    api_key = os.environ.get("FIRECRAWL_API_KEY", "")
    if not api_key:
        # Check hermes config
        config_path = Path.home() / ".hermes" / "config.yaml"
        if config_path.exists():
            try:
                import yaml
                with open(config_path) as f:
                    cfg = yaml.safe_load(f)
                api_key = (cfg.get("web", {}).get("firecrawl_api_key", "")
                           or cfg.get("firecrawl_api_key", ""))
            except Exception:
                pass

    if not api_key:
        print("[firecrawl] No API key found (set FIRECRAWL_API_KEY env)", file=sys.stderr)
        return None

    try:
        import json
        payload = json.dumps({
            "url": url,
            "formats": ["markdown"],
            "timeout": 60000,
        }).encode()

        req = urllib.request.Request(
            f"{FIRECRAWL_CLOUD_URL}/scrape",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
        )
        with urllib.request.urlopen(req, timeout=65) as resp:
            data = json.loads(resp.read().decode())

        content = data.get("data", {}).get("markdown", "")
        if len(content.strip()) < 100:
            return None

        return content[:max_chars] if len(content) > max_chars else content
    except Exception as e:
        print(f"[firecrawl] Failed: {e}", file=sys.stderr)
        return None


# ── GitHub Extract ─────────────────────────────────────────────────────────

def extract_github(url: str, max_chars: int = DEFAULT_MAX_CHARS) -> Optional[str]:
    """Clone GitHub repo and return directory tree + README."""
    m = GITHUB_URL_RE.match(url)
    if not m:
        return None

    owner, repo = m.group(1), m.group(2)
    repo_url = f"https://github.com/{owner}/{repo}"

    with tempfile.TemporaryDirectory(prefix="gh-extract-") as tmpdir:
        clone_path = os.path.join(tmpdir, repo)

        try:
            # Shallow clone (depth=1) for speed
            result = subprocess.run(
                ["git", "clone", "--depth=1", repo_url, clone_path],
                capture_output=True, text=True, timeout=120,
            )
            if result.returncode != 0:
                print(f"[github] Clone failed: {result.stderr}", file=sys.stderr)
                return None

            # Get directory tree
            tree_result = subprocess.run(
                ["find", clone_path, "-maxdepth=3", "-not", "-path", "*/.git/*"],
                capture_output=True, text=True, timeout=10,
            )
            tree_lines = []
            for line in tree_result.stdout.strip().split("\n"):
                rel = line.replace(clone_path + "/", "").replace(clone_path, "")
                if rel and rel != ".git":
                    tree_lines.append(rel)
            tree_lines.sort()

            # Read README if exists
            readme_content = ""
            for readme_name in ["README.md", "README.rst", "README.txt", "README"]:
                readme_path = os.path.join(clone_path, readme_name)
                if os.path.exists(readme_path):
                    with open(readme_path, "r", errors="replace") as f:
                        readme_content = f.read()
                    break

            # Build output
            output = f"# {owner}/{repo}\n\n"
            output += f"## Directory Tree\n\n```\n"
            output += "\n".join(tree_lines[:200])
            if len(tree_lines) > 200:
                output += f"\n... ({len(tree_lines)} total)"
            output += "\n```\n\n"

            if readme_content:
                output += f"## README\n\n{readme_content}\n"

            return output[:max_chars] if len(output) > max_chars else output

        except Exception as e:
            print(f"[github] Failed: {e}", file=sys.stderr)
            return None


# ── YouTube Extract ────────────────────────────────────────────────────────

def extract_youtube(url: str, max_chars: int = DEFAULT_MAX_CHARS) -> Optional[str]:
    """Extract YouTube video transcript via yt-dlp, fallback to Gemini Web."""
    m = YOUTUBE_URL_RE.search(url)
    video_id = m.group(1) if m else "unknown"

    # Try yt-dlp first (subtitles/transcript)
    try:
        result = subprocess.run(
            ["yt-dlp", "--skip-download", "--write-auto-sub", "--sub-lang", "en,zh-Hans,zh",
             "--sub-format", "vtt", "--output", "/tmp/yt-%(id)s", url],
            capture_output=True, text=True, timeout=60,
        )

        # Find subtitle file
        import glob
        sub_files = glob.glob(f"/tmp/yt-{video_id}*.vtt")
        if sub_files:
            with open(sub_files[0], "r", errors="replace") as f:
                vtt_content = f.read()

            # Parse VTT to plain text (remove timestamps and tags)
            lines = []
            for line in vtt_content.split("\n"):
                line = line.strip()
                if not line or line.startswith("WEBVTT") or line.startswith("Kind:") or line.startswith("Language:"):
                    continue
                if re.match(r"^\d{2}:\d{2}", line):
                    continue
                if re.match(r"^[\d\s\->:.,]+$", line):
                    continue
                # Remove VTT tags
                clean = re.sub(r"<[^>]+>", "", line)
                if clean and clean not in lines[-3:]:  # Deduplicate consecutive
                    lines.append(clean)

            transcript = "\n".join(lines)
            if len(transcript) > 50:
                # Clean up temp files
                for f in sub_files:
                    try: os.unlink(f)
                    except: pass

                output = f"# YouTube: {video_id}\n\n## Transcript\n\n{transcript}"
                return output[:max_chars] if len(output) > max_chars else output

    except Exception as e:
        print(f"[yt-dlp] Failed: {e}", file=sys.stderr)

    # Fallback: Gemini Web for video understanding
    print("[youtube] yt-dlp failed, trying Gemini Web...", file=sys.stderr)
    script_dir = Path(__file__).parent
    gemini_script = script_dir / "gemini-web.py"
    if gemini_script.exists():
        try:
            result = subprocess.run(
                [sys.executable, str(gemini_script), "query",
                 f"Extract the full transcript and key content from this YouTube video: {url}",
                 "--url", url],
                capture_output=True, text=True, timeout=90,
            )
            if result.returncode == 0 and len(result.stdout.strip()) > 100:
                return result.stdout.strip()[:max_chars]
        except Exception as e:
            print(f"[youtube-gemini] Failed: {e}", file=sys.stderr)

    return None


# ── PDF Extract ────────────────────────────────────────────────────────────

def extract_pdf(url: str, max_chars: int = DEFAULT_MAX_CHARS) -> Optional[str]:
    """Download and extract text from PDF using PyMuPDF."""
    try:
        import fitz  # PyMuPDF

        # Download PDF to temp file
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0",
        })
        with urllib.request.urlopen(req, timeout=30) as resp:
            pdf_data = resp.read()

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(pdf_data)
            tmp_path = tmp.name

        try:
            doc = fitz.open(tmp_path)
            text_parts = []
            for page_num in range(len(doc)):
                page = doc[page_num]
                text = page.get_text()
                if text.strip():
                    text_parts.append(f"--- Page {page_num + 1} ---\n{text}")
            doc.close()

            content = "\n\n".join(text_parts)
            if len(content.strip()) < 50:
                return None

            output = f"# PDF: {url}\n\n{content}"
            return output[:max_chars] if len(output) > max_chars else output
        finally:
            os.unlink(tmp_path)

    except Exception as e:
        print(f"[pdf] Failed: {e}", file=sys.stderr)
        return None


# ── Method: Scrapling (Anti-bot / Cloudflare bypass) ──────────────────────

def extract_scrapling(url: str, max_chars: int = DEFAULT_MAX_CHARS) -> Optional[str]:
    """Extract content via Scrapling StealthyFetcher (anti-bot bypass)."""
    try:
        result = subprocess.run(
            ["scrapling", "extract", "stealthy-fetch", url, "/tmp/scrapling-out.md",
             "--solve-cloudflare", "--block-webrtc"],
            capture_output=True, text=True, timeout=60,
        )
        if result.returncode != 0:
            # Fallback to dynamic fetch
            result = subprocess.run(
                ["scrapling", "extract", "fetch", url, "/tmp/scrapling-out.md",
                 "--network-idle"],
                capture_output=True, text=True, timeout=60,
            )
        if result.returncode != 0:
            print(f"[scrapling] Failed: {result.stderr}", file=sys.stderr)
            return None
        out_path = "/tmp/scrapling-out.md"
        if not os.path.exists(out_path):
            return None
        with open(out_path, "r", errors="replace") as f:
            content = f.read()
        os.unlink(out_path)
        if len(content.strip()) < 100:
            return None
        return content[:max_chars] if len(content) > max_chars else content
    except FileNotFoundError:
        print("[scrapling] Not installed (pip install scrapling[all] && scrapling install)", file=sys.stderr)
        return None
    except Exception as e:
        print(f"[scrapling] Failed: {e}", file=sys.stderr)
        return None


# ── Main: Unified Extraction ───────────────────────────────────────────────

METHODS = {
    "readability": extract_readability,
    "rsc": extract_rsc,
    "jina": extract_jina,
    "gemini": extract_gemini_web,
    "scrapling": extract_scrapling,
    "firecrawl": extract_firecrawl,
}

WEB_FALLBACK_CHAIN = ["readability", "rsc", "jina", "gemini", "scrapling", "firecrawl"]


def extract_web(url: str, method: Optional[str] = None,
                max_chars: int = DEFAULT_MAX_CHARS) -> Optional[str]:
    """Extract web content with smart fallback chain."""
    if method:
        fn = METHODS.get(method)
        if fn:
            return fn(url, max_chars)
        print(f"[error] Unknown method: {method}", file=sys.stderr)
        return None

    # Auto fallback chain
    for name in WEB_FALLBACK_CHAIN:
        print(f"[try] {name}...", file=sys.stderr)
        result = METHODS[name](url, max_chars)
        if result:
            print(f"[ok] {name} succeeded ({len(result)} chars)", file=sys.stderr)
            return result
        print(f"[skip] {name} failed or insufficient", file=sys.stderr)

    return None


def main():
    parser = argparse.ArgumentParser(description="Unified web content extraction")
    parser.add_argument("url", help="URL to extract content from")
    parser.add_argument("--method", choices=["readability", "rsc", "jina", "gemini", "scrapling", "firecrawl"],
                        help="Force specific extraction method")
    parser.add_argument("--format", default="markdown", help="Output format")
    parser.add_argument("--save", help="Save output to file")
    parser.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS,
                        help="Maximum output characters")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    url = args.url
    url_type = classify_url(url)

    # Route to specialized extractors
    if url_type == "github":
        print(f"[detect] GitHub repository", file=sys.stderr)
        content = extract_github(url, args.max_chars)
    elif url_type == "youtube":
        print(f"[detect] YouTube video", file=sys.stderr)
        content = extract_youtube(url, args.max_chars)
    elif url_type == "pdf":
        print(f"[detect] PDF document", file=sys.stderr)
        content = extract_pdf(url, args.max_chars)
    else:
        content = extract_web(url, args.method, args.max_chars)

    if content is None:
        if args.json:
            print(json.dumps({"success": False, "url": url, "error": "All extraction methods failed"}))
        else:
            print(f"Error: Failed to extract content from {url}", file=sys.stderr)
            print("All methods exhausted. Consider using CDP browser for login-protected or heavily JS-rendered pages.", file=sys.stderr)
        sys.exit(1)

    if args.save:
        Path(args.save).parent.mkdir(parents=True, exist_ok=True)
        Path(args.save).write_text(content, encoding="utf-8")
        print(f"[saved] {args.save} ({len(content)} chars)", file=sys.stderr)

    if args.json:
        print(json.dumps({
            "success": True,
            "url": url,
            "type": url_type,
            "chars": len(content),
            "content": content,
        }, ensure_ascii=False))
    else:
        print(content)


if __name__ == "__main__":
    main()
