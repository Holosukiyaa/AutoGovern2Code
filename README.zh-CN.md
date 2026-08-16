# AutoGovern2Code（AG2C）

**照常使用 Codex。AG2C 会自动隔离、检查、证明并安全合并每一次工程修改。**

[English](README.md) | [接入说明](docs/zh-CN/ADOPTION.md) | [自动治理原理](docs/zh-CN/AUTOMATIC_GOVERNANCE.md) | [架构与证据](docs/ARCHITECTURE.md)

AutoGovern2Code 是给 AI 编程使用的本地开源治理层。它不是另一套项目管理台，也不会要求用户操作卡片、策略或审批页面。一个 Git 工程完成一次纳管后，根级说明和 AG2C Skill 会让 Codex 在首次写入之前自动进入受治理施工流程。

## 用户体验发生了什么变化

没有 AG2C 时：

```text
让 Codex 修改工程 -> 只能希望它找对文件、跑对检查
```

完成一次纳管后：

```text
正常向 Codex 提开发需求
  -> 写入前确定责任范围
  -> 在工程外创建 Git worktree
  -> AI 只在 worktree 施工
  -> 按实际 diff 重新计算范围
  -> 运行工程自己的可信检查
  -> 把通过证据绑定到这份修改的精确字节
  -> fast-forward 合并已验证提交
  -> 留下可校验的治理记录
```

用户仍然只需要说“修复这个问题”或“实现这个功能”。治理留在后台，但失败原因和成功证据不会被隐藏。

## 安装一次

需要 Python 3.11 或更高版本、Git，以及 Codex CLI 或 Codex IDE 扩展。

从 GitHub 安装：

```bash
python -m pip install "git+https://github.com/Holosukiyaa/AutoGovern2Code.git@v0.3.0"
ag2c setup
```

从本地源码参与开发：

```bash
python -m pip install -e .
ag2c setup
```

`ag2c setup` 会把 Skill 安装到当前 Codex 能发现的用户级目录 `~/.agents/skills`。只有 Skill 明确执行 `ag2c setup --project .` 时才会纳管当前工程。

## 纳管一个工程

在一个干净且非空的 Git 工程中打开 Codex，然后说：

```text
$ag2c-governed-development 把这个工程纳入 AutoGovern2Code
```

纳管会生成并提交可审查的根级 `AGENTS.md` 门禁和 `.ag2c` 策略文件，同时安装本机 Git Guard、识别常见原生测试、建立初始责任索引并记录纳管证据。

这是用户最后一次主动启动治理流程。以后只需要正常提出开发需求；Codex 开工前会读取已纳管工程的说明并自动使用 AG2C。

首次纳管只声明“保守基线覆盖”：AG2C 按检测到的顶层工程区域拆分责任，遇到未知或新增路径时扩大路由和检查，不会假装已经理解全部业务架构。维护者以后可以继续补充结构化责任和公开合同，但用户工作流不变。

## 自动恢复与升级

Skill 每次开工前都会检查本机状态。重新克隆、Python 路径变化、Hook 缺失或 Skill 更新后，它会先运行 `ag2c doctor --repair` 再施工。`ag2c upgrade` 会在干净工程中刷新 AG2C 自动维护的区域和原生检查；`ag2c migrate` 会把旧 `.deg` 完整归档，原 Ledger 字节按摘要关联，不会被伪造重写。

## AG2C 能证明什么

- 正式工作副本没有被当成施工目录。
- 首次受治理写入前已经存在任务记录和外部 worktree。
- 最终责任范围来自实际 Git diff，而不只是 AI 自己的计划。
- 检查失败不会被后续通过覆盖，修复后的通过可以证明纠正过程。
- 通过证据对应的就是最终提交的精确内容。
- 合并时原分支仍然干净且 HEAD 没有变化。
- 已验证提交通过 fast-forward 进入原分支。
- 任务证据与哈希链 Ledger 仍然相互一致。

缺少任何一项，只能得到“治理不完整”，不能冒充成功。

## 查看证据

证据入口只读：

```bash
ag2c evidence
ag2c evidence --task <task-id>
ag2c evidence --format json
```

默认输出只说用户关心的事实：改了几个文件、检查通过几项、失败后是否完成纠正、阻止过几次危险操作、最终提交和证据是否完整。`--format json` 保留完整机器记录。

## 技术边界

AG2C 是可拆除的开发期基础设施。被纳管产品不导入 AG2C，也不依赖 AG2C 才能构建、测试或运行。移除本机 AG2C 只会移除受治理施工路径，不会改变产品功能。

`0.3` 版本面向单人、本地 Git 工作流，每个工程独立纳管。本机 Guard 不是操作系统级安全边界；多人协作仍然需要远端受保护分支和强制 CI。

首个正式支持的 harness 是 Codex。确定性 CLI 和持久化合同已经与具体 AI 解耦，后续可以增加其他编程 Agent 的 Skill，而不需要改造被纳管产品。

## 维护者文档

- [接入与换机激活](docs/zh-CN/ADOPTION.md)
- [自动治理合同](docs/zh-CN/AUTOMATIC_GOVERNANCE.md)
- [架构与证据模型](docs/ARCHITECTURE.md)
- [入口切片](docs/zh-CN/ENTRY_SLICING.md)
- [策略参考](docs/POLICY_REFERENCE.md)
- [参与贡献](CONTRIBUTING.md)
- [安全策略](SECURITY.md)

## 许可证

MIT
