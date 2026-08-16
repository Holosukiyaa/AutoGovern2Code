# Changelog

## 0.3.0 - 2026-08-16

- Established the public AutoGovern2Code (AG2C) product identity.
- Renamed the distribution to `autogovern2code`, the CLI and Python package to `ag2c`, and the Skill to `ag2c-governed-development`.
- Moved tracked governance and local evidence paths to `.ag2c` and versioned public schemas under the `ag2c.*` namespace.
- Moved task branches and external worktree defaults to the `ag2c` namespace.
- Updated Skill installation to the current Codex user-skill location, `~/.agents/skills`.
- Rewrote the GitHub entry documentation around zero-touch use, visible evidence, and the single-user boundary.
- Added `ag2c setup`, `upgrade`, `migrate`, and `doctor --repair` for one-entry adoption, safe tracked upgrades, legacy DEG conversion, and automatic local recovery.
- Added explicit baseline versus structured coverage, top-level area ownership, conservative unknown-path expansion, and native-check refresh during AG2C-managed upgrades.
- Replaced internal evidence narration with a plain-language summary of files, checks, proven correction, blocked actions, commit, and evidence completeness.
- Added a black-box CLI journey from an empty Git project through failed verification, AI correction, fast-forward merge, and final evidence.
- Added reproducible GitHub Release packaging and Node 24 GitHub Actions.

This is the first public identity. `ag2c migrate` converts clean pre-public `.deg` projects while archiving the complete original `.deg` contents and linking the old Ledger digest from the new evidence chain.

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
