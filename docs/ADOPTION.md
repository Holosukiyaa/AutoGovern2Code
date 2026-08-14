# Adoption

Users should not hand-author DEG governance before receiving value.

## Install

```bash
python -m pip install .
deg skill install
```

Use `python -m pip install deg-governance` after the package is published.

## Enroll once

From a clean Git repository, invoke the Skill:

```text
$deg-governed-development enroll this project in DEG
```

Enrollment is refused when the worktree is dirty, empty, not a Git repository, or already enrolled. DEG commits only its generated enrollment files. Existing `AGENTS.md`, `.gitignore`, and pre-commit behavior are preserved through managed blocks and hook delegation.

## Work normally

After enrollment, use the AI agent normally. The root `AGENTS.md` requires the Skill for every change request. The Skill performs route, worktree, verification, commit, merge, and evidence commands without asking the user to operate governance.

## Review evidence

`deg evidence` is read-only. Treat a task as managed successfully only when it was controlled from the start, its final verification passed, its verified digest reached the recorded commit, the merge was fast-forward, and the Ledger remains valid.

## Clone on another machine

Tracked enrollment travels with Git; machine-local activation does not. The Skill runs `deg activate` when `deg guard status` reports an inactive clone. Activation reinstalls the current Skill, restores the local Git guard, preserves an existing hook delegate, rebuilds the index, and records a new activation event.
