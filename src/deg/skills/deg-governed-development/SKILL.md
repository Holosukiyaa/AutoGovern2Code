---
name: deg-governed-development
description: Enroll a Git project in DEG when the user asks to adopt or enable DEG, then automatically govern every software change in an enrolled repository. Use for any implementation, fix, refactor, test, documentation, configuration, dependency, build, release, or other file-changing request when the repository contains `.deg/enrollment.json` or its root AGENTS.md requires DEG. Route before writing, work only in the DEG-created external Git worktree, run DEG verification after the final change, and finish through DEG so only verified evidence-backed commits reach the canonical checkout.
---

# DEG Governed Development

Treat DEG as the mandatory construction path, not an optional assistant. The user describes the product task normally; do not ask them to operate DEG or learn its governance model.

## Workflow

1. If the user explicitly asks to enroll a project that has no `.deg/enrollment.json`, require a clean Git worktree and run `deg enroll`. This creates and commits the project gate, installs this Skill, and activates local enforcement. Report the enrollment evidence, then use the remaining workflow for future change requests. Never enroll an unrelated repository implicitly.

2. Read the repository `AGENTS.md`. Before any write, run:

   ```text
   deg guard status
   ```

   If the project is enrolled but local activation is missing after a clone, run `deg activate` and check status again. Stop if DEG remains inactive.

3. Inspect the canonical checkout read-only to identify the narrow expected paths and any exact public contract keys. Do not edit, generate, build, install dependencies, or start a service there.

4. Start the task from the canonical checkout:

   ```text
   deg task start --goal "<user request>" --path app:<relative-path>
   ```

   Repeat `--path` and `--contract` as needed. If the change surface is genuinely unknown, use `--all`; never use a vague goal to invent a narrow route.

5. Read the JSON response and move into `worktree.path`. Perform every write, dependency install, build, test, screenshot, and generated output only in that external worktree.

6. After the final change, run from the task worktree:

   ```text
   deg task verify
   ```

   DEG recomputes the route from the actual diff and runs only trusted project checkers. When it reports a failure, fix the product cause and verify again. Never weaken policy, remove checks, edit evidence, or touch the canonical checkout to make a task pass.

7. After a passing verification, return to the canonical checkout and run:

   ```text
   deg task finish --task <task-id> --message "<concise commit message>"
   ```

   DEG refuses stale evidence, commits the verified diff, fast-forwards the original branch, records the result, and cleans up when the worktree contains no residual artifacts.

8. Report the product outcome and DEG evidence facts: task id, interventions, verification attempts, final status, and merged commit. Do not teach the user cards, slices, policies, or checker selection unless they explicitly request diagnostics.

## Fail Closed

- A dirty or advanced canonical checkout blocks start, verify, or merge.
- A write outside governed scope blocks verification.
- A governance-control edit blocks an ordinary task.
- Any change after the passing verification requires another verification.
- Missing or invalid evidence means the work is not complete.
