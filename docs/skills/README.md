# Skills used with AutoGovern2Code

These are **reading copies**. Compatible agents load Skills from their own homes
(`~/.codex/skills`, `~/.claude/skills`, `~/.cursor/skills`, `~/.agents/skills`).
Enrollment installs the AG2C pair there from `src/ag2c/skills/`. Do not edit
Policy by pasting these files into a project.

Each `SKILL.md` has `version:` matching this AG2C package. Pasting the AI-entry
prompt (`ag2c skill prompt` or tray 复制提示词) tells the agent to refresh its
home from this copy whenever the installed version or digest differs. Latest
means this AutoGovern2Code, not a newer folder from the internet or another
install. `ag2c skill version` prints the required identity.

| Copy | What it binds |
| --- | --- |
| `ag2c-governed-development` | File-changing work: `guard status`, task worktree, verify, finish. |
| `ag2c-governance-update` | Document and interface cards: `ag2c govern` only, never hand-edited Policy. |
| `ag2c-directory-census` | Tree investigation: observe census, name proper-subset rooms, record only inspected rooms. |
| `result-lock` | Lock a checkable finished state before implementation (Grok 结果门). |

The strong constraint on Codex CLI is not the Skill text alone. The Skill is
entry; `core.hooksPath` is delivery. See [Automatic governance](../AUTOMATIC_GOVERNANCE.md).
