# 治理解惑入口：砍托盘 GUI，改走 MCP + Skill

> **次要。** 主指导是 [GOVERNANCE-PACK.md](GOVERNANCE-PACK.md)（治理包 + 反向开发）。本文只处理窗口皮肤；未完成治理包 P1/P2 前，不把砍 GUI 当主线。
> 地位：实施前给市长看的 GUI 退役说明，**本文件落地不等于已经砍掉 GUI**。
> 依据：市长代理之后驾驶舱可有可无；有问题走 Git；人问「现在怎样」由 MCP 供数、Skill 让 AI 画给人看。
> 作者：grok，2026-09-14。未过市长点头前，不删 `src/ag2c_gui`。

---

## 1. 要解决什么

AG2C 现在有三套「让人看见治理」的面：

| 面 | 现在干什么 | 问题 |
|---|---|---|
| Git 门禁 | 脏正本、verify 不过、不合入 | 真正的执法，应保留 |
| 托盘 GUI（Hello ImGui） | 首页任务/异常/健康度、文件树、MCP 检测、digest 轮询 | 市长代理开着后，不看也无所谓；维护成本高（崩溃日志、Job Object、热更新、画布已砍过一轮） |
| MCP | 任务、orient、evidence、普查、卡片 | 数已经在，但没有规定 AI **怎么用人话答用户** |

目标主路径改成：

```
用户问 AI「现在怎样 / 要我处理什么」
    → AI 按解惑 Skill 调 MCP
    → 用人话（必要时用 Markdown 结构图）答
有问题 → Git 拦住（提交失败、副本合不进去）
不看窗口 → 治理照样转
```

GUI 不再是治理驾驶舱。AG2C 这个软件也可以不再以桌面窗口为产品主界面。

---

## 2. 砍什么

**驾驶舱职责全部退役**，不是先藏窗口留后台。

计划删除或停用（实施阶段，不在写本文档这一刀）：

- `src/ag2c_gui/` 整包：tray、imgui、dashboard 绘制、desktop HTTP 小服务、Win32 标题栏等
- `packaging/windows/tray.py`、`start-tray.bat` 一类启动器
- 场景检查 `check.knowledge.ag2c-gui` → `scripts/check_desktop_boot.py`（「托盘能起来」不再是产品过关条件）
- `tests` 里 `gui` 套件（`test_dashboard.py` 等）以及 `tests/suites.py` 的 `gui` 条目
- README / ADOPTION / CONTRIBUTING 里「打开托盘」作为主入口的句子

**从 GUI 里要留下、给 MCP/Skill 用的数据层（不画图）：**

- `ag2c_gui.graph` / `graph_build` 里 agent 已经在用的谱系索引、治理图构建——若仍被 MCP 或 CLI 引用，迁到 `src/ag2c/`（例如 `ag2c/graph.py`），**不随 imgui 一起删**
- `management.project_details`、`dashboard_model` 若只是纯函数拼「当前任务 / 异常 / 健康度」，可迁到 `ag2c/briefing.py`，给解惑 Skill 当单一读口

托盘曾经做过、MCP 已有替代的：覆盖度打标、rehome 拖拽、复制提示词——保持 MCP，不搬回窗口。

---

## 3. 留什么（治理本体不动）

这些**不是 GUI**，砍窗口时不准顺手拆：

- Git hook、worktree、verify、finish、账本
- 门外 `policy.json`：知识卡片、checkers、绑定
- 检测脚本（AG2C 自己的 `tests/`；外管项目的治理包另说）
- 市长代理：`auto_warning` / `auto_census` / `auto_settle` 等
- MCP 服务器与现有工具（orient、task_list、evidence、guard、census、seed status 等）
- CLI：`ag2c seed status`、`ag2c evidence`、`ag2c task list`

执法者仍是 Git。MCP 只解惑、不代替 hook。这句话写在现有 `MCP_INSTRUCTIONS` 里，解惑 Skill 必须重复：Connecting MCP does not replace pre-commit.

---

## 4. 解惑 Skill 准备怎么做

新增打包 Skill，建议 id：`ag2c-status-brief`（中文职责：治理解惑）。

安装方式与现有技能相同：源在 `src/ag2c/skills/ag2c-status-brief/SKILL.md`，MCP `instructions` 里加一句「用户问状态时读这个 skill」，资源 `ag2c://skill/ag2c-status-brief`。

### 4.1 何时启用

用户问类似：

- 现在在干什么
- 有什么要我处理
- 种子/检查单什么状态
- 上一刀合进去没有
- 沙箱/副本还在吗
- 卸掉 AG2C 会怎样（指向零副作用：档案在门外，源码在 Git）

不问状态、正在改代码时，仍走 `ag2c-governed-development`，不要用解惑 Skill 代替施工路由。

### 4.2 AI 必须先拉的数（只读 MCP，不编）

按这个顺序调，缺的跳过并标明「没问到」：

1. `ag2c_guard_status` — 管不管、正本脏不脏、有没有未关任务
2. `ag2c_task_orient` — 当前阶段、画像、下一步该调哪个工具
3. `ag2c_task_list` — 进行中 / 已验证未合 / 半成品 worktree
4. `ag2c_evidence`（若用户点了某次任务）
5. CLI 或后续 briefing 读口：`ag2c seed status`（phase / sower / trusted）

禁止用聊天记忆代替上述输出。禁止说「应该都好了」而不引用工具结果。

