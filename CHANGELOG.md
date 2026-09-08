# Changelog

## Unreleased

- Verify is now a quality gate, not only a process gate. Checkers marked `always: true` join every verify check plan regardless of the slice, and enrollment marks native test checkers (`check.python` / `check.go` / `check.rust` / `check.node`) always-on. Checkers with `parse: unittest` get a zero-regression gate: failures recorded in the project store baseline stay green, any NEW failure blocks verify, and failures that start passing shrink the baseline automatically. Record existing debt once with `ag2c govern test-baseline`; tune checkers without hand-editing policy via `ag2c govern checker --id ... --always on|off --parse unittest|none --timeout N`.
- Room-scoped test selection: a directory household (knowledge card with a jurisdiction) may bind floor-stage checkers, so a `parse: unittest` checker attached to a room runs exactly when the slice touches that room — large suites can be split per room while the zero-regression gate still applies. Plain prose knowledge cards still cannot own checkers.
- `ag2c_task_verify` no longer hits the MCP timeout on long suites: the call runs verify on a worker thread, waits up to 45 seconds, and returns a `running` marker when the suite is still going — call the same tool again to poll. Results and gate errors are delivered exactly once; duplicate concurrent verifies are impossible.
- Docs-only diffs skip the always-on test suites: when every changed artifact is prose (`*.md` / `*.rst` / `*.txt` / `*.adoc` or a `docs/` directory), always+parse checkers record an explicit `skipped` with a `docs-only diff` reason instead of burning a full suite run. Code changes still always run the tests; checkers with a required `implementation` are never skipped.
- Canonical write watchdog: the tray digest endpoint now carries a TTL-cached `guard` field (`canonicalDirty` / `openTasks`), and the tray status bar shows a red warning — "canonical 在非任务窗口被修改——可能有改动绕开了治理流程" — whenever the canonical checkout is dirty with no open task. The digest itself stays subprocess-free; the guard probe is cached for 10 seconds and can never break polling.
- Crowded 一文件一张 rooms fold their file cards into collapsible subdirectory group nodes (kind `group`, e.g. `routers/` under backend, `flow-workbench/` under frontend-pages): rooms with 6+ file cards get one group per subdirectory holding 2+ cards. Groups join ordinal numbering, layout, hulls, links, and click-to-expand like modules, but stay collapsed by default; the room status still counts every file card.
- Floor titles no longer leak file names: a floor whose includes are root-level file lists (`.gitattributes`, `README.md`, …) fell back to showing the first file as the module title ("gitattributes"). Root-file patterns now yield no module path, so the card title is used; nested file patterns name their directory.
- File-card rehoming engine (`ag2c.rehome.rehome_file_card`): moving a card to another room is a real refactoring that rides the governed loop — the card scope updates first (so the task snapshots the final policy), then a task worktree does `git mv`, rewrites the dotted module path across every `.py` file (imports and quoted patch-target strings alike, without clobbering lookalike module names), records census for the old and new rooms, verifies, and merges. Any failure abandons the task and rolls the card scope back, leaving canonical untouched. v1 supports Python files only, refuses `__init__.py`, relative-import modules, target collisions, same-directory no-ops, and subdirectory escapes.
- Tray rehome API: `POST /api/household/rehome` starts a background rehome job (the governed pipeline can take minutes while tests run) and `GET /api/household/rehome-status?id=…` polls it, reporting `running` / `done` (with the move summary) / `failed` (with the rollback-safe error).
- Lineage drag-and-drop rehoming: the graph payload now marks single-file Python cards as drag sources (`rehomeSource`) and real rooms / subdirectory groups as drop targets (`rehomeRoom` + `rehomeSubdir`; exploring households never accept drops). In the tray, dragging a file card onto a room or group opens an inline confirmation strip ("把 X 搬到 Y？将开治理任务自动完成：git mv + 全仓 import 重写 + 测试验证，失败自动回滚"); confirming starts the background job, a spinner line tracks it, completion refreshes the tree, and failure surfaces the rolled-back error in the status bar.
- Tray crash observability: the tray (often run under pythonw, where a crash leaves no console output) now installs `faulthandler` plus `sys.excepthook` / `threading.excepthook` at startup, appending startup headers, uncaught tracebacks, thread crashes, and native-fault stacks to `logs/tray-crash.log` under the AG2C data root (or `%TEMP%`). Frame callbacks are wrapped so the log names the exact callback that died.
- Fix missing backdrop for fourth-layer lineage cards: the outward-hull pass in `_lineage_draw_hulls` only iterated knowledge cards, so an expanded subdirectory group (e.g. `routers/` under backend) never drew the hull behind its children — cards like 4-3-1-1~4-3-1-7 floated with no 底盘. Group nodes now draw their outward hull too; covered by a drawing-level regression test.
- Fix tray crash on clicking/pressing a lineage card: the rehoming drag source sat on a `Text()` line, which has no imgui ID, so a mouse press hit `IM_ASSERT(0)` inside `BeginDragDropSource`; the C++ exception unwound mid-frame and the process died at EndFrame with "Missing EndGroup()". The drag source now passes `source_allow_null_id` (imgui's official flag for dragging from text items).
- MCP tool `ag2c_rehome`: agents can move a file card into another room/subdirectory through the same governed pipeline the tray uses (scope update → task worktree `git mv` + import rewrite → census → verify → merge, rollback on failure). It runs in the background like `ag2c_task_verify` — answers within 45s or returns a job id to poll — and only one rehome runs at a time per server.
- The tray lineage tree nests directory rooms under their longest-prefix parent room, mirroring the real directory hierarchy (core/* rooms under the core room, frontend pages/styles under the frontend room). Exploring households never act as nesting parents, so census scaffolding cannot swallow named rooms.

- Packaged a fifth Skill, `ag2c-full-liquidation` (全量清算): an opt-in-only pipeline distilled from a production rebuild — assess and gate on explicit user decisions, physical cleanup through governed tasks (wedged-policy escape, retirement-references refactoring, generated-artifact locks with logical digests), ingest re-baseline, proper-subset re-census, room cards, per-file cards for core rooms, an evidence-backed audit document, and a prioritized cleanup queue. The Skill, the MCP initialize instructions, and the connect prompt all state it runs only when the user explicitly asks — never proactively.

## 0.9.0 - 2026-09-07

- The Windows release is now a no-install portable zip (`AutoGovern2Code-Portable-Windows-x64.zip`): extract anywhere and run — no PATH, registry, Start Menu, or login-startup writes. Moving the whole folder self-heals on the next command: the project registry rebases to the new location and enrolled projects get their Git guard hooks re-pointed, so a moved or copied folder never drops the guard. The Inno Setup installer is retired.
- The MCP server ships production hard rules in its initialize instructions: record the census before verify, knowledge-card titles are 20 characters max, rerun verify through the CLI when the MCP call times out, and finish tasks from the canonical checkout. `ag2c_census` exposes `all`.
- Household updates preserve entrypoints and checker bindings unless the caller passes new values; `ag2c_household` can now set entrypoints, checkers, and a scenario `command` over MCP, and the new `ag2c_tighten` tool tightens or renews a directory household without dropping to the CLI.
- First product acceptance check: `scripts/check_desktop_boot.py` boots the desktop backend, waits for `/api/status`, and shuts it down through the token API. It is attached to `knowledge.ag2c-gui` as a scenario checker and pinned in unittest, so a tray that cannot boot fails verification.
- The tray hot-reloads: every 5 seconds it polls `/api/project/digest` (git HEAD plus policy/ledger/journal/census mtimes, pure file IO) and reloads projects, details, and open panels when the fingerprint changes.
- Tray startup is faster: memoized repository roots, parallel project cards, and a short project-list cache; a full-window splash covers the remaining initial load.
- 审计 / 施工 / 实际记录 / AI 入口 moved out of the details pane into draggable floating windows; 审计 is renamed 操作日志, and 实际记录 shows the governance journal history.
- Restored the native Windows title bar (the custom caption layer is gone), fixed file-tree selection flicker, fixed lineage column overlap, and hid zero-file placeholder parents from the lineage graph by default.
- The tray backend server joins a Windows Job Object so the OS kills it when the tray exits; no more orphaned `ag2c desktop serve` processes holding worktree locks.
- The tray no longer shows **交付 / 已控制**. Git-hook status is inside MCP health. AI entry stays a generic connect prompt plus **检测 MCP**.
- AI entry is only a generic MCP connect prompt (placeholders `<python>` / `<ag2c-src>`, no vendor names, no user paths) plus MCP health (`ag2c mcp health` / tray **检测 MCP**). Skill text stays inside MCP. Enrollment keeps the project's `.git` and forces bundled MinGit for AG2C operations. The Git hook remains the delivery gate.
- AG2C is a local stdio MCP server. Packaged Skills ship as initialize `instructions` and `ag2c://skill/*` resources. `ag2c mcp install` writes local client configs when those files exist. Copy-prompt is no longer the tray AI entry.
- The tray no longer has buttons to set 未打标 / 整夹一张 / 一文件一张. Coverage tags stay visible for supervision; the agent sets them. Healthy cards no longer show 在册, and the card list no longer prints `0 个文件`.
- `ag2c task start` guidance now includes `lineage`: the knowledge-card 谱系 as a coding index (rooms and per-file 设计思路). The development Skill tells the agent to read it before writing.
- Code-file knowledge cards (`.py` and other source suffixes) are no longer tagged 文档; that flag stays on prose documents such as README.
- Clicking a leftover parent that excludes a carved child no longer lights the child's files. Clicking the child household still focuses the files it owns.
- The portable.ini layout test skips on a task worktree that does not have that operator file.
- Lineage opens each deeper mapping in a new column to the right. Clicking a file in the tree selects only that file and its file card; clicking the folder selects the directory card. No mapping-level dropdown.
- File cards for a 一文件一张 directory hang under that directory in the tray (third level), not beside it as extra modules. Expand the directory card to see them.
- Packaged a fourth Skill, `ag2c-knowledge-authoring`: after coverage tags exist, the agent reads the files and writes detailed 设计思路 cards (`整夹一张` one room card, `一文件一张` one card per code file). `ag2c-directory-census` now sets those tags in the same census pass. The copy-prompt installs all four Skills.
- A vanished project folder no longer runs Git or becomes the selected tray project. Missing directories sort last, details stay empty, and a successful load clears the red Git banner. Tests keep TemporaryDirectory enrollments out of the operator registry.
- Directory rooms carry a coverage tag the user can supervise: 未打标, 整夹一张, or 一文件一张. Untagged rooms do not paint 设计思路 onto files. Naming requires a tag; 一文件一张 naming requires one knowledge card per code file. `python.exe` and `pythonw.exe` count as the same Git-guard runtime.
- Re-including a parent household glob that recaptures an existing child room is refused (`cannot-overlap-household`). AG2C does not save dual owners.
- Packaged a third Skill, `ag2c-directory-census`, as the tree-investigation entry. The copy-prompt installs it with the development and governance-update pair.
- Registering or tightening a named directory household that still has unexplained child directories is refused. AG2C no longer saves that catch-all as a 黑盒.
- ADOPTION, ARCHITECTURE, and the GitHub README now describe copy-prompt AI entry and wrapping every previous Git hook. They no longer say AG2C detects which harness has the Skill.
- AI 入口 is only 复制提示词. The tray no longer reports 还没接到 from harness detection. `ag2c guard status` is managed when the Git guard is on; a stale Skill home does not unmanage the project.
- Activating AG2C seizes the existing Git repo by wrapping every previous hook name under `core.hooksPath`. History and remotes stay in the project's `.git`.
- Packaged Skills declare `version:` matching the AG2C package. The copy-prompt names that version and digest; each paste tells the agent to replace its installed copy if they differ. Latest means this AutoGovern2Code. `ag2c skill version` prints the required identity.
- Adding a project no longer requires a clean working tree. The card stays in 需要处理 until the checkout is clean; task start still refuses dirty construction. Ignore checkout `portable.ini` and `.grok/` so launching the tray does not dirty a self-governed tree. Tray errors wrap instead of clipping.
- Desktop host is only Hello ImGui (`start-tray.bat` → `packaging/windows/tray.py` → `ag2c.imgui_tray`). HTML/G6 viewer files, Qt/WinForms/WebView2 hosts, `ag2c viewer`, `qt_tray.py`, and duplicate launchers are gone. The local API is token-header JSON only; folder picking stays in the ImGui process.
- Drop the heavy enroll/worktree/verify integration tests. Remaining tests are the tray host, CLI surface, and in-memory engine checks.
- Fix `ag2c project uninstall` crashing on a missing `--remove-data` flag. The coverage payload is files and knowledge cards only (no G6 combo/edges). The local project list no longer returns an empty HTML `migrations` field.
- Stop the Hello ImGui tray from spawning extra tiny loading windows: apply the dock layout only on first use, keep one 1280×860 window, and skip font reloads after a DPI rebuild.
- Hide Windows console flashes from git, checkers, and the desktop server (`CREATE_NO_WINDOW`, prefer `pythonw`).
- Show the Hello ImGui window immediately: start the local API on a background thread before GLFW, list projects first, then align/details without blocking the first frame.
- Stop the tray from drawing two selection boxes on mouse click: unique ImGui ids per row, one selected key, no nav cursor, and hover no longer uses the same fill as selected.
- Load Microsoft YaHei (or SimSun) as the Hello ImGui default font from `C:\Windows\Fonts`, then merge Font Awesome.
- Move the Hello ImGui freeze entry and license notice to `packaging/windows/`. Portable copies no longer fall back to `build/dev-tray`.
- A portable folder (`portable.ini` next to `AutoGovern2Code.exe`, or `--portable`) keeps evidence in `data\` and MinGit in `git\`. It does not write Start Menu, PATH, or login startup.
- Directory households now have exploring, named, and opaque identities. `census --record` refuses opaque claims. Feature tasks cannot delete active households; leftover deletion uses `govern retire`.
- Show the tray coverage view as a scrollable project file tree on the left and knowledge cards on the right. Search `frontend` to isolate the frontend tree.
- Nest the tray file tree so folders like `src` expand to their children instead of rendering as empty leaves. Clicking a folder opens it; the first level starts expanded.
- File tree and knowledge cards are bidirectional: each file shows 未认领 / card title / 重复认领, clicking a file highlights 同类 and the card, clicking a card expands and lights its files in place, and the inspector shows 设计思路.
- Stop the tray from exiting when a knowledge-card file list is drawn: Hello ImGui `selectable` always receives the required selected flag. Cache project details by Git HEAD and status so a second launch does not rebuild the census.
- Stop the 项目 menu from crashing (shortcut must be a string). Refresh rebuilds the census and shows a scanning bar. Swap 详情 and 知识卡片 so details sit next to the file tree.
- Darken the Windows title bar to match the tray. Clicking a knowledge card collapses folders outside its files so the jurisdiction is visible as a thin path.
- Add a read-only 谱系 canvas with the bundled MIT imgui-node-editor, laid out like G6 antv-dagre-combo: the project and knowledge cards are nodes, modules are combo hulls, cubic-vertical arrows go from the project to cards (or to a collapsed combo). Nodes with children expand and collapse with +/− and start collapsed. Clicking a node highlights it and updates 详情 without panning. Five panes keep a default layout on every launch.
- Prefer the user's Git when it is on PATH; otherwise download MinGit into the AG2C data directory.
- Stop claiming macOS or Linux support in the public README. This release is Windows-only.
- Rewrote the GitHub README around v0.8.4: current tray dashboard, process vs product, stop/resume/uninstall, and copied-store recovery.

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
