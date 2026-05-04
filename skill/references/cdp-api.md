# CDP Proxy API 参考

## 基础信息

- 地址：`http://localhost:3456`
- 启动：`node ~/.claude/skills/web-access/scripts/cdp-proxy.mjs &`
- 启动后持续运行，不建议主动停止（重启需 Chrome 重新授权）
- 强制停止：`pkill -f cdp-proxy.mjs`

## API 端点

### GET /health
健康检查，返回连接状态。
```bash
curl -s http://localhost:3456/health
```

### GET /targets
列出所有已打开的页面 tab。返回数组，每项含 `targetId`、`title`、`url`。
```bash
curl -s http://localhost:3456/targets
```

### GET /new?url=URL
创建新后台 tab，自动等待页面加载完成。返回 `{ targetId }`.
```bash
curl -s "http://localhost:3456/new?url=https://example.com"
```

### GET /close?target=ID
关闭指定 tab。
```bash
curl -s "http://localhost:3456/close?target=TARGET_ID"
```

### GET /navigate?target=ID&url=URL
在已有 tab 中导航到新 URL，自动等待加载。
```bash
curl -s "http://localhost:3456/navigate?target=ID&url=https://example.com"
```

### GET /back?target=ID
后退一页。
```bash
curl -s "http://localhost:3456/back?target=ID"
```

### GET /info?target=ID
获取页面基础信息（title、url、readyState）。
```bash
curl -s "http://localhost:3456/info?target=ID"
```

### POST /eval?target=ID
执行 JavaScript 表达式，POST body 为 JS 代码。
```bash
curl -s -X POST "http://localhost:3456/eval?target=ID" -d 'document.title'
```

### POST /click?target=ID
JS 层面点击（`el.click()`），POST body 为 CSS 选择器。自动 scrollIntoView 后点击。简单快速，覆盖大多数场景。
```bash
curl -s -X POST "http://localhost:3456/click?target=ID" -d 'button.submit'
```

### POST /clickAt?target=ID
CDP 浏览器级真实鼠标点击（`Input.dispatchMouseEvent`），POST body 为 CSS 选择器。先获取元素坐标，再模拟鼠标按下/释放。算真实用户手势，能触发文件对话框、绕过部分反自动化检测。
```bash
curl -s -X POST "http://localhost:3456/clickAt?target=ID" -d 'button.upload'
```

### POST /setFiles?target=ID
给 file input 设置本地文件路径（`DOM.setFileInputFiles`），完全绕过文件对话框。POST body 为 JSON。
```bash
curl -s -X POST "http://localhost:3456/setFiles?target=ID" -d '{"selector":"input[type=file]","files":["/path/to/file1.png","/path/to/file2.png"]}'
```

### GET /scroll?target=ID&y=3000&direction=down
滚动页面。`direction` 可选 `down`（默认）、`up`、`top`、`bottom`。滚动后自动等待 800ms 供懒加载触发。
```bash
curl -s "http://localhost:3456/scroll?target=ID&y=3000"
curl -s "http://localhost:3456/scroll?target=ID&direction=bottom"
```

### GET /screenshot?target=ID&file=/tmp/shot.png
截图。指定 `file` 参数保存到本地文件；不指定则返回图片二进制。可选 `format=jpeg`。
```bash
curl -s "http://localhost:3456/screenshot?target=ID&file=/tmp/shot.png"
```

## /eval 使用提示

- POST body 为任意 JS 表达式，返回 `{ value }` 或 `{ error }`
- 支持 `awaitPromise`：可以写 async 表达式
- 返回值必须是可序列化的（字符串、数字、对象），DOM 节点不能直接返回，需要提取属性
- 提取大量数据时用 `JSON.stringify()` 包裹，确保返回字符串
- 根据页面实际 DOM 结构编写选择器，不要套用固定模板

## 错误处理

| 错误 | 原因 | 解决 |
|------|------|------|
| `Chrome 未开启远程调试端口` | Chrome 未开启远程调试 | 提示用户打开 `chrome://inspect/#remote-debugging` 并勾选 Allow |
| `attach 失败` | targetId 无效或 tab 已关闭 | 用 `/targets` 获取最新列表 |
| `CDP 命令超时` | 页面长时间未响应 | 重试或检查 tab 状态 |
| `端口已被占用` | 另一个 proxy 已在运行 | 已有实例可直接复用 |
| `Received network error or non-101` | WebSocket URL 缺少 UUID 后缀 | 已修复：从 `/json/version` 获取正确的 `webSocketDebuggerUrl` |

## 已知问题修复记录

### 2026-03-31: WebSocket 连接失败（已修复）

**现象**：Proxy 扫描端口后连接失败，报错：
```
[CDP Proxy] 连接错误: Received network error or non-101 status code.
```

**原因**：Chrome 的 WebSocket URL 必须带 UUID 后缀（如 `/devtools/browser/5ea4c5ff-...`），端口扫描时返回 `wsPath: null`，导致 Proxy 使用了错误路径 `/devtools/browser`

**解决**：在 `discoverChromePort()` 函数中，扫描到端口后从 `/json/version` 端点获取正确的 `webSocketDebuggerUrl`：
```javascript
const info = await fetch(`http://127.0.0.1:${port}/json/version`);
const wsPath = new URL(info.webSocketDebuggerUrl).pathname;
// wsPath = "/devtools/browser/5ea4c5ff-a9a0-4ed0-b8c8-52e78d6fbab5"
```

**已修复**：代码已更新，无需手动干预。

---

## Chrome 启动配置（固定）

**用户数据目录**：`D:\Playwright-Chrome-Profile`

**启动命令**（PowerShell）：
```powershell
# 先关闭所有 Chrome 进程
Stop-Process -Name chrome -Force -ErrorAction SilentlyContinue

# 用固定用户数据目录启动
Start-Process "C:\Program Files\Google\Chrome\Application\chrome.exe" `
  -ArgumentList "--remote-debugging-port=9222","--user-data-dir=D:\Playwright-Chrome-Profile"
```

**注意事项**：
- Windows 下启动 Chrome 带 CDP 参数时，**必须先完全关闭所有 Chrome 进程**
- 否则新实例会连接到已有进程，不会开启 CDP 端口
- 固定使用 `D:\Playwright-Chrome-Profile` 保持登录态一致
