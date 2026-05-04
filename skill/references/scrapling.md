# Scrapling — 反爬绕过与多页爬取

[Scrapling](https://github.com/D4Vinci/Scrapling) 提供三种抓取策略（HTTP、动态 JS、Stealth/Cloudflare）和 Spider 框架。

**适用场景**：
- Cloudflare Turnstile / 反爬保护的页面
- 需要浏览器伪装（impersonate）的 HTTP 请求
- 多页爬取 + 断点续爬
- Gemini Web 和 Jina 都搞不定的顽固页面

**不适用**：普通页面（用降级链前 ①②③④ 就够了）、需要登录态（用 CDP）

## 安装

```bash
pip install "scrapling[all]"   # 完整安装（含浏览器）
scrapling install               # 安装浏览器引擎

# 最小安装（仅 HTTP，无浏览器）
pip install scrapling
```

## 三种抓取方式

| 方式 | 类 | 用时 |
|------|---|------|
| HTTP | `Fetcher` | 静态页面、API、批量请求 |
| Dynamic | `DynamicFetcher` | JS 渲染内容 |
| Stealth | `StealthyFetcher` | Cloudflare、反爬保护 |

## CLI 用法

```bash
# 静态页面
scrapling extract get 'https://example.com' output.md

# 带 CSS 选择器 + 浏览器伪装
scrapling extract get 'https://example.com' output.md \
  --css-selector '.content' --impersonate 'chrome'

# JS 渲染页面
scrapling extract fetch 'https://example.com' output.md \
  --css-selector '.dynamic-content' --network-idle

# Cloudflare 保护页面
scrapling extract stealthy-fetch 'https://protected.com' output.html \
  --solve-cloudflare --block-webrtc --hide-canvas

# POST 请求
scrapling extract post 'https://api.example.com' output.json \
  --json '{"query": "search term"}'
```

输出格式由扩展名决定：`.html` / `.md` / `.txt` / `.json`

## Python 用法

### HTTP 抓取

```python
from scrapling.fetchers import Fetcher

page = Fetcher.get('https://example.com')
quotes = page.css('.quote .text::text').getall()
```

### Session（持久 Cookies）

```python
from scrapling.fetchers import FetcherSession

with FetcherSession(impersonate='chrome') as session:
    page = session.get('https://example.com/', stealthy_headers=True)
    links = page.css('a::attr(href)').getall()
```

### JS 渲染

```python
from scrapling.fetchers import DynamicFetcher

page = DynamicFetcher.fetch('https://example.com', headless=True)
data = page.css('.js-loaded-content::text').getall()

# 等待特定元素
page = DynamicFetcher.fetch('https://example.com',
    wait_selector=('.results', 'visible'), network_idle=True)
```

### Stealth / Cloudflare 绕过

```python
from scrapling.fetchers import StealthyFetcher

page = StealthyFetcher.fetch('https://protected-site.com',
    headless=True, solve_cloudflare=True,
    block_webrtc=True, hide_canvas=True)
content = page.css('.protected-content::text').getall()
```

### 自动化操作

```python
from playwright.sync_api import Page
from scrapling.fetchers import DynamicFetcher

def scroll_and_click(page: Page):
    page.mouse.wheel(0, 3000)
    page.wait_for_timeout(1000)
    page.click('button.load-more')
    page.wait_for_selector('.extra-results')

page = DynamicFetcher.fetch('https://example.com', page_action=scroll_and_click)
```

## Spider 框架（多页爬取）

```python
from scrapling.spiders import Spider, Response

class QuotesSpider(Spider):
    name = "quotes"
    start_urls = ["https://quotes.toscrape.com/"]
    concurrent_requests = 10
    download_delay = 1

    async def parse(self, response: Response):
        for quote in response.css('.quote'):
            yield {
                "text": quote.css('.text::text').get(),
                "author": quote.css('.author::text').get(),
            }
        next_page = response.css('.next a::attr(href)').get()
        if next_page:
            yield response.follow(next_page)

result = QuotesSpider().start()
result.items.to_json("quotes.json")
```

**断点续爬**：Ctrl+C 暂停，重新运行自动从 checkpoint 恢复。

## 元素选择

```python
page.css('h1::text').get()              # 第一个 h1 文本
page.css('a::attr(href)').getall()      # 所有链接
page.xpath('//div[@class="x"]/text()')  # XPath
page.find_all('div', class_='quote')    # 按属性查找
page.find_by_text('Read more', tag='a') # 按文本查找
page.find_by_regex(r'\$\d+\.\d{2}')    # 按正则查找
```

## 注意事项

- **浏览器依赖**：`pip install "scrapling[all]"` 后必须运行 `scrapling install`，否则 DynamicFetcher/StealthyFetcher 会失败
- **超时单位**：DynamicFetcher/StealthyFetcher 超时是**毫秒**（默认 30000），Fetcher 超时是**秒**
- **Cloudflare 绕过**：`solve_cloudflare=True` 增加 5-15 秒，仅在需要时启用
- **资源占用**：StealthyFetcher 运行真实浏览器，限制并发
- **法律合规**：遵守 robots.txt 和网站 ToS
- **Python 版本**：需要 3.10+
