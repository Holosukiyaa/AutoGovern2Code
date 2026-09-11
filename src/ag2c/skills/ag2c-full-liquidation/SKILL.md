---
name: ag2c-full-liquidation
version: 0.10.0
description: Full liquidation (全量清算) of a governed project whose knowledge base and tree have drifted — wipe stale cards, re-census into proper rooms, author room cards then per-file cards for core rooms, write an evidence-backed audit document, and queue prioritized cleanup tasks. Use ONLY when the user explicitly asks for 全量清算 / full liquidation / 重建知识库. Never trigger proactively, never chain into it from ag2c-directory-census or ag2c-knowledge-authoring, and never start before the user has approved the assessment and every destructive decision.
---

# AutoGovern2Code Full Liquidation (全量清算)

This Skill rebuilds a project's governance from zero and turns what is found into an audit plus a cleanup queue. It is heavy, destructive-adjacent, and **opt-in only**. The user supervises every phase; you execute.

## When to use

- The user explicitly says 全量清算 / 重建知识库 / full liquidation / "clear the old cards and re-ingest".
- The project's rooms are stale, overlapping, or the tree has drifted far from the policy.

## When NOT to use

- Routine feature/fix work (`ag2c-governed-development`).
- A census or tagging pass on a healthy policy (`ag2c-directory-census`).
- Writing cards for already-tagged rooms (`ag2c-knowledge-authoring`).
- Never enable it silently because a project "looks messy". Messy is not a trigger; the user's words are.

## Gate (required before any command)

1. Assess first, touch nothing: quantify the tree (file/line counts per top directory, god files, graveyard dirs, tracked binaries, evidence in source trees), list governance drift (untagged rooms, overlaps, ambiguous files, stale census).
2. Present the findings and a phase plan. Collect an explicit user decision for every destructive choice — each directory: delete / move out / keep; each tracked generated artifact: keep tracked / convert to build-time; each god file: split now / card now and split later.
3. Only then execute. The phases below are ordered; do not skip ahead.

## Phase A — physical cleanup (governed tasks)

One governed task per destructive decision. Rules learned in production:

- **Wedged policy**: pre-existing overlaps make every `govern household` write fail with `cannot-overlap-household`. Escape: `govern household-gate --mode observe`, then `govern retire` the rooms owning the files to be deleted (retire does not re-check global overlaps). A retire target with a same-capability successor becomes `legacy` via `--replaced-by`; without one it becomes `retired`.
- **retirement-references**: the deletion guard scans surviving files for literal path strings of deleted files. Refactor those references in a *separate* task first: split path literals into directory constants + filename, store filename-only in lock files, make test assertions use `endswith` instead of literal equality.
- **Generated artifacts** (e.g. a tracked SQLite): add an `ensure_*` script that rebuilds from the locked external source, a nested `.gitignore` for the artifact, and call the ensure script from bootstrap and test `setUpClass`. Verify a **logical content digest**, never the file sha256 — SQLite bytes drift with build environment. Expect the tracked copy to be stale against its lock; re-lock to the real source output.
- After the deletion task merges, regenerate artifacts on canonical so the working tree is functional, and re-register any retired-but-still-present rooms to clear `retired-code-remains` debt.

## Phase B — re-baseline and re-census

1. `ag2c govern ingest` wipes cards/relations to a clean baseline (floors + root document cards + exploring top-level rooms).
2. Register rooms **proper-subset**, children before parents. Auto-carve (`_carve_exploring_placeholders`) only shrinks exploring parents that have no explicit excludes; a parent already carrying explicit excludes must be re-registered with the new child excluded *before* the child is registered, or the child write fails with `cannot-overlap-household`.
3. Tag every room (未打标 / 整夹一张 / 一文件一张) and `govern census --record --card` each room. Re-record stale floors too. Target state: `ambiguous 0, leftover 0, unowned` only root loose files covered by a floor, all records `current`.

## Phase C — room cards (整夹一张)

Follow `ag2c-knowledge-authoring`. For many rooms, fan out parallel reading agents; each must open every file it describes (large files: structure map via `^class `/`^def ` plus key bodies). Apply with `govern household` keeping identical scope/floor/capability/implementation and replacing only `--summary`; record census per room.

## Phase D — per-file cards (一文件一张) for core rooms

1. `govern span --tag 一文件一张` the chosen core rooms (the user picks which; god-file rooms are the usual set).
2. Draft one card per code file — no skipping. Title ≤20 characters (it is the 摘要 shown in the file tree), id is an English slug, summary is that file's own 设计思路 (purpose, entry points, callers, dependencies, invariants, debts). Trivial `__init__.py` still gets a specific one-liner.
3. Apply with `govern apply --action add --type knowledge --include <one-file>`. Then rewrite the parent room summary as **room identity, not 设计思路**, and record census per room.

## Phase E — audit document

Write the audit as a governed task (new root doc). Every debt claim must be verified before writing (grep for reachability, read both halves of a suspected shim pair). Quantify: god-file line counts, dead-code file lists, shim counts, before/after governance metrics. End with a prioritized cleanup queue (P0/P1/P2) whose every item cites the file cards that prove it.

## Phase F — cleanup queue execution

- Reference-scan before every deletion (imports, string literals, CSS `@import`); "agent reported unreferenced" is not proof — scan yourself.
- Retire the file cards of files to be deleted *before* the deletion task.
- Restore `govern household-gate --mode enforce` as soon as Phase B is green; run the queue under enforce.

## Operational lessons

- Never pipe `ag2c` JSON through a shell that re-encodes (Windows PowerShell 5.1 mangles UTF-8 into GBK). Call it from a subprocess with `encoding="utf-8"`, or use `--format text`.
- `WinError 5` on `policy.json.tmp` rename is transient file-locking; retry. Make bulk card apply idempotent (skip ids already in policy) so a retry only sends the missing cards.
- When several drafting agents write card JSON, validate id uniqueness across batches before applying; the same file in two batches double-applies.
- Legacy census history may contain mojibake with raw control characters that break `--format json`; parse tolerantly or use text output.
- Have reading agents write their card JSON to files; do not funnel hundreds of cards through chat replies.

## Fail closed

- No explicit user request → do not run. No approved plan → do not execute.
- Never delete a file whose owners are still `current`; never delete before a reference scan.
- Never edit `policy.json`, the ledger, or evidence files by hand.
- Never write 设计思路 for files you did not read; never let a parent sentence cover files in a 一文件一张 room.
- Do not git commit on the canonical checkout; every file change goes through a governed task.
