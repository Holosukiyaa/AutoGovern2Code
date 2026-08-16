# 接入 AutoGovern2Code

用户不需要先学习 AG2C 的内部治理模型。安装一次、明确纳管一次，之后正常使用 Codex 即可。

## 安装

```bash
python -m pip install "git+https://github.com/Holosukiyaa/AutoGovern2Code.git@v0.3.0"
ag2c setup
```

本地源码开发使用 `python -m pip install -e .`。发布到 PyPI 后可改用 `python -m pip install autogovern2code`。

`ag2c setup` 会把 Skill 安装到 `~/.agents/skills`。

## 纳管一次

在干净且非空的 Git 工程中打开 Codex，然后说：

```text
$ag2c-governed-development 把这个工程纳入 AutoGovern2Code
```

AG2C 会生成并提交可审查的根级 `AGENTS.md` 门禁和 `.ag2c` 配置，保留已有 `AGENTS.md`、`.gitignore` 与 pre-commit hook，并完成本机激活。

Skill 内部只调用 `ag2c setup --project .`。这个入口会自动判断应该首次纳管、迁移旧 `.deg`，还是升级已有工程，不要求用户分辨。

## 正常工作

以后直接向 Codex 提出产品需求。根级门禁会要求 Codex 在首次写入前使用 Skill；Skill 会在后台完成路由、外部 worktree、验证、提交、fast-forward 合并和证据记录。

## 查看证据

```bash
ag2c evidence
ag2c evidence --task <task-id>
ag2c evidence --format json
```

默认输出只展示文件数、检查结果、AI 是否在失败后完成纠正、阻止过的危险操作、最终提交和证据完整性。只有任务从首次写入前就被接管、最终内容通过验证、相同内容进入提交、合并为 fast-forward 且 Ledger 完整时，治理结果才是成功。

## 换电脑或重新克隆

仓库中的纳管门禁会随 Git 传播，本机 Skill 和 Git Guard 不会。先在新机器安装 AutoGovern2Code 并运行 `ag2c setup`，再正常用 Codex 打开工程。Skill 发现本机未激活时会先执行 `ag2c doctor --repair`，恢复 Skill、Guard、已有 Hook 委托、索引和激活证据，然后才允许写入。

## 升级与迁移

- `ag2c upgrade` 在干净正式工作副本中刷新 AG2C 自动维护的基线区域、原生检查、工程门禁、Skill、Hook 和索引，只提交确实变化的治理文件。
- `ag2c migrate` 迁移旧 `.deg` 工程。原 `.deg` 全部内容归档到 `.ag2c/state/legacy-deg`，新 Ledger 只记录旧 Ledger 摘要，不伪造历史。
- `ag2c doctor --repair` 只修复本机激活；损坏的 Ledger 不会被冒充修好。
