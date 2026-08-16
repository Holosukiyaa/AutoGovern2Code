---
name: ag2c-governed-development
description: Set up, migrate, repair, or use AutoGovern2Code (AG2C), then automatically govern every software change in an enrolled Git repository. Use when the user asks to adopt AG2C, when a repository contains `.deg` or `.ag2c` enrollment, or when root AGENTS.md requires AG2C for an implementation, fix, refactor, test, documentation, configuration, dependency, build, or release request. Restore local activation without making the user operate governance, route before writing, work only in the AG2C-created external worktree, verify the final diff, and finish through AG2C so only evidence-backed commits reach the canonical checkout.
---

# AutoGovern2Code Development

Treat AutoGovern2Code (AG2C) as the mandatory construction path, not an optional assistant. The user describes the product task normally; do not ask them to operate AG2C or learn its governance model.

## Workflow

1. If the user explicitly asks to adopt AG2C, require a clean Git worktree and run `ag2c setup --project .`. This single command chooses enrollment, legacy DEG migration, or upgrade and local activation. Never enroll an unrelated repository implicitly.

2. Read the repository `AGENTS.md`. Before any write, run:

   ```text
   ag2c guard status
   ```

   If status fails after a clone, interpreter move, Skill update, or missing hook, run `ag2c doctor --repair` and check status again. Do not ask the user to repair AG2C. Stop if management remains inactive.

3. Inspect the canonical checkout read-only and run `ag2c coverage --format json`. Identify narrow expected paths and exact public contract keys. Baseline coverage is intentionally conservative: use exact paths when known and broaden uncertain or new areas. Do not edit, generate, build, install dependencies, or start a service in the canonical checkout.

4. Start the task from the canonical checkout:

   ```text
   ag2c task start --goal "<user request>" --path app:<relative-path>
   ```

   Repeat `--path` and `--contract` as needed. If the change surface is genuinely unknown, use `--all`; never use a vague goal to invent a narrow route.

5. Read the JSON response and move into `worktree.path`. Perform every write, dependency install, build, test, screenshot, and generated output only in that external worktree.

6. After the final change, run from the task worktree:

   ```text
   ag2c task verify
   ```

   AG2C recomputes the route from the actual diff and runs only trusted project checkers. When it reports a failure, fix the product cause and verify again. Never weaken policy, remove checks, edit evidence, or touch the canonical checkout to make a task pass.

7. After a passing verification, return to the canonical checkout and run:

   ```text
   ag2c task finish --task <task-id> --message "<concise commit message>"
   ```

   AG2C refuses stale evidence, commits the verified diff, fast-forwards the original branch, records the result, and cleans up when the worktree contains no residual artifacts.

8. Run `ag2c evidence --task <task-id>` and report its plain-language facts with the product outcome: files changed, checks passed, whether a failed attempt was corrected, evidence completeness, and merged commit. Do not teach the user cards, floors, slices, policies, or checker selection unless they explicitly request diagnostics.

## Fail Closed

- A dirty or advanced canonical checkout blocks start, verify, or merge.
- A write outside governed scope blocks verification.
- A governance-control edit blocks an ordinary task.
- Any change after the passing verification requires another verification.
- Missing or invalid evidence means the work is not complete.
