---
name: ag2c-directory-census
version: 0.8.4
description: Investigate AutoGovern2Code directory households without treating enrollment placeholders as an explanation of the tree. Use when the user asks to 彻查, 普查, census, 说清目录, split 占位/黑盒, inspect ownership, or find unexplained files under a claimed parent. Observe with `ag2c govern census`, register only proper-subset rooms, record a review only after inspecting that room, and never name a catch-all parent. Do not change product files; hand leftover deletion to ag2c-governed-development after `govern retire`.
---

# AutoGovern2Code Directory Census

This Skill is the entry for looking at the tree. The user wants rooms explained. Do not fix product behavior here, and do not edit Policy JSON by hand.

## When to use

- 彻查 / 普查 / census / 说清这一层 / 占位 / 黑盒 / unexplained files under a claimed directory.
- Not for a product bug or feature (use `ag2c-governed-development`).
- Not for a README or public-interface card the user named (use `ag2c-governance-update`).

Enrollment already hangs each top-level directory as exploring (`meaning=none`). That owns routing. It does not explain children.

## Workflow

1. Confirm the repository is managed:

   ```text
   ag2c guard status
   ```

   Repair with `ag2c doctor --repair` if needed. Stop if still unmanaged.

2. Observe only:

   ```text
   ag2c govern census
   ```

   Read `identity` / `explained` / `child_directories`. Exploring is a door sign, not a finished census. Opaque is a failed named claim, not success.

3. Tag the room before filling cards. Coverage is the ruler the user supervises:

   ```text
   ag2c govern span --id knowledge.<slug> --tag 整夹一张 --actor <harness> --reason "<why this tightness>"
   ```

   Tags: `未打标` (routing only, no file 设计思路), `整夹一张` (one card covers the room), `一文件一张` (each code file needs its own knowledge card). Propose tags; let the user correct them. Do not name a room that is still `未打标`.

4. Explain one room at a time. Register a **proper-subset** glob (example: `src/frontend/**`), not the whole parent (`src/**`) as named:

   ```text
   ag2c govern household --id knowledge.<slug> --title "<room>" --summary "<one line>" --include <dir>/** --floor <floor.id> --capability <slug> --implementation <slug>.main --actor <harness> --reason "<what was traced>"
   ```

   `--meaning named` requires a coverage tag. `整夹一张` may name the room when child directories are themselves rooms. `一文件一张` may name only after every code file has its own card (`ag2c govern apply` with that file as `--include`). AG2C refuses `cannot-name-undecomposed-household`, `span-unlabeled`, and `span-file-gap`. After a child room exists, the parent must `--exclude` that child's glob. Re-including the parent tree without that exclude recaptures the child; AG2C refuses `cannot-overlap-household`.

5. After inspecting that room's files and checks, record only that card:

   ```text
   ag2c govern census --record --card knowledge.<slug> --actor <harness> --reason "<what was inspected and why>"
   ```

   Never `--all` or a bulk record to hide unread files. `govern settle` does not count as a census.

6. Report in plain language: which tags were proposed, which rooms are still 未打标, which you named, which record succeeded. Do not tell the user cards or policy unless they ask.

7. Deleting leftover bytes is a separate `ag2c-governed-development` task after `ag2c govern retire`. Do not delete exploring or current directories here.

## Fail closed

- Do not change product source, tests, or docs in this Skill.
- Do not create a catch-all card to hide unowned or unexplained code.
- Do not re-include a parent glob that covers an existing subset household unless that child glob is excluded.
- Do not treat exploring as named.
- Do not skip coverage tags, and do not name a 未打标 room.
- Do not use a parent-room summary as 设计思路 for files in a 一文件一张 room.
- Do not `census --record` a card you did not inspect.
- Do not enable `household-gate --mode enforce` unless the user asked to block delivery on census gaps.
- Do not edit `policy.json`, Manifest, ledger, or evidence files.
