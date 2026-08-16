# AutoGovern2Code（AG2C）

**照常使用你的编程 AI，工程治理放在它背后自动完成。**

[English](README.md) | [接入说明](docs/zh-CN/ADOPTION.md) | [自动治理](docs/zh-CN/AUTOMATIC_GOVERNANCE.md) | [架构](docs/ARCHITECTURE.md)

AutoGovern2Code 是一层本地、开源的 AI 编程治理工具。一个 Git 工程被加入管理后，兼容的编程 AI 会通过已安装的 Skill 发现 AG2C。之后，责任路由、外部 worktree、项目检查、验证后合并和证据记录都在后台完成。

用户工程里不会出现 `.ag2c` 目录，不会由 AG2C 生成 `AGENTS.md` 或 `CLAUDE.md`，也不会混入治理凭证。产品的构建和运行永远不依赖 AG2C。

## Windows 用户怎么用

只需要 Windows 10/11 x64 和 Git，不需要 Python。

1. 从[最新 GitHub Release](https://github.com/Holosukiyaa/AutoGovern2Code/releases/latest)下载 `AutoGovern2Code-Setup-Windows-x64.exe`。
2. 双击安装。安装器只写入当前用户，并自动启动 AG2C 托盘程序。
3. 从系统托盘打开 AG2C，点击“添加工程”，选择一个非空的 Git 工程目录。
4. 回到 Codex、Claude Code 或其他兼容工具里，继续像以前一样提开发需求。

托盘程序会随 Windows 启动。它只展示普通用户关心的结果：工程有没有管起来、AI 入口是否就绪、交付门禁是否生效、有没有成功治理的证据。用户不需要理解卡片、策略、切片或审批流程。

社区安装器目前没有代码签名，Windows SmartScreen 可能会警告。请只从本仓库下载，先按 `SHA256SUMS.txt` 核对文件，再选择“更多信息 > 仍要运行”。

## 后台实际做了什么

```text
用户正常提出开发需求
  -> Skill 识别当前 Git 工程已被纳管
  -> AG2C 在写入前确定责任范围
  -> AI 只在工程外的 Git worktree 施工
  -> 最终范围按实际 diff 重新计算
  -> 运行工程自己的测试和检查
  -> 把证据绑定到最终提交的精确内容
  -> 只把验证过的提交 fast-forward 合回原分支
  -> 托盘展示结果与本机证据
```

正式工作副本不干净、分支发生变化、检查失败、修改超出治理范围或证据过期，都会阻止交付。AI 先失败再修好的过程也会保留，不会只留下一个“成功”。

## 治理数据放在哪里

Windows 默认位置：

```text
%LOCALAPPDATA%\AutoGovern2Code\
  projects.json
  projects\<工程标识>\
```

策略、索引、任务 worktree、Ledger 和凭证都在这里。用户工程只在本机 `.git/config` 中留下外部位置和 `core.hooksPath` 指针；它们不会被 Git 提交，也不会传播到别人的 clone。

从托盘停止管理某个工程时，默认只解除本机门禁，历史证据仍然保留。卸载 AG2C 也不会改写用户工程或删除证据。

## 支持哪些 AI

安装器会把同一份 Agent Skills 标准 Skill 安装到 Codex、Claude Code 和通用 Skill 目录，托盘会分别检测这些入口。

- 支持 Agent Skills 的工具可以进入完整的无感流程。
- 对没有 Skill 机制的未知工具，Git 交付门禁仍可能阻止不合规提交，但不能保证它在编辑前主动进入 AG2C。
- 本机 Guard 是 Git 交付边界，不是操作系统文件权限。一个故意篡改 Git 配置的进程仍然可以绕过它。

当前版本先把单人、本地工作流打磨好；多人协调和跨机器证据交换属于后续能力。

## macOS、Linux 与源码开发

桌面安装器目前只支持 Windows。macOS、Linux 和源码开发需要 Python 3.11 或更高版本：

```bash
python -m pip install "git+https://github.com/Holosukiyaa/AutoGovern2Code.git@v0.6.0"
ag2c setup
```

从本地源码运行：

```bash
python -m pip install -e .
ag2c setup
```

这些命令面向非 Windows 用户和开发者。Release 中的 wheel 与源码包也是开发产物；Windows 普通用户只下载安装器。

## 证据和 CI

普通用户直接在托盘里看证据。高级用户仍可只读查询：

```bash
ag2c evidence
ag2c evidence --task <task-id>
ag2c evidence --format json
```

为了保持项目零治理文件，完整证据只保存在本机外部目录。提交消息只带 `AG2C-Task` 和 `AG2C-Evidence` 摘要。另一台机器不能只靠摘要还原本机 Ledger；远端 CI 应独立运行项目测试并配合分支保护。详见[本机证据与 CI](docs/zh-CN/CI_VERIFICATION.md)。

## 维护者文档

- [接入、换机与旧版迁移](docs/zh-CN/ADOPTION.md)
- [自动治理合同](docs/zh-CN/AUTOMATIC_GOVERNANCE.md)
- [架构与证据模型](docs/ARCHITECTURE.md)
- [入口切片](docs/zh-CN/ENTRY_SLICING.md)
- [策略参考](docs/POLICY_REFERENCE.md)
- [本机证据与 CI](docs/zh-CN/CI_VERIFICATION.md)
- [参与贡献](CONTRIBUTING.md)
- [安全策略](SECURITY.md)

## 许可证

MIT
