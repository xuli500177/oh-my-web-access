#!/usr/bin/env python3
"""
Gemini Web Access — free AI search & content extraction via cached Chrome cookies.

No API key needed. Uses your Google account's Gemini Web session.

Usage:
  gemini-web.py import cookies.json       # Import cookies from browser export
  gemini-web.py query "your question"     # Ask Gemini Web
  gemini-web.py query "explain" --url URL # Ask about a URL
  gemini-web.py search "search query"     # AI-powered web search
  gemini-web.py extract URL               # Extract content from a URL
  gemini-web.py status                    # Check cache freshness

Cookie sources:
  - Browser extension "EditThisCookie" or "Cookie-Editor" → export JSON
  - gemini-web.py import cookies.json
"""

import argparse, json, os, re, sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
import urllib.request, urllib.parse, urllib.error

# ── Constants ──────────────────────────────────────────────────────────────

CACHE_FILE = Path.home() / ".cache" / "gemini-web-cache.json"
MAX_CACHE_AGE = timedelta(days=30)      # Google session cookies last months
WARN_CACHE_AGE = timedelta(days=14)

GEMINI_APP_URL = "https://gemini.google.com/app"
GEMINI_STREAM_URL = (
    "https://gemini.google.com/_/BardChatUi/data/"
    "assistant.lamda.BardFrontendService/StreamGenerate"
)
MODEL_HEADER_NAME = "x-goog-ext-525001261-jspb"
MODELS = {
    "gemini-3.1-pro": '[1,null,null,null,"gemini-3.1-pro-header",null,null,0,[4]]',
    "gemini-3-pro": '[1,null,null,null,"9d8ca3786ebdfbea",null,null,0,[4]]',
    "gemini-2.5-pro": '[1,null,null,null,"4af6c7f5da75d65d",null,null,0,[4]]',
    "gemini-2.5-flash": '[1,null,null,null,"9ec249fc9ad08861",null,null,0,[4]]',
}
DEFAULT_MODEL = "gemini-3.1-pro"
# Fallback chain: try models in order until one works
FALLBACK_CHAIN = ["gemini-3.1-pro", "gemini-3-pro", "gemini-2.5-pro", "gemini-2.5-flash"]
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# ── Helpers ────────────────────────────────────────────────────────────────

def _get_nested(obj, path):
    """Walk nested list/dict by index path."""
    cur = obj
    for idx in path:
        if cur is None:
            return None
        try:
            cur = cur[idx]
        except (IndexError, KeyError, TypeError):
            return None
    return cur


def _cookie_header(cookies: dict) -> str:
    return "; ".join(f"{k}={v}" for k, v in cookies.items() if v)


def _fetch_access_token(cookie_hdr: str) -> str:
    """GET gemini.google.com/app → extract SNlM0e token."""
    req = urllib.request.Request(GEMINI_APP_URL, headers={
        "User-Agent": USER_AGENT, "Cookie": cookie_hdr,
    })
    with urllib.request.urlopen(req, timeout=15) as r:
        html = r.read().decode("utf-8", errors="replace")
    for key in ("SNlM0e", "thykhd"):
        m = re.search(rf'"{key}":"(.*?)"', html)
        if m:
            return m.group(1)
    raise RuntimeError(
        "Could not authenticate with Gemini. "
        "Cookies may be expired — re-import fresh cookies."
    )


def _parse_stream_response(raw: str) -> tuple[str, Optional[int]]:
    """Parse Gemini StreamGenerate → (text, error_code)."""
    start, end = raw.find("["), raw.rfind("]")
    if start < 0 or end <= start:
        raise RuntimeError("Gemini returned non-JSON response")

    resp = json.loads(raw[start:end + 1])

    error_code = None
    try:
        error_code = _get_nested(resp, [0, 5, 2, 0, 1, 0])
    except Exception:
        pass

    # Streaming response: collect all text chunks, return the last (most complete)
    last_text = None
    for part in (resp if isinstance(resp, list) else []):
        if not isinstance(part, list) or len(part) < 3:
            continue
        body_str = part[2]
        if not isinstance(body_str, str):
            continue
        try:
            parsed = json.loads(body_str)
            if not isinstance(parsed, list) or len(parsed) < 5:
                continue
            candidates = parsed[4]
            if not isinstance(candidates, list) or not candidates:
                continue
            c0 = candidates[0]
            if not isinstance(c0, list) or len(c0) < 2:
                continue
            text_val = c0[1]
            if isinstance(text_val, list) and len(text_val) > 0:
                t = text_val[0]
                if isinstance(t, str) and t:
                    if re.match(r"^http://googleusercontent\.com/card_content/\d+", t):
                        alt = c0[22][0] if len(c0) > 22 and isinstance(c0[22], list) and c0[22] else None
                        if isinstance(alt, str) and alt:
                            last_text = alt
                    else:
                        last_text = t
            elif isinstance(text_val, str) and text_val:
                if re.match(r"^http://googleusercontent\.com/card_content/\d+", text_val):
                    alt = c0[22][0] if len(c0) > 22 and isinstance(c0[22], list) and c0[22] else None
                    if isinstance(alt, str) and alt:
                        last_text = alt
                else:
                    last_text = text_val
        except (json.JSONDecodeError, TypeError, IndexError):
            continue

    if last_text:
        return last_text, error_code

    raise RuntimeError("Could not extract text from Gemini response")


