---
name: ag2c-governed-development
version: 0.11.0
description: Automatically govern software changes in Git projects registered with AutoGovern2Code (AG2C), whose enrollment is stored outside the project and discovered through local Git configuration. Use for implementation, fixes, refactors, tests, documentation, configuration, dependencies, builds, and releases when `ag2c guard status` reports managed; also use when the user asks to add, migrate, repair, or inspect AG2C. Restore activation without asking the user to operate governance, route before writing, work only in the external task worktree, verify the final diff, and finish through AG2C.
---

# AutoGovern2Code Development

Treat AutoGovern2Code (AG2C) as the mandatory construction path, not an optional assistant. The user describes the product task normally; do not ask them to operate AG2C or learn its governance model.

## Workflow

1. For a file-changing request in a Git repository, check `ag2c guard status` before the first write. AG2C discovers registered projects through local Git metadata, so do not look for or create governance files in the project. If the repository is not registered, continue normally unless the user explicitly asks to add it.

2. If the user explicitly asks to adopt AG2C, run `ag2c setup --project .`. This creates the external project store, installs the Skill, and activates the Git guard without changing project files or creating a commit. Legacy `.deg` or `.ag2c` enrollment is moved outside the project automatically.

3. For a registered project, before any write run:

   ```text
   ag2c guard status
   ```

   If status fails after a clone, interpreter move, Skill update, or missing hook, run `ag2c doctor --repair` and check status again. Do not ask the user to repair AG2C. Stop if management remains inactive.

   When a session resumes with work possibly in flight, run `ag2c task orient` (optionally `--task <task-id>`) before deciding anything. It reports the task phase, the lifecycle checklist, blockers, and the exact next command; with several open tasks it returns the queue so the user can pick one.

4. Inspect the canonical checkout read-only and run `ag2c coverage --format json`. Identify narrow expected paths and exact public contract keys. Baseline coverage is intentionally conservative: use exact paths when known and broaden uncertain or new areas. Do not edit, generate, build, install dependencies, or start a service in the canonical checkout.

   Tree investigation and coverage tags (彻查, 普查, 打标) use
   `ag2c-directory-census`. Writing 设计思路 from those tags uses
   `ag2c-knowledge-authoring`. Do not start a feature task to name a
   catch-all parent.

5. Start the task from the canonical checkout, locking the 结果门 (result
   gate) portrait before any code:

   ```text
   ag2c task start --goal "<user request>" --path app:<relative-path> --portrait "<finished-state portrait>"
   ```

   The portrait simulates the finished state from outside the implementation
   and locks it: Done looks like (2-4 sentences an outsider could accept or
   reject), Surfaces (each observable surface with example + empty/error/
   success), Out of result (what will NOT exist), Inferences (each guessed
   detail marked INFERRED). Never steps, files-to-edit, or architecture. Write
   it against the knowledge cards in the slice — that is your working set. The
   portrait is the anchor for the whole task: re-read it through
   `ag2c task orient` whenever the session drifts; apply the user's named
   corrections to it and continue without restarting.

   Repeat `--path` and `--contract` as needed. If a household is opaque or has
   unresolved `tighten-or-renew` debt on those paths, settle that first or use
   `--all` only for an explicit compression/retirement task. Never use a vague
   goal to invent a narrow route. Guidance includes `households` with identity,
   children, and `explained`; do not treat an exploring household as named.
   Enrollment already hangs top-level directories as exploring; register a
   tighter household on a subset glob, or tighten the existing card, instead of
   hanging a second card on the same glob.

6. Read the JSON response and move into `worktree.path`. Before any write, read `guidance.lineage` as the knowledge-card 谱系 — the coding index for this change. Each `rooms[].files[]` entry is one file's 设计思路; the room summary is not a substitute when file cards exist. Empty leftover-parent rooms are not the index for a carved child. `guidance.cards` and `guidance.households` are the same records in flat form. Do not grep the repository for ownership or invent design from a leftover parent. Then perform every write, dependency install, build, test, screenshot, and generated output only in that external worktree. `ag2c task list` reports worktree lifecycle: constructing, verified but unmerged, diverged, abandoned, or merged.

7. After the final change, run from the task worktree:

   If directory-household enforcement is enabled, record census only for rooms
   actually inspected in this diff, through `ag2c-directory-census` (tags) and
   `ag2c-knowledge-authoring` (设计思路). Never bulk `--record` unread files.

   ```text
   ag2c task verify
   ```

   AG2C recomputes the route from the actual diff and runs only trusted project checkers. A passing result leaves the task verified but unmerged. When it reports a failure, fix the product cause and verify again. Never weaken policy, remove checks, edit evidence, or touch the canonical checkout to make a task pass.

   If the canonical branch moved while the worktree was open, run `ag2c task refresh --task <task-id>` from the canonical checkout, then verify again. If that work is obsolete, run `ag2c task abandon --task <task-id>` instead of leaving an active worktree behind. A large actual diff or a changed Manifest/Policy expands validation conservatively.

8. After a passing verification, return to the canonical checkout and run:

   ```text
   ag2c task finish --task <task-id> --message "<what was implemented or fixed>" --proof "<自证 evidence>"
   ```

   `--message` must name the product change: a feature that landed or a problem that was fixed. `--proof` is 自证 against the locked portrait: for every claim with side effects (files changed, behavior changed), quote the this-session tool output that proves it — command plus output fragment. Read-only observations (you clicked and saw) need no proof. "Tests passed" without the output, or confidence without an artifact, is a 随便的答案 — do not hand it in. AG2C stores that as the task delivery record, refuses stale evidence, writes the full record to the external project store, adds only evidence digest trailers to the commit, validates the committed bytes, fast-forwards the original branch, and cleans up the external worktree. If `governance_pending.items` is not empty, immediately settle it before any new coding task:

   ```text
   ag2c govern settle --actor <harness> --reason "after task <task-id>: <user request>"
   ```

   Do not ask the user to operate this. If settle reports remaining items, follow the `ag2c-governance-update` Skill for those leftovers only. Then continue with evidence.

8b. `guidance.lineage` from `ag2c task start` is the knowledge-card 谱系. Read it as the index before writing (step 6). Do not grep the whole repository for ownership or public interfaces when that payload already names them.

9. Run `ag2c evidence --task <task-id>` and report its plain-language facts: files changed, checks passed, whether a failed attempt was corrected, process evidence completeness, merged commit, and the Product line. Process evidence complete only means the task was delivered through AG2C. If Product is `undeclared`, `blocked`, or `incomplete`, say the work was checked in, not that the product is done. Do not teach the user cards, floors, slices, policies, or checker selection unless they explicitly request diagnostics. Do not edit Policy by hand; use `ag2c govern` through census, knowledge-authoring, or governance-update when stored knowledge must change.

## Fail Closed

- A dirty or advanced canonical checkout blocks start, verify, or merge.
- A diverged task worktree must be refreshed onto the current canonical HEAD or abandoned before delivery.
- A write outside governed scope blocks verification.
- Do not delete current or exploring directories in a feature task. Mark leftover
  with `ag2c govern retire`, confirm irreversible scopes, then delete only those
  bytes in a dedicated task.
- Any change after the passing verification requires another verification.
- Missing or invalid process evidence means the work is not delivered.
- An undeclared, blocked, or incomplete Product line means product behavior was not proven.
- Do not edit or manufacture the external project store, task records, hooks, or evidence files.
