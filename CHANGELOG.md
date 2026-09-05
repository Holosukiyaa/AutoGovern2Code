# Changelog

## Unreleased

- Add `start-tray.bat` (and `打开管理界面.bat`) so the Qt tray can be started with a double-click from the repo.
- Replace the WinForms tray with a Python Qt host (PySide6). The window uses stock Qt widgets and Qt Style Sheets instead of a hand-drawn control set or an embedded browser. The governance engine stays Python; Qt is an optional `gui` extra and is frozen only into the Windows tray.
- Skin the native tray to the previous light-console look: blue AG mark, 236×76 project cards, pill filters, white file-tree pane and mint knowledge-card pane. Still no browser.
- A portable folder (`portable.ini` next to `AutoGovern2Code.exe`, or `--portable`) keeps evidence in `data\` and MinGit in `git\`. It does not write Start Menu, PATH, or login startup. Moving that folder rebases store paths in the registry and keeps using the shipped Git.
- The tray window is native WinForms: project list, file tree, and knowledge cards. It no longer embeds Edge WebView2. Windows installers and portable copies ship MinGit next to the runtime; a portable Git wins over whatever Git happens to be on PATH so moving project folders does not switch Git implementations.

- Directory households now have exploring, named, and opaque identities. `census --record` refuses opaque claims. `govern tighten` is monotonic; `renew-exploring` keeps construction visible without product acceptance. Narrow `task start` refuses unresolved household debt. Feature tasks cannot delete active households; leftover deletion uses `govern retire` and an optional confirm fuse. New enrollment hangs top-level directories as exploring without naming them, seeds that child set so nested trees stay startable, and later household registration absorbs or carves those placeholders instead of dual-owning. README cards no longer explain every floor.

- Show the tray coverage view as a scrollable project file tree on the left and knowledge cards on the right, with lines between a selected file and the card that covers it. Stop periodic refresh from yanking the view. Each file shows who manages it, which floor owns the path, the latest commit, and whether it looks like leftover work. Search `frontend` to isolate the frontend tree.
- Show a G6 force-directed knowledge graph in the tray window so unowned paths, stale knowledge, abandoned cards, undeclared product checks, and AI-writing work cannot hide in lists.
- Render that graph inside the Windows tray host with embedded Edge WebView2 instead of the IE WebBrowser control.
- Prefer the user's Git when it is on PATH; otherwise download MinGit into the AG2C data directory. Remember each project's Git source so a moved folder keeps bundled Git, or falls back to a download if the original system Git is gone.
- Stop claiming macOS or Linux support in the public README. This release is Windows-only.
- Keep the desktop list cheap, refresh when the window is shown or the store/HEAD changes, and stop wiping details on every redraw.
- Rewrote the GitHub README around v0.8.4: current tray dashboard, process vs product, stop/resume/uninstall, and copied-store recovery. Corrected the matching adoption pages.

## 0.8.4 - 2026-09-01

- Listed actual records and project cards from stored task JSON and one ledger pass, without re-verifying every commit receipt or hashing knowledge files.
- Read kept task records after Stop Governance even when Git no longer points at the store, skipped engine align on stopped projects, and still listed those deliveries on the project card.

## 0.8.3 - 2026-09-01

- Recovered projects copied from another computer when `.git/config` still pointed at a missing user-directory store.
- Treated missing external manifests as stale or relocated instead of “already enrolled”, so enroll, upgrade, doctor --repair, and Add Project share the same recovery path.
- Rebound a copied store under the original project key; when the store is gone, re-enrolled on this computer and said history was not recovered.

## 0.8.2 - 2026-08-29

- Aligned already-enrolled projects to a newer engine without re-slicing floors or rewriting task evidence.
- Registered the Windows tray app in the Start Menu, App Paths, and Apps list so it can be reopened after close.
- Showed a blocking loading overlay while a project is being enrolled or checked.
- Stored what each finished task implemented or fixed, and listed those delivery records in the desktop viewer.

## 0.8.1 - 2026-08-26

- Split process delivery from product acceptance so a finished task no longer reads as product-complete.
- Kept baseline projects explicitly undeclared until contracts or boundary/scenario checks exist, and left that gap in pending updates.
- Let checkers skip with `AG2C_SKIP:` or exit code 78, recorded the local environment, and treated stale or conflicting Knowledge as blocking product acceptance.

## 0.8.0 - 2026-08-26

- Recorded a versioned governance journal after each finished task and showed those versions in the desktop viewer.
- Made Stop Governance keep the project in the list with its store intact, and added Uninstall Project to unregister the project and delete its governance archive.
- Let a stopped project resume governance without a new enrollment when the external store is still present.
- Hashed large working-tree diffs in batch so verification and finish stay usable on generated sites.
- Passed `--all` through guidance retrieval so starting a whole-project task no longer fails after the worktree is created.
- Stabilized the IE desktop viewer layout: document scrolling, visible project names, and centered action labels.

## 0.7.0 - 2026-08-24

- Tracked generated task worktrees through constructing, verified-but-unmerged, diverged, abandoned, and merged states.
- Added `ag2c task list`, `ag2c task refresh`, and `ag2c task abandon` so a moved canonical branch can rebase an open worktree or discard obsolete construction.
- Expanded verification conservatively when a task's actual diff covers most Floors in a target, or when Policy or Manifest changes after the task starts.
- Opened the operating-system folder dialog from the browser viewer when adding a project, and kept the in-page browser only as fallback.
- Ingested project documents and detected public surfaces into Knowledge and boundary cards on first enrollment, and kept them current through `ag2c govern ingest`.
- Added `ag2c govern apply`, `pending`, and `retrieve` plus the `ag2c-governance-update` Skill so stored knowledge changes only with an actor and reason.
- Attached retrieved Knowledge to `ag2c task start` and listed follow-up governance updates after `ag2c task finish`.
- Let the browser viewer recover a missing or rotated loopback session token without showing `desktop session token is required`.
- Show post-merge governance updates in the viewer and settle them with `ag2c govern settle` so the next task starts against current Knowledge.
- Detect rewritten Knowledge claims from synced document leads, mark them as assertion conflicts, expand the slice, and keep `ag2c govern settle` from accepting those conflicts without an explicit sync.

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
