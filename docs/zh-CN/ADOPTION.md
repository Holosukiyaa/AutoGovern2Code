# 接入 AutoGovern2Code

用户不需要先学习 AG2C 的内部治理模型。安装一次、明确纳管一次，之后正常使用 Codex 即可。

## 安装

Windows 10 或 11（x64）用户从[最新 GitHub Release](https://github.com/Holosukiyaa/AutoGovern2Code/releases/latest)下载 `AutoGovern2Code-Setup-Windows-x64.exe`，然后双击即可。安装器只写入当前用户目录，不需要管理员权限，自带 Python 运行环境，会把 `ag2c` 加入用户 PATH，并安装所需 Skill；它不是桌面应用，也不会常驻后台。

目前社区安装器还没有代码签名。如果 Windows SmartScreen 拦截，先用 Release 同页的 `SHA256SUMS.txt` 核对下载文件，再选择“更多信息 > 仍要运行”；不要运行从其他网站取得的副本。

macOS 或 Linux 用户需要 Python 3.11 或更高版本：

```bash
python -m pip install "git+https://github.com/Holosukiyaa/AutoGovern2Code.git@v0.5.0"
ag2c setup
```

AG2C 只通过 GitHub Releases 发布。Release 里的 wheel 和源码包是开发者产物。本地源码开发使用 `python -m pip install -e .`。

`ag2c setup` 会把同一份 Skill 安装到 Codex、Claude Code 和通用 Agent Skills 的用户目录；可以重复使用 `--harness` 只选择需要的入口。

Windows 卸载程序会删除自带运行环境、用户 PATH 项，以及安装后没有被用户修改过的 Skill。它不会改写已经纳管的工程，也不会删除工程证据；以后还要修改这些工程时，重新双击安装 AG2C 即可。

## 纳管一次

在干净且非空的 Git 工程中打开 Codex，然后说：

```text
$ag2c-governed-development 把这个工程纳入 AutoGovern2Code
```

AG2C 会生成并提交可审查的根级 `AGENTS.md`、`CLAUDE.md` 门禁和 `.ag2c` 配置，保留已有内容、`.gitignore` 与 pre-commit hook，并完成本机激活。

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

每个成功任务还会提交一份可移植凭证。可以运行 `ag2c ci verify --commit HEAD --rerun`，或使用公开 GitHub Action，在不依赖本机忽略证据的情况下独立复核。

## 换电脑或重新克隆

仓库中的纳管门禁会随 Git 传播，本机 Skill 和 Git Guard 不会。先在新机器安装 AutoGovern2Code 并运行 `ag2c setup`，再正常用 Codex 打开工程。Skill 发现本机未激活时会先执行 `ag2c doctor --repair`，恢复 Skill、Guard、已有 Hook 委托、索引和激活证据，然后才允许写入。

## 升级与迁移

- `ag2c upgrade` 在干净正式工作副本中刷新 AG2C 自动维护的基线区域、原生检查、工程门禁、Skill、Hook 和索引，只提交确实变化的治理文件。
- `ag2c migrate` 迁移旧 `.deg` 工程。原 `.deg` 全部内容归档到 `.ag2c/state/legacy-deg`，新 Ledger 只记录旧 Ledger 摘要，不伪造历史。
- `ag2c doctor --repair` 只修复本机激活；损坏的 Ledger 不会被冒充修好。
