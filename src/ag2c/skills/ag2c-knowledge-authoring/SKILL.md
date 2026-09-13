---
name: ag2c-knowledge-authoring
version: 0.11.0
description: Write detailed AutoGovern2Code knowledge cards from directory coverage tags. Use after ag2c-directory-census has tagged rooms, or when the user asks to 写知识卡, 整理知识卡片, 设计思路, or fill cards from 未打标/整夹一张/一文件一张. Read the files, then store 设计思路 through `ag2c govern` only. Do not invent unread files, do not use a parent sentence to cover many files under 一文件一张, and do not leave a tagged room with routing-only prose.
---

# AutoGovern2Code Knowledge Authoring

This Skill writes **设计思路**. Coverage tags are already the ruler (`ag2c-directory-census` sets them). Follow the tag. Do not thin the card because the folder has many files. Do not edit Policy JSON by hand. Do not change product source.

## When to use

- After a census pass that set tags.
- 写知识卡 / 整理知识卡片 / 设计思路 / fill cards / 按标写卡.
- Not for splitting rooms or choosing tags (use `ag2c-directory-census`; retag there if the tag is wrong).
- Not for a product bug or feature (use `ag2c-governed-development`).
- Not for a README or public-interface card the user named (use `ag2c-governance-update`).

## What "detailed" means

A stranger should be able to accept or reject the card without opening the code: what this unit is for, what callers use, how the pieces cooperate, what is out of scope. Several sentences are normal. One vague line is not a card.

Forbidden substitutes for 设计思路: "owns routing", "exploring placeholder", "this directory exists", restating the folder name, a sentence that is true of any Python package.

If the tag is `整夹一张` and after reading the files they do not share one design, stop. Do not write a fake umbrella. Send the room back to `ag2c-directory-census` to split or retag `一文件一张`.

## Workflow

1. Confirm the repository is managed:

   ```text
   ag2c guard status
   ```

   Repair with `ag2c doctor --repair` if needed. Stop if still unmanaged.

2. Observe tags:

   ```text
   ag2c govern census
   ```

   Use each household's `span` / tag. Skip rooms still `未打标` (no 设计思路 on files). Walk every tagged room the user asked to 整理; if they said 整理一遍, walk every tagged room.

3. Read the files in that room before writing. Unread files get no card text.

4. Write according to the tag.

   **整夹一张** — one household card covers the room. Keep the same `--include` / `--exclude` / `--floor` / `--capability` / `--implementation`. Replace `--summary` with the detailed 设计思路 for this room as one unit (entry, how files cooperate, invariants, what is outside). Files inherit that summary.

   ```text
   ag2c govern household --id knowledge.<slug> --title "<room>" --summary "<detailed 设计思路 for this folder as one unit>" --include <dir>/** --floor <floor.id> --capability <slug> --implementation <slug>.main --actor <harness> --reason "<read these files; they share this design>"
   ```

   **一文件一张** — each code file gets its own knowledge card bound to that file. The parent household summary is room identity, not 设计思路. Do not skip files. Do not reuse one parent sentence.

   The card **title is the 摘要**: at most 20 characters, Chinese allowed. The file tree shows this name next to the file as its owner. Do not write a separate 摘要. `--summary` is 详细设计. The id (`knowledge.<english-slug>`) is the stable identifier, not the display name; it must stay an English slug.

   ```text
   ag2c govern apply --action add --id knowledge.<file-slug> --type knowledge --title "<≤20-character 摘要>" --summary "<detailed 设计思路 for THIS file>" --include <relative-file> --actor <harness> --reason "<read this file>"
   ```

   Use `--action update` when that file card already exists. `--include` is exactly one file. Then the room may be named (`--meaning named`) only after every code file has a card.

   **未打标** — do not write 设计思路; do not add per-file cards.

5. After writing that room, record census for it (summary and file cards change the declaration):

   ```text
   ag2c govern census --record --card knowledge.<slug> --actor <harness> --reason "<wrote 设计思路 from the tag after reading the files>"
   ```

6. Report in plain language: which rooms were written, which stayed 未打标, which were sent back to retag. Do not tell the user cards or policy unless they ask.

## Fail closed

- Do not edit `policy.json`, Manifest, ledger, or evidence files.
- Do not change product source, tests, or docs in this Skill.
- Do not skip a code file in a `一文件一张` room.
- Do not use a parent-room summary as 设计思路 for files in a `一文件一张` room.
- Do not write routing-only or one-line filler for a `整夹一张` or `一文件一张` room.
- Do not invent text for files you did not read.
- Do not name a `未打标` room.
- Do not `census --record` a card you did not inspect.
- Do not create a catch-all parent card to hide unread children.
- Do not use an English filename, module path, or `python -m …` as the file-card title when a ≤20-character 摘要 can name it.