### 4.3 画给人看的固定版式

用 Markdown，不要 GUI。建议四块，空块写「无」：

```markdown
## 现在
- 项目：<根路径>  托管：是/否
- 正本：干净 / 脏（脏且无任务 = 可能绕开治理，必须写红）
- 当前任务：无 / <id> <阶段> <一句话 goal>

## 要你处理（仅判断题）
- 无
- 或：合不回去某刀 / 认不认账单 / 要不要继续拆 / 警告已升级

## 机器在干的（不用你看）
- 代理已 settle / 普查 / 认警告
- verify 在跑（给任务 id）

## 检查单（立法）
- 种子：planted|mapped|growing|sliced  播种者：…  可信：是/否
- 地图 structured 只表示有卡片，不是已经长成
```

必要时再跟一张纯文本结构图（房间 → 绑了哪条 checker），数据来自 lineage/briefing，不手画假谱系。

### 4.4 明确不是解惑入口的事

- 不代替 verify、不代替 finish
- 不在解惑时改 policy、不手改 JSON
- 不把 GUI 截图当证据
- 全量清算仍要用户明说才准开

---

## 5. MCP 要不要加新工具

**第一刀 Skill 可以不新加工具**：现有 orient + list + guard + evidence 够拼出 4.3 的版式。

若拼出来又臭又长，再加只读聚合（实施后期，单独任务）：

- 建议名：`ag2c_brief`（或 CLI `ag2c brief`）
- 输入：`cwd`
- 输出：正好是 4.3 四块的 JSON，供 Skill 渲染
- 内部只组合已有函数（`guard_status`、任务列表、`assess_seed`、pending settle、stale cards），不写档案

有 `ag2c_brief` 之前，Skill 规定 AI 自己组合。有了之后，Skill 改为「先 brief，不够再点查」。

---

## 6. 分几刀做（你点头后才开工）

| 顺序 | 做什么 | 完成长什么样 | 不做什么 |
|---|---|---|---|
| 本文档 | 只写指导 | 你能接受或打回 | 不删 GUI |
| 第 1 刀 | Skill `ag2c-status-brief` + MCP instructions 一句路由 | 用户说「现在怎样」，AI 按版式答；有 unittest 或固定夹具断言版式字段 | 不删 imgui |
| 第 2 刀（可选） | `ag2c brief` / `ag2c_brief` | 一次调用给出四块 JSON | 不改执法 |
| 第 3 刀 | 退役 GUI：迁走 graph/briefing 纯函数，删 `ag2c_gui`、托盘启动器、desktop boot 场景、gui 测试套件，改 README 入口为 MCP | `python -c "import ag2c_gui"` 失败；`check.knowledge.ag2c-gui` 不存在；`ag2c mcp` 与 hook 仍绿 | 不删卡片/checkers/tests |
| 第 4 刀 | ADOPTION / 用户指南：主入口是编辑器里的 MCP，不是托盘 | 新用户文档不再教开窗口 | 不改治理包模型 |

第 3 刀必须 **touches_verification**：产品与「桌面能起来」这条场景检查一起消失。

---

## 7. 和「治理包 / 零副作用」怎么对齐

砍 GUI **不改变**立法在门外、考卷可外挂、源码默认可不改。

- 卡片、checkers：仍在项目档案 `policy.json`
- 用户问「现在怎样」：解惑读档案 + Git 状态，不读托盘
- 卸掉 AG2C：MCP 和 Skill 安装也会走，Git 钩子卸掉；用户仓库里仍不应留下 `.ag2c` 或托盘配置作为产品依赖

GUI 本来就不是治理包的一部分，是 AG2C 这个软件多出来的窗户。砍窗 = 软件变瘦，治理包形状不变。

---

## 8. 风险

- **没有窗口之后，不会用 MCP 的人会觉得「没东西」。** 缓解：Skill 规定 AI 主动用 4.3 答；ADOPTION 第一屏改成「在 Cursor/Grok 里说话」。
- **desktop boot 一删，少了一条「真进程起来」的产品检查。** 替代产品事实应是：MCP initialize 成功、hook 能拒绝一次提交（已有 first-drill 金丝雀），而不是窗口。
- **graph 纯函数若误删，谱系 MCP 会瞎。** 第 3 刀先迁再删，用现有 `CanvasRemovalTests` 同类断言：imgui 符号死、索引还在。
- **代理已让人不看窗，但不等于状态可问。** 所以 Skill 要先于删 GUI 落地，否则中间真空。

---

## 9. 不做（除非另说）

- 不把用户项目接到 AG2C 源码树下
- 不在本指导任务里删除任何 GUI 代码
- 不把解惑做成第二个驾驶舱网页
- 不让 MCP 代替 Git hook
- 不把 AG2C 自己的 `tests/` 搬进外挂包来「演」零副作用
- 不在解惑 Skill 里做 sow / flatten / 合入

---

## 10. 请你拍板的三件事

1. **Skill 是否必须先于删 GUI？** 本文建议是（第 1 刀 → 第 3 刀）。若你要一次砍净，会有一段时间只能自己跑 CLI。
2. **要不要 `ag2c_brief` 聚合工具？** 建议第 1 刀不做，用着拼得烦再加。
3. **graph/dashboard 纯函数迁到 `ag2c/` 是否同意？** 不同意则第 3 刀要另定「谱系数据从哪读」。

你点头「按第 1 刀开始」或改这三问之后，再开实施任务。
