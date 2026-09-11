---
name: ag2c-directory-census
version: 0.10.0
description: Investigate AutoGovern2Code directory rooms, split 占位/黑盒, and apply coverage tags (未打标 / 整夹一张 / 一文件一张) while looking at the tree. Use when the user asks to 彻查, 普查, census, 说清目录, 打标, split ownership, or find unexplained files under a claimed parent. Observe with `ag2c govern census`, register only proper-subset rooms, set a tag on each inspected room, and never name a catch-all parent. Do not write 设计思路 here (`ag2c-knowledge-authoring` does that from the tags). Do not change product files; hand leftover deletion to ag2c-governed-development after `govern retire`.
---

# AutoGovern2Code Directory Census

This Skill looks at the tree and **sets coverage tags**. It does not write 设计思路. After tags exist, `ag2c-knowledge-authoring` writes the knowledge cards. Do not fix product behavior here, and do not edit Policy JSON by hand.

## When to use

- 彻查 / 普查 / census / 说清这一层 / 打标 / 占位 / 黑盒 / unexplained files under a claimed directory.
- Not for a product bug or feature (use `ag2c-governed-development`).
- Not for filling 设计思路 from those tags (use `ag2c-knowledge-authoring`).
- Not for a README or public-interface card the user named (use `ag2c-governance-update`).

Enrollment already hangs each top-level directory as exploring (`meaning=none`). That owns routing. It does not explain children and it is not a tag.

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

   Read `identity` / `explained` / `child_directories` / `span`. Exploring is a door sign, not a finished census. Opaque is a failed named claim, not success.

3. Explain one room at a time. Register a **proper-subset** glob (example: `src/frontend/**`), not the whole parent (`src/**`) as named:

   ```text
   ag2c govern household --id knowledge.<slug> --title "<room>" --summary "<room identity, not 设计思路>" --include <dir>/** --floor <floor.id> --capability <slug> --implementation <slug>.main --actor <harness> --reason "<what was traced>"
   ```

   After a child room exists, the parent must `--exclude` that child's glob. Re-including the parent tree without that exclude recaptures the child; AG2C refuses `cannot-overlap-household`.

4. **Set a coverage tag on that room in the same pass.** Do not leave it 未打标 unless the user said 未打标. Infer and apply with `ag2c govern span`. The user supervises the tag in the tray; they do not click to set it. Do not wait for permission.

   ```text
   ag2c govern span --id knowledge.<slug> --tag 整夹一张 --actor <harness> --reason "<why this tightness>"
   ```

   Tags:

   - `未打标` — routing only. Files get no 设计思路.
   - `整夹一张` — one card will cover this room. Use when the files cooperate as one unit.
   - `一文件一张` — each code file will get its own card. Use when files do not share one design.

   Do not name a room that is still `未打标`. `--meaning named` requires a tag. `整夹一张` may name when child directories are themselves rooms. `一文件一张` may name only after every code file has its own card. AG2C refuses `cannot-name-undecomposed-household`, `span-unlabeled`, and `span-file-gap`.

5. After inspecting that room's files (enough to choose the tag and the split), record only that card:

   ```text
   ag2c govern census --record --card knowledge.<slug> --actor <harness> --reason "<what was inspected and why the tag>"
   ```

   Never `--all` or a bulk record to hide unread files. `govern settle` does not count as a census.

6. If the user asked to 彻查, 说清, or 整理知识卡, continue into `ag2c-knowledge-authoring` in the same session for the rooms just tagged. Do not stop at tags.

7. Report in plain language: which rooms you split, which tags you set, which the user still 未打标. Do not tell the user cards or policy unless they ask.

8. Deleting leftover bytes is a separate `ag2c-governed-development` task after `ag2c govern retire`. Do not delete exploring or current directories here.

## Fail closed

- Do not change product source, tests, or docs in this Skill.
- Do not skip tagging an inspected room.
- Do not write 设计思路 here; that is `ag2c-knowledge-authoring`.
- Do not create a catch-all card to hide unowned or unexplained code.
- Do not re-include a parent glob that covers an existing subset household unless that child glob is excluded.
- Do not treat exploring as named.
- Do not name a 未打标 room.
- Do not `census --record` a card you did not inspect.
- Do not enable `household-gate --mode enforce` unless the user asked to block delivery on census gaps.
- Do not edit `policy.json`, Manifest, ledger, or evidence files.
