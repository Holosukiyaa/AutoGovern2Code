# Automatic governance

An enrolled project is governed by default. The human task request is the only task input; Codex translates it into deterministic DEG coordinates internally.

## Before the first write

The Skill confirms activation, reads the canonical checkout without modifying it, identifies expected paths and exact contracts, then asks DEG to start a task. Unknown scope uses conservative all-project routing rather than a guessed narrow route.

DEG records the original branch and HEAD, compiles the initial route, and creates an external `deg/<task-id>` Git worktree. The returned worktree is the only permitted write location.

## During implementation

The AI may inspect, edit, install dependencies, build, test, and generate artifacts inside the task worktree. The canonical checkout remains an integration target, not a workspace.

## Verification

`deg task verify` ignores the AI's claimed scope and recomputes from the actual Git diff. Newly touched governed paths expand the route and produce an intervention record. Ungoverned paths and changes to DEG controls fail closed.

The current Policy selects trusted argv-only checkers. Failed checks remain in evidence. When a later attempt passes, DEG records an `ai-correction-proven` intervention. If a checker itself changes governed bytes, verification fails and must be rerun against the new bytes.

## Integration

`deg task finish` requires the final diff digest to equal the passing verification event recorded in the Ledger. It commits that change in the task worktree, recomputes the committed diff so an existing pre-commit hook cannot substitute unverified bytes, confirms the canonical checkout is still clean and unchanged, and merges with `--ff-only`. Any mismatch preserves the worktree and blocks integration.

## What the user sees

Normal Codex output should focus on product work. DEG details are reduced to evidence facts: whether management started before writes, interventions, failed and passing attempts, the final commit, merge mode, cleanup state, and Ledger integrity.