# ── Cache Management ───────────────────────────────────────────────────────

def save_cache(cookies: dict):
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    CACHE_FILE.write_text(json.dumps({
        "extracted_at": datetime.now().isoformat(),
        "source": "manual_export",
        "cookies": cookies,
    }, indent=2))
    n = len(cookies)
    print(f"✓ Cached {n} cookies → {CACHE_FILE}")
    print(f"  Keys: {', '.join(sorted(cookies.keys()))}")


def load_cache(fail_stale=True) -> dict:
    if not CACHE_FILE.exists():
        raise RuntimeError(
            "No cached cookies. Run: gemini-web.py import <cookies.json>"
        )
    cache = json.loads(CACHE_FILE.read_text())
    extracted = datetime.fromisoformat(cache["extracted_at"])
    age = datetime.now() - extracted
    days = age.total_seconds() / 86400

    if fail_stale and age > MAX_CACHE_AGE:
        raise RuntimeError(
            f"Cookies expired ({days:.0f}d old, max {MAX_CACHE_AGE.days}d). "
            "Re-import fresh cookies."
        )
    if age > WARN_CACHE_AGE:
        print(f"⚠ Cookies are {days:.0f}d old — consider re-importing.", file=sys.stderr)

    return cache["cookies"]


def show_status():
    if not CACHE_FILE.exists():
        print("No cached cookies. Run: gemini-web.py import <cookies.json>")
        return 1
    cache = json.loads(CACHE_FILE.read_text())
    extracted = datetime.fromisoformat(cache["extracted_at"])
    age = datetime.now() - extracted
    days = age.total_seconds() / 86400
    cookies = cache.get("cookies", {})

    if days < 7:
        tag = "✓ fresh"
    elif days < MAX_CACHE_AGE.days:
        tag = "⚠ aging"
    else:
        tag = "✗ expired"

    print(f"Gemini Web Cookie Cache: {tag}")
    print(f"  Imported  : {extracted:%Y-%m-%d %H:%M} ({days:.1f}d ago)")
    print(f"  Cookies   : {len(cookies)} ({', '.join(sorted(cookies.keys())[:8])}...)")
    print(f"  Model     : {DEFAULT_MODEL}")
    return 0


# ── Import ─────────────────────────────────────────────────────────────────

def import_cookies(path: str):
    """Import cookies from browser export (EditThisCookie / Cookie-Editor JSON)."""
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    if isinstance(raw, list):
        # Browser export format: [{name, value, domain, ...}, ...]
        cookies = {}
        for c in raw:
            name = c.get("name", "")
            value = c.get("value", "")
            domain = c.get("domain", "")
            if not name or not value:
                continue
            # Take google.com and gemini.google.com cookies
            if "google.com" in domain:
                if name not in cookies:  # first occurrence wins
                    cookies[name] = value
    elif isinstance(raw, dict) and "cookies" in raw:
        # Already our cache format
        cookies = raw["cookies"]
    elif isinstance(raw, dict):
        # Already a name→value map
        cookies = raw
    else:
        raise RuntimeError(f"Unrecognized cookie format in {path}")

    required = ["__Secure-1PSID", "__Secure-1PSIDTS"]
    missing = [k for k in required if k not in cookies]
    if missing:
        raise RuntimeError(
            f"Missing required cookies: {missing}. "
            "Make sure you exported cookies while logged into gemini.google.com"
        )

    save_cache(cookies)


# ── Core API ───────────────────────────────────────────────────────────────

