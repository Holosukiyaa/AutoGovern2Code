# UI 搬迁：Hello ImGui → WebView2（保留现有布局）

> 地位：窗口皮肤怎么换。治理包仍是主线，见 [GOVERNANCE-PACK.md](GOVERNANCE-PACK.md)。
> 换壳已落地：产品窗口是 WebView2。Hello ImGui Python 与 NOTICE 已从树里删掉。
> 作者：grok，2026-09-14。市长要求：真窗口、AI 好改样式、布局保持现在满意的那套。

---

## 1. 为何换

原先的托盘是 Hello ImGui：每帧自绘、自己的窗口循环，Windows 不把它当正经应用。所以卡，也吃不到系统给 HWND 的合成、DPI、贴靠。

换成 **WebView2**：系统 WebView 控件嵌在真窗口里。样式是 HTML/CSS，AI 训练数据最多，改布局不用碰 Python 执法核。Win10（装了 Evergreen Runtime）和 Win11 都能用。

不换成 WinUI 3：AI 对 WinUI 不熟。不换成 Electron：重、再打一份 Chromium。WebView2 用机上已有的 Edge 内核。

---

## 2. 搬什么、不搬什么

**只换壳，不换信息架构。** 现有四块必须一对一还在：

| 现 ImGui 窗 | dock | 搬过去 |
|---|---|---|
| 首页 | 中央主台 | 市长桌：要你处理 / 系统警情 / 记录（可折） |
| 文件树 | 左约 42% | 覆盖树、筛选、点文件 |
| 检查器 | 右约 32% | 选中文件/卡的说明 |
| 运维 | 下约 30% | 四个页：操作日志、施工、实际记录、AI 入口（MCP 链接） |

顶栏：项目、门禁条、刷新。暗色。能复制提示词、复制 MCP 入口。

**数据层不动：**

- `desktop.py` 本地 HTTP（`127.0.0.1` + `X-AG2C-Token`）
- `dashboard_model` / `custody_model` / `coverage_rows` / `inspect_*` / `graph_build`
- Python 执法核、MCP、hook

页面只 `fetch` 现有 `/api/status`、`/api/projects`、`/api/project/details`、digest 轮询。缺的 JSON 再加只读字段，不把治理写进前端。

**已删：** `imgui_tray.py`、`imgui_panels.py`、`imgui_runtime.py`、`tray_caption_win32.py`、imgui_bundle 依赖与 `NOTICE-imgui.txt`。`tray_host.py` 里无 toolkit 的部分留下给 WebView 宿主用。

---

## 3. 技术形态

```
packaging/windows 启动
  → 小宿主（真 HWND + WebView2）
  → 打开本地 UI（file:// 或宿主注入的 127.0.0.1 静态页）
  → fetch 同一套 desktop API（带 token）
```

宿主建议：**pywebview（Windows 后端就是 WebView2）**，和现有 Python 进程在一起，少一条 C# 工程。便携包打 WebView2 Evergreen bootstrapper 或声明「需已装 Edge WebView2」。

静态页建议目录：`src/ag2c_gui/web/`（`index.html`、`layout.css`、`app.js`）。无 React/Vue 构建步，AI 直接改 CSS。需要组件时再用极少原生 JS。

安全：继续只绑 127.0.0.1；token 仍 header；CSP 收紧（`default-src 'self'`，只允许连 desktop 端口）。页面不执行用户项目代码。

Win10：最低 Win10 1809 + WebView2 Runtime。没有 Runtime 时启动应说人话并给下载链，不要黑屏。

---

## 4. 布局怎么「照搬」

CSS Grid 对应现在的 dock 比例，不要改成手机风单栏（除非窗口极窄再叠）。

```
grid-template:
  "bar  bar  bar"  auto
  "tree home inspect" 1fr
  "ops  ops  ops"  minmax(10rem, 30%)
 / 42%  1fr  32%
```

窄于约 900px：树和检查器改抽屉，首页仍主台——这是唯一允许的响应式，不是新 IA。

首页分区顺序与 `dashboard.py` 一致：先「要你处理」，再「系统警情」，再折叠「记录」。文案沿用现有中文，不要重新发明一套产品语言。

颜色：现有绿/琥珀/红语义（决策、警情、正常）迁到 CSS 变量，便于以后 AI 改主题而不改结构。

---

## 5. 分几刀（点头后）

| 刀 | 做什么 | 完成长什么样 |
|---|---|---|
| W1 壳 | pywebview 开窗，加载空白页，能打到 `/api/status`（token） | 真 HWND；任务管理器里是应用不是 imgui 渲染器 |
| W2 首页 | HTML 渲染 `dashboard_model` 同构 JSON | 要你处理 / 警情 / 记录 三条区都在；无项目时仍能画空态 |
| W3 树+检查器 | 左树右检，点击联动 | 点文件出检查器字段，与现 inspect 键一致 |
| W4 运维四页 | 日志 / 施工 / 记录 / MCP 入口 | 复制 MCP 文案仍可用 |
| W5 退役 imgui | 启动改走 web 壳；删 imgui_*；gui 测试改打 WebView 或打「API+静态页」 | `import imgui_bundle` 不再是运行时依赖；desktop boot 改为「宿主进程 + 本机 API 200」 |

W5 才动 `check.knowledge.ag2c-gui`。W1–W4 期间两壳可并存（旧托盘、新窗），避免真空。

产品检查建议改为：进程起来、本机 `/api/status` 返回 200、静态 `index.html` 存在。不要再要求 ImGui 帧循环。

---

## 6. 和另两份文档的关系

- **GOVERNANCE-PACK.md**：主线仍是治理包与反向开发。本搬迁是皮肤，不挡 P1。
- **GUI-RETIREMENT.md**：原「砍窗、只留 MCP」。现修正为：**砍 ImGui，换成 WebView2**；MCP + Skill 仍作解惑主路径，窗是可瞟一眼的只读壳，不代替 Git 门。
- **SELF-GOVERNANCE-FRICTION F4**：文档切片绑桌面启动，W5 换检查定义后可一并消。

合入、改卡、sow 仍禁止做在网页里当主路径（可放「复制给 AI 的提示词」按钮，与现在一样）。

---

## 7. 不做

- 不把用户项目接到 AG2C 源码树
- 不在前端写 policy
- 不上 Electron / 不强制 WinUI 3
- 不在本指导任务里删 imgui 或加 `web/` 目录
- 不把首页改成图表驾驶舱或新信息架构

---

## 8. 请你拍板

1. 宿主用 **pywebview** 是否同意？（不同意则改小 C# WebView2 壳）
2. 是否 **W1–W4 与旧托盘并存**，W5 再切启动器？
3. 本搬迁与治理包 P1 **并行**还是 **P1 之后**？建议并行：壳不碰立法。

点头后从 W1 开任务。
