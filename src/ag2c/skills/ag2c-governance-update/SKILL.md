---
name: ag2c-governance-update
version: 0.10.0
description: Update AutoGovern2Code project knowledge, floors, and public-interface cards through the dedicated `ag2c govern` commands. Use after enrollment ingest, after `ag2c task finish` reports pending governance items, or when the user asks to add, change, or retire project knowledge or contracts. Always require a reason. Never edit Policy JSON by hand.
---

# AutoGovern2Code Governance Update

This Skill updates **named document and interface** cards through `ag2c govern`. Directory tags are `ag2c-directory-census`. 设计思路 from those tags is `ag2c-knowledge-authoring`. Do not ask the user to operate Policy, cards, or the viewer.

## When to use

- First enrollment already ingested top-level areas, key documents, detected interfaces, and exploring households for top-level directories. Use this Skill when those *document or interface* records must change. Exploring is not named. To 彻查, split rooms, or 打标, use `ag2c-directory-census`. To write 设计思路 from tags, use `ag2c-knowledge-authoring`.
- After `ag2c task finish`, if `governance_pending` lists items. Prefer `ag2c govern settle` first. `undeclared-product` stays until the project has a real product check; settle does not invent one.
- When the user says a README, API, or contract is new, moved, or gone.

## Workflow

1. Confirm the repository is managed:

   ```text
   ag2c guard status
   ```

   If it is not managed, continue normally unless the user asked to enroll the project.

2. Inspect what AG2C already knows, then settle the backlog with one reason:

   ```text
   ag2c govern pending --format json
   ag2c knowledge status --format json
   ag2c govern settle --actor <harness> --reason "<why the tree or docs changed>"
   ```

   `settle` refreshes discovered directories, documents, and interfaces, and syncs stale Knowledge. It does not accept rewritten document leads. If `assertion-conflict` remains, review the card and then:

   ```text
   ag2c knowledge sync --card <card-id> --actor <harness> --reason "<why the stored claim changed>"
   ```

   Use the commands below only for leftovers or a specific card the user named.

3. Apply one change at a time. `--reason` is required and must say why the stored knowledge changed.

   Add or update a document:

   ```text
   ag2c govern apply --action add --id knowledge.<slug> --type knowledge --title "<name>" --summary "<one line>" --include <relative-path> --actor <harness> --reason "<why>"
   ```

   Add a public interface area:

   ```text
   ag2c govern apply --action add --id boundary.<slug> --type boundary --title "<name>" --summary "<one line>" --include <dir>/** --actor <harness> --reason "<why>"
   ```

   Retire a card that no longer matches the project:

   ```text
   ag2c govern apply --action remove --id <card-id> --actor <harness> --reason "<why>"
   ```

4. After a merge that added directories or documents, refresh discovery instead of inventing cards by hand:

   ```text
   ag2c govern ingest --actor <harness> --reason "<why the tree changed>"
   ```

5. For the next coding task, retrieve only the relevant records:

   ```text
   ag2c govern retrieve --path app:<relative-path> --goal "<user request>" --format json
   ```

   `ag2c task start` already includes the same guidance, including `guidance.lineage` as the knowledge-card 谱系 index. Prefer that payload over searching the whole tree.
   Directory households, tags, and 占位/黑盒 use `ag2c-directory-census`. 设计思路 from tags uses `ag2c-knowledge-authoring`.
   `settle` does not mark a household named or delete leftover code.

## Fail closed

- Directory households, census, 打标, and 占位/黑盒: `ag2c-directory-census`.
- 设计思路 from coverage tags: `ag2c-knowledge-authoring`, not this Skill.
- Do not edit `policy.json`, Manifest, ledger, or evidence files.
- Do not apply a change without `--reason`.
- Do not remove the constitution card or the last floor.
- Do not invent public contracts the project does not have.