def query_gemini(prompt: str, model: str = DEFAULT_MODEL,
                 url: str = None) -> str:
    """Query Gemini Web. Returns response text."""
    cookies = load_cache()
    cookie_hdr = _cookie_header(cookies)
    at = _fetch_access_token(cookie_hdr)

    full_prompt = prompt
    if url:
        full_prompt = f"{prompt}\n\nURL to analyze: {url}"

    inner = [[full_prompt], None, None]
    f_req = json.dumps([None, json.dumps(inner)])
    body = urllib.parse.urlencode({"at": at, "f.req": f_req}).encode("utf-8")

    model_hdr = MODELS.get(model, MODELS[DEFAULT_MODEL])
    headers = {
        "Content-Type": "application/x-www-form-urlencoded;charset=utf-8",
        "Host": "gemini.google.com",
        "Origin": "https://gemini.google.com",
        "Referer": "https://gemini.google.com/",
        "X-Same-Domain": "1",
        "User-Agent": USER_AGENT,
        "Cookie": cookie_hdr,
        MODEL_HEADER_NAME: model_hdr,
    }

    req = urllib.request.Request(GEMINI_STREAM_URL, data=body, headers=headers)
    with urllib.request.urlopen(req, timeout=120) as r:
        raw = r.read().decode("utf-8", errors="replace")

    text, error_code = _parse_stream_response(raw)

    # Model unavailable → step down the fallback chain
    if error_code == 1052:
        try:
            idx = FALLBACK_CHAIN.index(model)
        except ValueError:
            idx = -1
        if idx < len(FALLBACK_CHAIN) - 1:
            next_model = FALLBACK_CHAIN[idx + 1]
            print(f"  Model {model} unavailable, trying {next_model}...",
                  file=sys.stderr)
            return query_gemini(prompt, model=next_model, url=url)
        else:
            print("  All models exhausted.", file=sys.stderr)

    return text


def query_gemini_with_retry(prompt: str, model: str = DEFAULT_MODEL,
                             url: str = None, max_retries: int = 2) -> str:
    """Wrapper with retry for transient parse errors."""
    for attempt in range(max_retries + 1):
        try:
            return query_gemini(prompt, model=model, url=url)
        except RuntimeError as e:
            if attempt < max_retries and "Could not extract text" in str(e):
                wait = 2 ** attempt
                print(f"  Transient error (attempt {attempt+1}/{max_retries+1}), "
                      f"retrying in {wait}s...", file=sys.stderr)
                import time; time.sleep(wait)
            else:
                raise


# ── Main ───────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(
        description="Gemini Web Access (free, via cached cookies)")
    sub = p.add_subparsers(dest="cmd")

    imp = sub.add_parser("import", help="Import cookies from browser export")
    imp.add_argument("file", help="JSON file from Cookie-Editor/EditThisCookie")

    sub.add_parser("status", help="Check cookie cache freshness")

    q = sub.add_parser("query", help="Query Gemini Web")
    q.add_argument("prompt", help="Your question / prompt")
    q.add_argument("--model", default=DEFAULT_MODEL, choices=list(MODELS),
                   help="Model (default: %(default)s)")
    q.add_argument("--url", help="Include a URL for Gemini to read")

    s = sub.add_parser("search", help="AI-powered web search via Gemini")
    s.add_argument("query", help="Search query")
    s.add_argument("--model", default=DEFAULT_MODEL, choices=list(MODELS))

    e = sub.add_parser("extract", help="Extract readable content from a URL")
    e.add_argument("url", help="URL to extract")
    e.add_argument("--model", default=DEFAULT_MODEL, choices=list(MODELS))

    args = p.parse_args()

    if args.cmd == "import":
        import_cookies(args.file)

    elif args.cmd == "status":
        sys.exit(show_status())

    elif args.cmd == "query":
        print(query_gemini_with_retry(args.prompt, model=args.model, url=args.url))

    elif args.cmd == "search":
        prompt = (
            f"Search the web and answer with sources.\n\n"
            f"Query: {args.query}\n\n"
            "Format:\n## Answer\n<answer>\n\n"
            "## Sources\n<sources with URLs>"
        )
        print(query_gemini_with_retry(prompt, model=args.model))

    elif args.cmd == "extract":
        prompt = (
            "Extract the complete readable content from this URL as clean markdown. "
            "Include title, all text, code blocks, tables. Do not summarize — "
            "extract the full content."
        )
        print(query_gemini_with_retry(prompt, model=args.model, url=args.url))

    else:
        p.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
