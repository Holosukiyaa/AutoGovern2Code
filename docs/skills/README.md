# Skills used with AutoGovern2Code

These are **reading copies**. Agents that speak MCP receive the same text as
initialize instructions and `ag2c://skill/<name>` resources from `ag2c mcp`.
The user-facing AI entry is the generic connect prompt (`ag2c://connect`,
placeholders only) plus `ag2c mcp health`. Do not edit Policy by pasting these
files into a project.

Each `SKILL.md` has `version:` matching this AG2C package. Latest means this
AutoGovern2Code. `ag2c skill version` prints the required identity.

| Copy | What it binds |
| --- | --- |
| `ag2c-governed-development` | File-changing work: `guard status`, task worktree, verify, finish. |
| `ag2c-governance-update` | Named document and interface cards: `ag2c govern` only, never hand-edited Policy. |
| `ag2c-directory-census` | Tree investigation and coverage tags: 未打标 / 整夹一张 / 一文件一张. |
| `ag2c-knowledge-authoring` | Write detailed 设计思路 knowledge cards from those tags. |
| `ag2c-full-liquidation` | Full liquidation (全量清算): re-baseline, re-census, re-author, audit, cleanup queue. Explicit user request only. |
| `result-lock` | Lock a checkable finished state before implementation (Grok 结果门). |

The strong constraint is not the Skill text alone. MCP is entry; `core.hooksPath`
is delivery. See [Automatic governance](../AUTOMATIC_GOVERNANCE.md).
