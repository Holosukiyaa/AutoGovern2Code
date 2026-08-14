# DEG

**让 AI 在受控路径里改代码，并留下它确实被纠正和验证过的证据。**

[English](README.md) | [自动治理](docs/zh-CN/AUTOMATIC_GOVERNANCE.md) | [证据模型](docs/ARCHITECTURE.md)

DEG 不是需要用户操作的项目管理台。工程完成一次纳管后，用户继续像平时一样使用 Codex；AI 会自动读取项目门禁、经过责任路由、进入外部 Git worktree 施工、执行项目检查，并且只有在证据对应当前修改时才能合并。

## 用户能得到什么

- AI 不能直接在正式工作副本里提交修改。
- AI 开工前必须确定修改范围；不确定时扩大验证，不能偷偷缩小范围。
- 实际修改超出最初判断时，DEG 自动重新路由并记录这次纠正。
- 必要检查失败时任务不能完成；修复后重新通过会形成前后证据。
- 通过检查后又发生修改，旧证据立即失效。
- 正式分支有用户修改、HEAD 变化或无法 fast-forward 时拒绝合并。
- 每个任务留下开始、干预、检查、提交和合并记录。

## 一次性安装

DEG 需要 Python 3.11 或更高版本。当前从源码目录安装：

```bash
python -m pip install .
deg skill install
```

正式发布软件包后，`python -m pip install deg-governance` 会安装同一个命令和 Skill 内容。

然后在一个干净的 Git 工程中告诉 Codex：

```text
$deg-governed-development 把这个工程纳入 DEG
```

Skill 会执行一次性纳管：生成根级 `AGENTS.md` 门禁、自动识别当前工程范围和常见原生测试、提交纳管配置、安装本机 Git Guard，并建立第一条 Ledger 证据。

从此以后不再需要启动 DEG。正常告诉 Codex“修复这个问题”或“实现这个功能”即可。

## 日常过程

```text
用户正常提出开发任务
        ↓
Codex 自动进入 DEG Skill
        ↓
只读判断入口和责任范围
        ↓
DEG 建立外部任务 worktree
        ↓
AI 只在 worktree 修改
        ↓
DEG 按实际 diff 重新路由并运行可信检查
        ↓
同一份修改验证通过后提交并 fast-forward 合并
        ↓
Ledger 和任务记录保存管理证据
```

用户不需要理解卡片、Policy、Floor、Boundary、Scenario 或 Checker。它们是 DEG 内部确定“该看什么、该防什么、该测什么”的实现机制。

## 查看证据

证据入口是只读的：

```bash
deg evidence
deg evidence --task <task-id>
deg evidence --format json
```

它只回答：DEG 是否从任务开始接管、阻止或纠正过什么、验证尝试了几次、最终是否通过、哪个提交被合并，以及 Ledger 是否完整。

## 交付标准

一个任务只有同时满足以下条件才算管理成功：

1. DEG 在首次写入前建立任务记录和外部 worktree。
2. 正式工作副本在施工期间保持干净且 HEAD 不变。
3. 实际修改全部处于受治理范围，并按最终 diff 完成路由。
4. 最后一次验证的修改摘要与提交前摘要完全一致。
5. 所有选中的可信检查通过。
6. 任务提交通过 fast-forward 进入原分支。
7. Ledger 哈希链和任务证据完整。

缺少任意一项，只能报告“管理不完整”，不能冒充完成。

## 技术边界

DEG 是开发期外挂。被治理产品不导入 DEG，也不依赖 DEG才能构建或运行。项目内只有可审查的纳管门禁和策略；索引、任务状态、Hook 与 Ledger 运行数据不会进入产品运行时。

当前 `0.2` 是单人、本地 Git 工作流。远端分支保护、多人并发和托管证据不在本版本范围内。

## 许可证

MIT
