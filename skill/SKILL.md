---
name: web-access
license: MIT
github: https://github.com/xuli500177/oh-my-web-access
description: "联网操作工具。当用户要求进行任何网络交互时触发。触发词：打开网页、访问网站、登录、抓取、爬取、浏览器操作、打开链接、看网页、网页截图、操作网页。触发场景：搜索信息、查看网页内容、访问需要登录的网站、操作网页界面、抓取社交媒体内容（小红书、微博、推特等）、读取动态渲染页面、以及任何需要真实浏览器环境的网络任务。特殊处理：GitHub 仓库自动 clone、YouTube 视频自动提取转录稿、PDF 自动提取文本。智能降级链：Readability → 结构化数据解析 → Jina → Gemini Web → Scrapling → CDP 浏览器。也适用于：Cloudflare 绕过、反爬页面、多页爬取、stealth 浏览。"
metadata:
  author: 右太极
  version: "3.0.1"
---

# web-access Skill

## 联网工具选择

**一手信息优于二手信息**。搜索引擎是信息发现入口，不是证明工具。找到来源后直接访问原文。

### 搜索

| 场景 | 工具 |
|------|------|
| 中文搜索 | **baidu-search 技能** |
| 英文/技术/学术 | **Exa MCP**：`python3 scripts/exa-search.py "query" [-n 5] [--content]` |
| AI 问答+引用 | **Gemini Web**：`python3 scripts/gemini-web.py search "query"` |
| 代码/文档 | **Exa MCP**（code_search）|

> **Gemini Sources 陷阱**：Gemini 返回的 URL 列表经常是编造的，不能直接引用，重要信息必须二次验证。

### 内容获取

**统一入口**：`python3 scripts/web-extract.py URL` 自动检测 URL 类型：

```bash
python3 scripts/web-extract.py https://github.com/owner/repo   # → git clone + tree
python3 scripts/web-extract.py https://youtube.com/watch?v=xxx  # → 转录稿
python3 scripts/web-extract.py https://example.com/article      # → 降级提取
python3 scripts/web-extract.py URL --method scrapling            # → 强制 Scrapling
python3 scripts/web-extract.py URL --method gemini               # → 强制 Gemini
python3 scripts/web-extract.py URL --save /tmp/out.md            # → 保存文件
```

#### 智能降级链

按顺序逐级尝试，成功即停：

```
① HTTP + Readability  → 快速 HTML 解析，适合静态页面
② 结构化数据解析     → data-* 属性、RSC flight、__NEXT_DATA__
③ Jina Reader        → 服务器端 HTML→MD（限 20 RPM）
④ Gemini Web 提取    → AI 读取，支持 JS/SPA（免费，需 cookies）
⑤ Scrapling          → 反爬绕过、Cloudflare、stealth 浏览
⑥ CDP 浏览器         → 最后手段（登录态/交互操作/截图）
```

**关键判断**：
- SPA 页面（React/Vue/Astro）→ 跳过 Jina，直接 Gemini Web
- Cloudflare/反爬拦截 → 跳到 Scrapling → `references/scrapling.md`
- 需要登录态或交互操作 → 跳到 CDP → `references/cdp-usage.md`

**Firecrawl**（可选，需 API key）：`FIRECRAWL_API_KEY` 环境变量。免费套餐一次性 500 次，非必需。

## 前置检查（CDP 模式时）

```bash
bash ~/.claude/skills/web-access/scripts/check-deps.sh
```

- **Node.js 22+**：必需（原生 WebSocket）
- **Chrome remote-debugging**：`chrome://inspect/#remote-debugging` 勾选允许

未通过则引导用户设置。通过后 CDP Proxy 自动启动。

## 已知陷阱

**Gemini Web 流式响应**：StreamGenerate 返回多个 chunk，解析时必须取**最后一个**（最完整的），否则内容截断。

**结构化数据解析局限**：`data-*` 属性只对 SSR 框架有效（Astro、SvelteKit）。纯客户端 SPA 需靠 Gemini Web 或 CDP。

**Jina 不执行 JS**：SPA 页面只能拿到壳。遇到 SPA 直接跳过，用 Gemini Web。

## 脚本索引

| 脚本 | 用途 |
|------|------|
| `scripts/web-extract.py` | 统一内容提取（自动检测 + 降级链） |
| `scripts/github-extract.py` | GitHub 仓库 clone + 目录树 |
| `scripts/youtube-extract.py` | YouTube 转录稿 + Gemini 分析 |
| `scripts/exa-search.py` | Exa MCP 搜索（免费） |
| `scripts/gemini-web.py` | Gemini Web 搜索/提取（免费） |
| `scripts/check-deps.sh` | CDP 环境检查 |
| `scripts/cdp-proxy.mjs` | CDP Proxy 服务 |
| `scripts/match-site.sh` | 站点经验匹配 |

### Gemini Web Cookie 管理

```bash
python3 scripts/gemini-web.py import /path/to/cookies.json  # 首次导入
python3 scripts/gemini-web.py status                         # 检查状态
```

Cookies 有效期数月，过期需重新导入。

## References 索引

按需加载，不会增加触发时的 context 负担。

| 文件 | 何时加载 |
|------|---------|
| `references/cdp-usage.md` | 需要 CDP 浏览器操作时（登录、交互、截图） |
| `references/cdp-api.md` | 需要 CDP API 详细参考、JS 提取模式时 |
| `references/scrapling.md` | 需要反爬绕过、Cloudflare、多页爬取时 |
| `references/methodology.md` | 需要浏览哲学、信息核实、并行调研策略时 |
| `references/site-patterns/{domain}.md` | 确定目标网站后，读取对应站点经验 |

**站点经验**：操作中积累的特定网站经验存储在 `references/site-patterns/` 下。CDP 操作成功后，如发现新模式，主动写入经验文件（只写验证过的事实）。
