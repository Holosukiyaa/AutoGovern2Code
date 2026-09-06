# Automatic governance

Once a local Git clone is added to AG2C, governance becomes the default construction path for compatible coding agents. The user's product request remains the only task input.

## Entry

The installed Skill checks `ag2c guard status` for file-changing work. AG2C discovers the external Manifest through local Git configuration; the agent does not search for governance files in the project. Missing activation is repaired before writing. An unknown or incompatible harness is reported honestly by the tray rather than treated as ready.

## Before the first write

The Skill reads the canonical checkout without modifying it and identifies expected paths or exact public contracts. Unknown scope uses conservative all-project routing. AG2C captures the branch and HEAD, creates an external task record and external Git worktree, and returns the only permitted construction directory.

## During implementation

The AI may inspect, edit, install dependencies, build, test, and generate artifacts inside the task worktree. The canonical checkout remains an integration target. Each project has independent external policy, worktrees, Ledger, and evidence.

`ag2c task list` tracks each generated worktree. Passing verification marks the task verified but unmerged until `task finish`. If the work is obsolete, `ag2c task abandon` removes the worktree and records the discarded attempt. If the canonical branch moved, `ag2c task refresh` rebases the open worktree onto the current HEAD and requires another verification.

## Verification

`ag2c task verify` calculates scope again from the actual Git diff. Newly touched governed paths expand the route and leave an intervention record. Ungoverned paths fail closed. A change that spans most Floors in a target, or a Policy/Manifest change after the task started, expands validation conservatively.

Only policy-declared argv checkers run. Failed attempts remain in evidence; a later pass records that the AI corrected a failure. If a checker changes governed bytes, verification becomes stale and must run again.

## Integration

`ag2c task finish` requires the final diff digest to equal the passing verification event. AG2C commits in the task worktree, validates the Git objects again, checks that the canonical checkout and source HEAD are unchanged, and integrates with `--ff-only`. The commit message receives only task and evidence digest trailers; the full receipt remains in the external project store.

## Why Codex CLI (and friends) feel tightly bound

Yes: **Skill for entry, Git hook for delivery.** Neither is enough alone.

1. **Skill (soft).** Enrollment copies `ag2c-governed-development` into Codex, Claude Code, Cursor, and `~/.agents/skills`. A compatible harness is supposed to run `ag2c guard status` before the first write, start a task, and edit only the returned worktree. A model can ignore that. Reading copies live in [docs/skills](skills/README.md).
2. **Git hijack (hard).** Activation sets `core.hooksPath` to an external hook that runs `ag2c guard pre-commit`. That hook refuses commits in the canonical worktree, refuses branches not named `ag2c/…`, and refuses a worktree that does not match an open task record. The tray can be closed. `git commit` on `main` still dies.
3. **Worktree isolation.** Construction is a second Git checkout. Even when the agent obeys the Skill, the product branch does not move until `task finish` fast-forwards verified bytes.

Older in-repo `AGENTS.md` / `CLAUDE.md` blocks were a fourth reminder. They are gone: the Skill is installed outside the project. The hook is still the part an agent cannot talk its way around.

## Enforcement boundary

The pre-commit guard rejects delivery from the canonical checkout or an unmanaged branch. It is deliberately independent from the tray window. It does not prevent arbitrary filesystem writes, so an agent that ignores the Skill may dirty the canonical checkout before the guard blocks its commit. AG2C reports that state instead of calling it successful.

## User-visible result

Normal agent output should focus on the product change. The tray and read-only evidence view explain what happened: changed files, checks, failed attempts and correction, blocked actions, final commit, merge mode, and evidence integrity. Cards, policies, slices, and checker selection remain maintainer internals.
