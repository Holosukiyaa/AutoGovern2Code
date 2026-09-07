# Automatic governance

Once a local Git clone is added to AG2C, governance becomes the default construction path for compatible coding agents. The user's product request remains the only task input.

## Entry

The AI entry is a local stdio MCP server (`ag2c mcp`). Packaged Skills are initialize `instructions` and `ag2c://skill/*` resources; the generic connect prompt is `ag2c://connect`. The tray shows only that prompt (placeholders, no vendor or user-path lock-in) and **检测 MCP**. `ag2c mcp health` handshakes the server. AG2C does not detect which harness is installed. Tools check `ag2c_guard_status` for file-changing work. AG2C discovers the external Manifest through local Git configuration; the agent does not search for governance files in the project. Missing Git activation is repaired before writing. `managed` means the Git guard is on, not that a Skill folder was found.

## Before the first write

MCP tools read the canonical checkout without modifying it and identify expected paths or exact public contracts. Unknown scope uses conservative all-project routing. AG2C captures the branch and HEAD, creates an external task record and external Git worktree, and returns the only permitted construction directory.

## During implementation

The AI may inspect, edit, install dependencies, build, test, and generate artifacts inside the task worktree. `ag2c task start` returns `guidance.lineage`: the knowledge-card 谱系 for the routed rooms, used as the coding index before writing. The canonical checkout remains an integration target. Each project has independent external policy, worktrees, Ledger, and evidence.

`ag2c task list` tracks each generated worktree. Passing verification marks the task verified but unmerged until `task finish`. If the work is obsolete, `ag2c task abandon` removes the worktree and records the discarded attempt. If the canonical branch moved, `ag2c task refresh` rebases the open worktree onto the current HEAD and requires another verification.

## Verification

`ag2c task verify` calculates scope again from the actual Git diff. Newly touched governed paths expand the route and leave an intervention record. Ungoverned paths fail closed. A change that spans most Floors in a target, or a Policy/Manifest change after the task started, expands validation conservatively.

Only policy-declared argv checkers run. Failed attempts remain in evidence; a later pass records that the AI corrected a failure. If a checker changes governed bytes, verification becomes stale and must run again.

## Integration

`ag2c task finish` requires the final diff digest to equal the passing verification event. AG2C commits in the task worktree, validates the Git objects again, checks that the canonical checkout and source HEAD are unchanged, and integrates with `--ff-only`. The commit message receives only task and evidence digest trailers; the full receipt remains in the external project store.

## Why entry and delivery are both required

Yes: **MCP for entry, Git hook for delivery.** Neither is enough alone. Connecting MCP cannot replace the hook.

1. **MCP (soft).** `ag2c mcp` serves the Skill workflow as `instructions`, full SKILL.md as resources, and live tools (`ag2c_task_start` returns `guidance.lineage`). Enrollment writes this server into local MCP configs. A model can ignore tools. Reading copies still live in [docs/skills](skills/README.md) for humans.
2. **Git hijack (hard).** The project's `.git` stays put. Activation sets `core.hooksPath` to an external directory: AG2C `pre-commit` runs first, then every hook that was already there (husky, leftover, default `.git/hooks`) is forwarded by name. That guard refuses commits in the canonical worktree, refuses branches not named `ag2c/…`, and refuses a worktree that does not match an open task record. History and remotes are unchanged. AG2C operations use bundled MinGit when it is available. The tray can be closed. `git commit` on `main` still dies.
3. **Worktree isolation.** Construction is a second Git checkout. Even when the agent obeys MCP tools, the product branch does not move until `task finish` fast-forwards verified bytes.

Older in-repo `AGENTS.md` / `CLAUDE.md` blocks were a fourth reminder. They are gone. Connecting MCP is the user-facing entry; the hook is still the part an agent cannot talk its way around.

## Enforcement boundary

The pre-commit guard rejects delivery from the canonical checkout or an unmanaged branch. It is deliberately independent from the tray window. It does not prevent arbitrary filesystem writes, so an agent that ignores MCP tools may dirty the canonical checkout before the guard blocks its commit. AG2C reports that state instead of calling it successful.

## User-visible result

Normal agent output should focus on the product change. The tray and read-only evidence view explain what happened: changed files, checks, failed attempts and correction, blocked actions, final commit, merge mode, and evidence integrity. Cards, policies, slices, and checker selection remain maintainer internals.
