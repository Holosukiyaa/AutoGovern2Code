# 接入 AutoGovern2Code

用户不需要先学习 AG2C 的内部治理模型。安装一次、明确纳管一次，之后正常使用 Codex 即可。

## 安装

```bash
python -m pip install "git+https://github.com/Holosukiyaa/AutoGovern2Code.git"
ag2c skill install
```

本地源码开发使用 `python -m pip install -e .`。发布到 PyPI 后可改用 `python -m pip install autogovern2code`。

Skill 默认安装到 `~/.agents/skills`。

## 纳管一次

在干净且非空的 Git 工程中打开 Codex，然后说：

```text
$ag2c-governed-development 把这个工程纳入 AutoGovern2Code
```

AG2C 会生成并提交可审查的根级 `AGENTS.md` 门禁和 `.ag2c` 配置，保留已有 `AGENTS.md`、`.gitignore` 与 pre-commit hook，并完成本机激活。

## 正常工作

以后直接向 Codex 提出产品需求。根级门禁会要求 Codex 在首次写入前使用 Skill；Skill 会在后台完成路由、外部 worktree、验证、提交、fast-forward 合并和证据记录。

## 查看证据

```bash
ag2c evidence
ag2c evidence --task <task-id>
ag2c evidence --format json
```

只有任务从首次写入前就被接管、最终内容通过验证、相同内容进入提交、合并为 fast-forward 且 Ledger 完整时，治理结果才是成功。

## 换电脑或重新克隆

仓库中的纳管门禁会随 Git 传播，本机 Skill 和 Git Guard 不会。先在新机器安装 AutoGovern2Code 和 Skill，再正常用 Codex 打开工程。Skill 发现本机未激活时会先执行 `ag2c activate`，恢复 Guard、索引和激活证据，然后才允许写入。
