# oh-my-web-access

A powerful web-access skill for Claude Code / Claude.ai / PI, featuring a **6-level intelligent fallback chain**, dedicated extractors for GitHub/YouTube/PDF, and full browser automation via CDP.

## Highlights

- **🎯 Layered Loading** — SKILL.md is only 114 lines. Detailed guides (CDP API, Scrapling, methodology) live in `references/` and load on-demand. Triggers stay lean, saving tokens.
- **🧠 Gemini Web (Free)** — Uses your browser's cached Google cookies to let Gemini read any URL directly. No API key, no limits, handles JS/SPAs. A powerful weapon against anti-bot pages.
- **🕷️ Scrapling Integration** — Stealth/Cloudflare bypass + Spider framework for multi-page crawling. Fills the gap between Gemini Web and CDP.
- **🔗 Smart Fallback Chain** — 6 levels deep. Lightweight for static pages, escalates automatically for stubborn ones.

---

## Quick Start

```bash
# Install dependencies
pip install yt-dlp pymupdf readability-lxml trafilatura firecrawl-py "scrapling[all]"

# Clone into your skills directory
git clone https://github.com/YOUR_GITHUB/oh-my-web-access.git ~/.agents/skills/web-access

# (Optional) Gemini Web — export cookies from browser
python3 scripts/gemini-web.py import /path/to/cookies.json
python3 scripts/gemini-web.py status

# (Optional) CDP browser setup
bash scripts/check-deps.sh
```

---

## Intelligent Fallback Chain

```
① Readability          → Fast HTML parsing (static pages)
② Structured Data      → data-* attrs, RSC flight, __NEXT_DATA__
③ Jina Reader          → Server-side HTML→Markdown (20 RPM limit)
④ Gemini Web           → AI-powered extraction, JS/SPA support (free)
⑤ Scrapling            → Stealth/Cloudflare bypass, multi-page crawling
⑥ CDP Browser          → Last resort (login, interactivity, screenshots)
```

```bash
python3 scripts/web-extract.py URL --method scrapling   # Force Scrapling
python3 scripts/web-extract.py URL --method gemini       # Force Gemini Web
python3 scripts/web-extract.py URL --save /tmp/out.md    # Save to file
```

---

## Scripts

| Script | Purpose |
|--------|---------|
| `web-extract.py` | **Unified entry point** — auto-detects URL type + fallback |
| `github-extract.py` | Clone repo + directory tree + README |
| `youtube-extract.py` | Transcript + Gemini visual analysis |
| `exa-search.py` | Exa MCP search (free, 1000/month) |
| `gemini-web.py` | Gemini Web search & extraction (free, needs cookies) |
| `check-deps.sh` | CDP environment check |
| `cdp-proxy.mjs` | CDP proxy service |

---

## Gemini Web Cookie Setup

Gemini Web is **free and unlimited** — no API key, just your browser session cookies.

1. Install [Cookie-Editor](https://cookie-editor.cg.guide/) or [EditThisCookie](https://www.editthiscookie.com/)
2. Visit [gemini.google.com](https://gemini.google.com) and log in
3. Export cookies as JSON
4. Import:
   ```bash
   python3 scripts/gemini-web.py import cookies.json
   ```
   Re-import when cookies expire (typically months).

---

## Scrapling (Anti-bot / Cloudflare Bypass)

### Three Fetch Modes

```python
from scrapling.fetchers import Fetcher, DynamicFetcher, StealthyFetcher

page = Fetcher.get('https://example.com')                                     # Static
page = DynamicFetcher.fetch('https://example.com', network_idle=True)        # JS rendering
page = StealthyFetcher.fetch('https://protected.com', solve_cloudflare=True)  # Cloudflare
```

### CLI

```bash
scrapling extract stealthy-fetch 'https://protected.com' out.md --solve-cloudflare
scrapling extract fetch 'https://example.com' out.md --network-idle --css-selector '.content'
```

### Spider (Multi-page Crawling)

```python
from scrapling.spiders import Spider, Response

class MySpider(Spider):
    name = "myspider"
    start_urls = ["https://example.com/"]
    concurrent_requests = 5
    download_delay = 1

    async def parse(self, response: Response):
        for item in response.css('.item'):
            yield {"title": item.css('h2::text').get()}
        next_page = response.css('.next::attr(href)').get()
        if next_page:
            yield response.follow(next_page)

result = MySpider().start()
result.items.to_json("output.json")
```

> Full install: `pip install "scrapling[all]" && scrapling install`

---

## CDP Browser Automation

Control the user's local Chrome directly — no separate browser instance needed, session cookies work automatically.

```bash
curl -s http://localhost:3456/targets                                          # List tabs
curl -s "http://localhost:3456/new?url=https://example.com"                     # New tab
curl -s -X POST "http://localhost:3456/eval?target=ID" -d 'document.title'      # JS eval
curl -s "http://localhost:3456/screenshot?target=ID&file=/tmp/shot.png"         # Screenshot
curl -s -X POST "http://localhost:3456/click?target=ID" -d '.button'            # Click
curl -s "http://localhost:3456/scroll?target=ID&direction=bottom"               # Scroll
curl -s "http://localhost:3456/close?target=ID"                                # Close tab
```

---

## Skill Architecture

```
skill/
├── SKILL.md (core — < 120 lines, always loaded)
├── references/
│   ├── cdp-usage.md       → Loaded when CDP operations needed
│   ├── cdp-api.md         → Loaded for CDP API reference
│   ├── scrapling.md       → Loaded for anti-bot / Cloudflare
│   ├── methodology.md     → Loaded for browse philosophy / parallel research
│   └── site-patterns/     → Per-site experience (auto-built)
scripts/                   → Standalone executables
```

---

## Inspired by

[web-access](https://github.com/eze-is/web-access) by [@一泽Eze](https://github.com/eze-is) — the original skill that pioneered the 6-level fallback chain and CDP integration.

---

## License

MIT