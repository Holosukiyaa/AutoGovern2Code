---
name: ag2c-governance-update
description: Update AutoGovern2Code project knowledge, floors, and public-interface cards through the dedicated `ag2c govern` commands. Use after enrollment ingest, after `ag2c task finish` reports pending governance items, or when the user asks to add, change, or retire project knowledge or contracts. Always require a reason. Never edit Policy JSON by hand.
---

# AutoGovern2Code Governance Update

This Skill is the only path for changing stored project knowledge. The user describes what changed in the product; do not ask them to operate Policy, cards, or the viewer.

## When to use

- First enrollment already ingested top-level areas, key documents, and detected interfaces. Use this Skill only when those records must change.
- After `ag2c task finish`, if `governance_pending` lists items. Prefer `ag2c govern settle` first. `undeclared-product` stays until the project has a real product check; settle does not invent one.
- When the user says a directory, README, API, or contract is new, moved, or gone.

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

   `ag2c task start` already includes the same guidance. Prefer that payload over searching the whole tree.
   Directory households use `ag2c govern tighten`, `renew-exploring`, `retire`,
   and `retire-confirm`. `settle` does not mark a household named or delete leftover code.

## Fail closed

- Directory jurisdictions use `ag2c govern household`, not document-card apply.
  Register directory scopes, exclusions, floor links, capability, implementation,
  lifecycle, grain/meaning/contract/decider, and implementation-specific checks.
  Tighten only; never widen. Retain old cards with an explicit `--replaced-by`
  link until a retirement task removes leftover bytes.
- `ag2c govern census` only observes. Record a reviewed scope with `--record
  --card <id> --actor <harness> --reason "<review facts>"`; never infer review from
  a refresh, a timestamp, or successful unrelated tests.
- `ag2c govern household-gate --mode enforce` enables hard checks; observation
  mode must never be described as enforced. Both commands require actor/reason.

- Do not edit `policy.json`, Manifest, ledger, or evidence files.
- Do not apply a change without `--reason`.
- Do not remove the constitution card or the last floor.
- Do not invent public contracts the project does not have.
