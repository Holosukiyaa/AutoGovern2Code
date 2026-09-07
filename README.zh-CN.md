# AutoGovern2Code（AG2C）

**照常使用你的编程 AI。工程治理由 AG2C 在背后完成。**

[![Release](https://img.shields.io/github/v/release/Holosukiyaa/AutoGovern2Code)](https://github.com/Holosukiyaa/AutoGovern2Code/releases/latest)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

[English](README.md) · [接入说明](docs/ADOPTION.md) · [架构](docs/ARCHITECTURE.md) · [Releases](https://github.com/Holosukiyaa/AutoGovern2Code/releases/latest)

当前版本：**v0.9.0**（2026-09-07）。Alpha。仅 Windows。单人、本机。

AutoGovern2Code 是一层本地、开源的 AI 编程治理工具。把 Git 工程加入一次即可。AI 入口只有两件事：通用 MCP 连接说明（占位符，不绑厂商、不写本机路径）和 **检测 MCP**。Skill 全文在 MCP 里。施工在工程外的 Git worktree，运行项目自己的检查，只把验证过的提交 fast-forward 回原分支。完整证据留在这台电脑上。

用户工程里不会出现 `.ag2c` 目录，不会由 AG2C 生成 `AGENTS.md` 或 `CLAUDE.md`，也不会混入治理凭证。产品的构建和运行永远不依赖 AG2C。

## Windows 怎么安装

需要 Windows 10/11 x64，不需要 Python。托盘是 Dear ImGui 窗口（Hello ImGui 停靠壳），不嵌入 Edge，也不再用 PySide/Qt。便携版是一个文件夹：exe、`git\`、`data\`。旁边放 `portable.ini`（或加 `--portable`）就不会写 PATH、开始菜单、开机启动。自带的 MinGit 优先于系统 Git。

1. 从[最新 GitHub Release](https://github.com/Holosukiyaa/AutoGovern2Code/releases/latest)下载 `AutoGovern2Code-Setup-Windows-x64.exe`。
2. 双击安装。安装器只写入当前用户，会加入开始菜单，并启动托盘程序。
3. 从托盘或开始菜单打开 AG2C，点击「添加项目」，选择一个非空的 Git 工程。
4. 在托盘点一次「检测 MCP」（或运行 `ag2c mcp health`）。需要时复制通用连接说明。新开一轮对话后，继续像以前一样提开发需求。

托盘程序会随 Windows 启动。关掉窗口只是缩回托盘；已经纳管工程的 Git 交付门禁仍然生效。

社区安装器目前没有代码签名，Windows SmartScreen 可能会警告。请只从本仓库下载，先按 `SHA256SUMS.txt` 核对文件，再选择「更多信息 > 仍要运行」。下载的 Git 仍是独立的 GPL-2.0 程序，放在 `%LOCALAPPDATA%\AutoGovern2Code\runtime\git`。AG2C 操作用这份 MinGit；工程自己的 `.git` 和历史不动。

## 加入工程之后能看到什么

桌面窗口是普通用户的主界面。每个工程会显示：

- **AI 入口**：通用 MCP 连接说明 + 健康检测。本机 stdio 服务带上 Skill 全文和活工具。提示词不写厂商名，也不写用户路径。Git hook 是否接通算在检测 MCP 里，托盘不再单独显示「交付 / 已控制」。
- **实际记录**：已经完成的任务、它们实现或修复了什么，以及这次是不是流程交付完成。
- **施工副本、治理日志、最近证据**：进行中的 worktree、带版本的日志、本机凭证。
- **停止治理 / 恢复治理 / 卸载项目**：停止后项目仍留在列表并保留档案；恢复不必重新纳管；卸载才会删除该工程的治理档案。

施工检查通过，不等于产品已经验收。在工程声明公开契约或边界/场景检查之前，产品状态会保持 **未登记**。Knowledge 过期或冲突时，即使流程已经走完，也不能当成产品通过。

## 后台实际做了什么

```text
用户正常提出开发需求
  -> 连接一次 AG2C MCP；工具和 Skill 全文随会话到达
  -> AG2C 在写入前确定责任范围
  -> AI 只在工程外的 Git worktree 施工
  -> 最终范围按实际 diff 重新计算
  -> 运行工程自己的测试和检查
  -> 把证据绑定到最终提交的精确内容
  -> 只把验证过的提交 fast-forward 合回原分支
  -> 托盘展示结果与本机记录
```

正式工作副本不干净、分支已前进但施工副本没有刷新、检查失败、修改超出治理范围或证据过期，都会阻止交付。AI 先失败再修好的过程会保留，不会只留下一个「成功」。

如果任务还开着时原分支已经前进，需要把施工副本刷新到当前 HEAD 再验证，或者废弃该副本。

## 治理数据放在哪里

Windows 默认位置：

```text
%LOCALAPPDATA%\AutoGovern2Code\
  projects.json
  projects\<工程标识>\
```

策略、索引、任务 worktree、Ledger、凭证和日志都在这里。用户工程只在本机 `.git/config` 中留下 `ag2c.manifest`、`ag2c.project-key` 和外部 `core.hooksPath`；它们不会被提交，也不会传到别人的 clone。

**停止治理**只断开本机门禁，项目仍留在列表。**恢复治理**在档案还在时不必重新纳管。**卸载项目**才会删除该工程的治理档案。卸载 AG2C 本身不会改写用户工程。

把整个文件夹拷到另一台电脑时，`.git/config` 可能仍指向旧电脑的用户目录。添加项目或 `ag2c doctor --repair` 会把它当成搬迁或过期：档案一起拷来了就接上；没有拷来就在本机重新纳入，并标明旧历史不可恢复。

## 支持哪些 AI

任何能启动本地 stdio MCP 的编程 agent 都可以接。本机若已有常见客户端配置文件，AG2C 会写入；连接说明本身不点名任何一家。

- 已经连上 AG2C MCP 的 agent 可以进入完整自动流程。
- 从没连 MCP 的 agent，Git 交付门禁仍可能挡住不合规提交，但不能保证它在编辑前就会调用工具。
- 本机 Guard 是 Git 交付边界，不是操作系统文件权限。故意改 Git 配置的进程仍然可以绕过它。

当前版本只做 Windows、单人、本地工作流；多人协调和跨机器证据交换还不包含。

## 证据和 CI

普通用户直接在托盘里看证据。维护者仍可只读查询：

```bash
ag2c evidence
ag2c evidence --task <task-id>
ag2c evidence --format json
```

完整凭证只保存在本机外部目录。提交消息只带 `AG2C-Task` 和 `AG2C-Evidence` 摘要。另一台机器不能只靠摘要还原 Ledger。远端 CI 应独立运行项目测试并配合分支保护。详见[本机证据与 CI](docs/CI_VERIFICATION.md)。

Knowledge、Floor 和公开界面卡片是维护者工具（`ag2c knowledge`、`ag2c govern`），不是开始使用 AG2C 的前提。见[自动治理](docs/AUTOMATIC_GOVERNANCE.md)。

## 文档

- [接入、换机与旧版迁移](docs/ADOPTION.md)
- [自动治理合同](docs/AUTOMATIC_GOVERNANCE.md)
- [架构与证据模型](docs/ARCHITECTURE.md)
- [目录户口](docs/DIRECTORY-CENSUS.md)
- [本机证据与 CI](docs/CI_VERIFICATION.md)
- [Skill 副本](docs/skills/README.md)
- [参与贡献](CONTRIBUTING.md)
- [安全策略](SECURITY.md)
- [更新记录](CHANGELOG.md)

## 许可证

MIT
