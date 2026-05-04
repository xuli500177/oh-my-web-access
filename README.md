# oh-my-web-access

A powerful web-access skill for Claude Code / Claude.ai / PI, featuring a **6-level intelligent fallback chain**, dedicated extractors for GitHub/YouTube/PDF, and full browser automation via CDP.

Based on the excellent [web-access](https://github.com/eze-is/web-access) by **[@一泽Eze](https://github.com/eze-is)**. This fork extends it with:

- 🧩 Layered architecture (SKILL.md < 120 lines, references/ loaded on-demand)
- 🕷️ **Scrapling** integration (stealth/Cloudflare bypass + Spider framework)
- 📦 Unified extraction with smarter fallback
- 🧠 Enhanced methodology (browse philosophy, parallel research, fact verification)

---

## Quick Start

```bash
# 1. Install dependencies
pip install yt-dlp pymupdf readability-lxml trafilatura firecrawl-py "scrapling[all]"

# 2. Clone into your skills directory
git clone https://github.com/YOUR_GITHUB/oh-my-web-access.git ~/.agents/skills/web-access

# 3. (Optional) Gemini Web setup — export cookies from browser
#    Use Cookie-Editor or EditThisCookie to export gemini.google.com cookies as JSON
python3 scripts/gemini-web.py import /path/to/cookies.json

# 4. (Optional) CDP browser setup
#    Open chrome://inspect/#remote-debugging → check "Allow remote debugging"
bash scripts/check-deps.sh
```

---

## Intelligent Fallback Chain

When extracting web content, it tries each method in order until one succeeds:

```
① Readability          → Fast HTML parsing (static pages)
② Structured Data      → data-* attrs, RSC flight, __NEXT_DATA__
③ Jina Reader          → Server-side HTML→Markdown (20 RPM limit)
④ Gemini Web           → AI-powered extraction, JS/SPA support (free)
⑤ Scrapling            → Stealth/Cloudflare bypass, multi-page crawling
⑥ CDP Browser          → Last resort (login, interactivity, screenshots)
```

Choose a specific method:
```bash
python3 scripts/web-extract.py URL --method scrapling
python3 scripts/web-extract.py URL --method gemini
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

Gemini Web is **free and unlimited** — no API key needed, just your browser session cookies.

1. Install the [Cookie-Editor](https://cookie-editor.cg.guide/) or [EditThisCookie](https://www.editthiscookie.com/) Chrome extension
2. Go to [gemini.google.com](https://gemini.google.com) and log in
3. Export cookies as JSON
4. Import:
   ```bash
   python3 scripts/gemini-web.py import cookies.json
   python3 scripts/gemini-web.py status
   ```

Re-import when cookies expire (typically after several months).

---

## Scrapling (Anti-bot / Cloudflare Bypass)

Scrapling provides three fetch strategies and a Spider framework for multi-page crawling.

### Three Fetch Modes

```python
from scrapling.fetchers import Fetcher, DynamicFetcher, StealthyFetcher

# Static page
page = Fetcher.get('https://example.com')

# JS-rendered page
page = DynamicFetcher.fetch('https://example.com', network_idle=True)

# Cloudflare / anti-bot
page = StealthyFetcher.fetch('https://protected.com', solve_cloudflare=True)
```

### CLI

```bash
# Cloudflare bypass
scrapling extract stealthy-fetch 'https://protected.com' out.md --solve-cloudflare

# JS rendering
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

> **Note**: Full installation required: `pip install "scrapling[all]" && scrapling install`

---

## CDP Browser Automation

Control the user's local Chrome directly — no separate browser needed, session cookies work automatically.

```bash
# List open tabs
curl -s http://localhost:3456/targets

# Open a new tab
curl -s "http://localhost:3456/new?url=https://example.com"

# Run JavaScript (read DOM, extract data, interact)
curl -s -X POST "http://localhost:3456/eval?target=TARGET_ID" -d 'document.title'

# Screenshot
curl -s "http://localhost:3456/screenshot?target=TARGET_ID&file=/tmp/shot.png"

# Click, scroll, navigate, close
curl -s -X POST "http://localhost:3456/click?target=TARGET_ID" -d '.button'
curl -s "http://localhost:3456/scroll?target=TARGET_ID&direction=bottom"
curl -s "http://localhost:3456/navigate?target=TARGET_ID&url=https://example.com"
curl -s "http://localhost:3456/close?target=TARGET_ID"
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
└── scripts/               → Standalone executables
```

---

## Credits

This project is a **fork and extension of [web-access](https://github.com/eze-is/web-access)** by **[@一泽Eze](https://github.com/eze-is)**. The original skill provided the foundation for the 6-level fallback chain, CDP integration, and the unified extraction philosophy. All credit for the core architecture belongs to 一泽.

This fork adds layered loading, Scrapling integration, and enhanced methodology documentation.

---

## License

MIT