# Changelog

## 0.3.0 - 2026-08-16

- Established the public AutoGovern2Code (AG2C) product identity.
- Renamed the distribution to `autogovern2code`, the CLI and Python package to `ag2c`, and the Skill to `ag2c-governed-development`.
- Moved tracked governance and local evidence paths to `.ag2c` and versioned public schemas under the `ag2c.*` namespace.
- Moved task branches and external worktree defaults to the `ag2c` namespace.
- Updated Skill installation to the current Codex user-skill location, `~/.agents/skills`.
- Rewrote the GitHub entry documentation around zero-touch use, visible evidence, and the single-user boundary.

This is the first public identity. Earlier local `0.x` enrollment files are not migrated; re-enroll disposable pre-release test projects with `0.3`.

## 0.2.0 - 2026-08-15

- Repositioned AG2C as automatic governance for enrolled Git projects.
- Added one-time enrollment with a root AGENTS gate and packaged Codex Skill.
- Added machine-local Git guard activation with existing hook delegation.
- Added isolated external task worktrees and fast-forward-only integration.
- Added actual-diff rerouting, exact change digests, and stale-evidence rejection.
- Bound each verification and the final committed bytes to hash-chained evidence.
- Added evidence for blocked writes, scope correction, failed checks, and proven fixes.
- Added read-only task evidence output; users do not operate Policy or slicing.

## 0.1.0 - 2026-08-14

- Introduced versioned Manifest and Policy formats.
- Added deterministic path and contract entry slicing.
- Added conservative routing for unowned, ambiguous, and unknown entries.
- Added rebuildable SQLite ownership index and freshness verification.
- Added argv-only checker orchestration and staged acceptance states.
- Added a hash-chained JSONL evidence ledger.
- Added English and Chinese Entry Slicing documentation.
