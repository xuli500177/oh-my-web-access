# CDP 浏览器操作指南

通过 CDP Proxy 直连用户日常 Chrome，天然携带登录态，无需启动独立浏览器。

**原则**：不主动操作用户已有 tab，所有操作在自己创建的后台 tab 中进行。完成任务后关闭自己的 tab，保留用户 tab。

## 启动

```bash
bash ~/.claude/skills/web-access/scripts/check-deps.sh
```

脚本检查 Node.js、Chrome 端口，确保 Proxy 已连接（未运行则自动启动）。

## Proxy API

```bash
# 列出用户已打开的 tab
curl -s http://localhost:3456/targets

# 创建新后台 tab（自动等待加载）
curl -s "http://localhost:3456/new?url=https://example.com"

# 页面信息
curl -s "http://localhost:3456/info?target=ID"

# 执行任意 JS（读写 DOM、提取数据、操控元素、提交表单）
curl -s -X POST "http://localhost:3456/eval?target=ID" -d 'document.title'

# 截图
curl -s "http://localhost:3456/screenshot?target=ID&file=/tmp/shot.png"

# 导航、后退
curl -s "http://localhost:3456/navigate?target=ID&url=URL"
curl -s "http://localhost:3456/back?target=ID"

# 点击（CSS 选择器，JS click）
curl -s -X POST "http://localhost:3456/click?target=ID" -d 'button.submit'

# 真实鼠标点击（CDP dispatchMouseEvent，能触发文件对话框）
curl -s -X POST "http://localhost:3456/clickAt?target=ID" -d 'button.upload'

# 文件上传
curl -s -X POST "http://localhost:3456/setFiles?target=ID" \
  -d '{"selector":"input[type=file]","files":["/path/to/file.png"]}'

# 滚动（触发懒加载）
curl -s "http://localhost:3456/scroll?target=ID&y=3000"
curl -s "http://localhost:3456/scroll?target=ID&direction=bottom"

# 关闭 tab
curl -s "http://localhost:3456/close?target=ID"
```

## 操作模式

### 看 → 做 → 读

- **看**：`/eval` 查询 DOM，发现链接、按钮、表单、文本
- **做**：`/click` 点击、`/scroll` 滚动、`/eval` 填表
- **读**：`/eval` 提取文字、`/screenshot` 视觉识别

先了解页面结构，再决定下一步。

### 页面内导航

- **`/click`**：当前 tab 内点击，串行处理
- **`/new` + 完整 URL**：从 DOM 提取链接地址（保留所有查询参数），在新 tab 打开

站点自己生成的链接天然携带完整上下文，手动构造的 URL 可能缺失隐式参数。

### 媒体资源

内容在图片里时，用 `/eval` 从 DOM 拿图片 URL 再定向读取——比全页截图精准。公开资源直接下载；需登录态的才在浏览器内 navigate + screenshot。

## 技术事实

- DOM 中有大量已加载但未展示的内容（轮播非当前帧、折叠区块、懒加载占位），以数据结构为单位可以直接触达
- Shadow DOM 的 `shadowRoot`、iframe 的 `contentDocument` 是选择器不可跨越的边界，eval 递归遍历可穿透所有层级
- `/scroll` 到底部触发懒加载，提取图片前先滚动
- 密集打开大量页面（批量 `/new`）可能触发反爬风控
- "内容不存在"提示不一定反映真实状态，也可能是 URL 缺失参数或触发反爬

## 视频内容

通过 `/eval` 操控 `<video>` 元素（获取时长、seek、播放/暂停/全屏），配合 `/screenshot` 采帧。

## 登录判断

核心问题：**目标内容拿到了吗？**

先尝试获取内容。只有确认无法获取且登录能解决时，才告知用户：
> "当前页面在未登录状态下无法获取[具体内容]，请在你的 Chrome 中登录 [网站名]，完成后告诉我继续。"

登录后无需重启，直接刷新继续。

## 任务结束

用 `/close` 关闭自己创建的 tab，保留用户 tab。Proxy 持续运行，不主动停止。
