# Skills used with AutoGovern2Code

These are **reading copies**. Compatible agents load Skills from their own homes
(`~/.codex/skills`, `~/.claude/skills`, `~/.cursor/skills`, `~/.agents/skills`).
Enrollment installs the AG2C pair there from `src/ag2c/skills/`. Do not edit
Policy by pasting these files into a project.

| Copy | What it binds |
| --- | --- |
| `ag2c-governed-development` | File-changing work: `guard status`, task worktree, verify, finish. |
| `ag2c-governance-update` | Knowledge and households: `ag2c govern` only, never hand-edited Policy. |
| `result-lock` | Lock a checkable finished state before implementation (Grok 结果门). |

The strong constraint on Codex CLI is not the Skill text alone. The Skill is
entry; `core.hooksPath` is delivery. See [Automatic governance](../AUTOMATIC_GOVERNANCE.md).
