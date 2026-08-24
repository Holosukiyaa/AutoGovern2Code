---
name: ag2c-governed-development
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

4. Inspect the canonical checkout read-only and run `ag2c coverage --format json`. Identify narrow expected paths and exact public contract keys. Baseline coverage is intentionally conservative: use exact paths when known and broaden uncertain or new areas. Do not edit, generate, build, install dependencies, or start a service in the canonical checkout.

5. Start the task from the canonical checkout:

   ```text
   ag2c task start --goal "<user request>" --path app:<relative-path>
   ```

   Repeat `--path` and `--contract` as needed. If the change surface is genuinely unknown, use `--all`; never use a vague goal to invent a narrow route.

6. Read the JSON response and move into `worktree.path`. Perform every write, dependency install, build, test, screenshot, and generated output only in that external worktree. `ag2c task list` reports worktree lifecycle: constructing, verified but unmerged, diverged, abandoned, or merged.

7. After the final change, run from the task worktree:

   ```text
   ag2c task verify
   ```

   AG2C recomputes the route from the actual diff and runs only trusted project checkers. A passing result leaves the task verified but unmerged. When it reports a failure, fix the product cause and verify again. Never weaken policy, remove checks, edit evidence, or touch the canonical checkout to make a task pass.

   If the canonical branch moved while the worktree was open, run `ag2c task refresh --task <task-id>` from the canonical checkout, then verify again. If that work is obsolete, run `ag2c task abandon --task <task-id>` instead of leaving an active worktree behind. A large actual diff or a changed Manifest/Policy expands validation conservatively.

8. After a passing verification, return to the canonical checkout and run:

   ```text
   ag2c task finish --task <task-id> --message "<concise commit message>"
   ```

   AG2C refuses stale evidence, writes the full record to the external project store, adds only evidence digest trailers to the commit, validates the committed bytes, fast-forwards the original branch, and cleans up the external worktree. If `governance_pending.items` is not empty, immediately settle it before any new coding task:

   ```text
   ag2c govern settle --actor <harness> --reason "after task <task-id>: <user request>"
   ```

   Do not ask the user to operate this. If settle reports remaining items, follow the `ag2c-governance-update` Skill for those leftovers only. Then continue with evidence.

8b. Use the JSON `guidance` from `ag2c task start` as the retrieved project knowledge and contracts for this change. Do not grep the whole repository for ownership or public interfaces when that guidance already names them.

9. Run `ag2c evidence --task <task-id>` and report its plain-language facts with the product outcome: files changed, checks passed, whether a failed attempt was corrected, local evidence completeness, and merged commit. Do not teach the user cards, floors, slices, policies, or checker selection unless they explicitly request diagnostics. Do not edit Policy by hand; use `ag2c govern` through the governance-update Skill when rules must change.

## Fail Closed

- A dirty or advanced canonical checkout blocks start, verify, or merge.
- A diverged task worktree must be refreshed onto the current canonical HEAD or abandoned before delivery.
- A write outside governed scope blocks verification.
- Any change after the passing verification requires another verification.
- Missing or invalid evidence means the work is not complete.
- Do not edit or manufacture the external project store, task records, hooks, or evidence files.
