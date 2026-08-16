# Changelog

## 0.6.0 - 2026-08-16

- Added a per-user Windows tray application, adapted from the CartridgeFlow Runtime Shell pattern, with native folder selection, managed-project status, harness readiness, recheck, evidence, and detach actions.
- Moved Manifest, Policy, indexes, worktrees, Ledger, receipts, hooks, and project registry to the per-user external AG2C data directory.
- Made new enrollment leave the project working tree, index, and history unchanged; only local Git configuration points to external governance.
- Added transactional externalization for tracked `.ag2c` and legacy `.deg` projects while preserving evidence outside the project.
- Replaced project instruction gates with Skill-based discovery and kept the external pre-commit guard as the delivery boundary.
- Changed completed commits to carry only `AG2C-Task` and `AG2C-Evidence` trailers while retaining full receipts locally.
- Removed the portable-receipt GitHub Action because remote runners cannot honestly reconstruct deliberately external local evidence.
- Updated the one-click installer to start the tray application at user login and extended Windows smoke coverage for project cleanliness and startup registration.
- Moved the routing example's governance fixture outside the example project and rewrote adoption, architecture, evidence, and entry-slicing documentation around low-learning-cost use.

## 0.5.0 - 2026-08-16

- Added a per-user Windows 10/11 x64 installer that bundles the AG2C runtime, requires no Python or administrator access, installs supported harness Skills, and creates no desktop application or background service.
- Made local Git guards invoke either the exact source interpreter or the frozen AG2C executable, so enrolled projects remain enforceable with the self-contained Windows runtime.
- Added safe Skill removal that preserves locally modified Skill directories during uninstall.
- Added Windows CI and Release smoke tests covering installation, Skill discovery, real Git-project enrollment, guard activation, and uninstall.
- Made tagged GitHub source the only CI installation source and added SHA-256 checksums to Release assets.
- Reframed the Windows entry documentation around downloading and double-clicking the single clearly named installer; wheel and source archives are documented as developer artifacts.

## 0.4.0 - 2026-08-16

- Added Codex, Claude Code, and generic Agent Skills installation adapters while keeping one harness-neutral governance engine.
- Added a managed `CLAUDE.md` entry gate alongside `AGENTS.md` so enrolled projects enter governance automatically in either supported harness.
- Added recoverable lifecycle transactions for enrollment, upgrade, and legacy migration, including file, staging, and Git-hook restoration after pre-commit failure or process interruption.
- Added tracked, self-digesting task receipts that bind source commit, exact Git bytes, route, policy objects, trusted checks, correction, and blocked-action evidence.
- Added `ag2c ci verify` to validate portable receipts from Git objects and optionally recompute routing and rerun trusted checks in a clean checkout.
- Added a reusable GitHub composite Action and documented required-check integration for protected branches.
- Kept GitHub Releases as the sole distribution channel, with wheel and source archives attached to each tagged release.
- Improved native Node test detection for npm, pnpm, Yarn, and Bun projects.
- Kept the product focused on invisible single-user governance: no desktop application, configuration dashboard, or mandatory user input was added.

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
