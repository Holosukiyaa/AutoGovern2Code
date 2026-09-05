# AutoGovern2Code (AG2C)

**Keep using your coding agent. AG2C runs the engineering process behind it.**

[![Release](https://img.shields.io/github/v/release/Holosukiyaa/AutoGovern2Code)](https://github.com/Holosukiyaa/AutoGovern2Code/releases/latest)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

[中文](README.zh-CN.md) · [Adoption](docs/ADOPTION.md) · [Architecture](docs/ARCHITECTURE.md) · [Releases](https://github.com/Holosukiyaa/AutoGovern2Code/releases/latest)

Current release: **v0.8.4** (2026-09-01). Alpha. Windows only. Single-user and local.

AutoGovern2Code is a local open-source governance layer for AI coding. Add a Git project once. A compatible agent discovers AG2C through an installed Skill, works in an external Git worktree, runs the project's own checks, and fast-forwards only verified bytes. Evidence stays on this machine.

The project never receives an `.ag2c` directory, AG2C-generated `AGENTS.md` or `CLAUDE.md`, or evidence files. Product build and runtime never depend on AG2C.

## Install on Windows

Requirements: Windows 10 or 11 x64. Python is not required. The tray is a native Windows window. A portable copy is a folder with `AutoGovern2Code.exe`, `git\`, and `data\`; drop `portable.ini` beside the exe (or pass `--portable`) and it will not write PATH, Start Menu, or login startup. Shipped MinGit is used even if another Git is on PATH.

1. Download `AutoGovern2Code-Setup-Windows-x64.exe` from the [latest GitHub Release](https://github.com/Holosukiyaa/AutoGovern2Code/releases/latest).
2. Double-click the installer. It installs for the current user, puts AG2C in the Start Menu, and starts the tray app.
3. Open AG2C from the tray or Start Menu, click **Add project**, and choose a non-empty Git repository.
4. Keep using Codex, Claude Code, Cursor, or another Agent Skills-compatible tool in that repository as usual.

The tray starts with Windows. Closing the window hides it; Git delivery guards on enrolled projects stay active.

The community installer is unsigned, so Windows SmartScreen may warn. Download it only from this repository, compare the file with `SHA256SUMS.txt`, then choose **More info > Run anyway**. A downloaded Git remains a separate GPL-2.0 program under `%LOCALAPPDATA%\AutoGovern2Code\runtime\git`. Each project remembers whether it used your Git or the bundled copy, so a moved folder keeps that choice.

## What you see after adding a project

The desktop window is the normal interface. For each project it shows:

- **Agent entry** — which supported tools have the current Skill (Codex, Claude Code, Cursor, generic Agent Skills).
- **Delivery** — whether the external store and Git guard are connected.
- **Observed records** — finished tasks, what they implemented or fixed, and whether the run was process-complete.
- **Worktrees, journals, and recent evidence** — open construction copies, versioned logs, and local receipts.
- **Stop / Resume / Uninstall project** — stop leaves the project listed with its archive; resume reconnects it; uninstall deletes that project's governance archive.

A passing construction check is not the same as product acceptance. Until the project declares contracts or boundary/scenario checks, AG2C keeps Product as **undeclared**. Stale or conflicting Knowledge can block product acceptance even after the process finished.

## What happens in the background

```text
normal coding request
  -> Skill sees that this Git repository is managed
  -> AG2C routes responsibility before writing
  -> work happens in an external Git worktree
  -> the actual diff determines the final scope
  -> the project's own checks run
  -> evidence is bound to the exact committed bytes
  -> a verified commit fast-forwards into the original branch
  -> the tray shows the result and the local record
```

AG2C refuses delivery when the canonical checkout is dirty, the branch moved and the worktree was not refreshed, checks fail, the change is outside governed scope, or evidence is stale. A failed check stays in the record after the agent later fixes it.

If the original branch moves while a task is open, refresh the worktree onto the current HEAD and verify again, or abandon that worktree.

## Where governance lives

On Windows:

```text
%LOCALAPPDATA%\AutoGovern2Code\
  projects.json
  projects\<project-key>\
```

Policy, indexes, task worktrees, Ledger, receipts, and journals live there. The Git repository keeps only local, untracked values in `.git/config` (`ag2c.manifest`, `ag2c.project-key`, and an external `core.hooksPath`). They are not committed and do not travel to another clone.

**Stop governance** disconnects the local guard and keeps the project in the list. **Resume** reconnects it without a new enrollment while the store is still present. **Uninstall project** removes that archive. Uninstalling AG2C itself does not rewrite user repositories.

Copying a folder to another PC can leave `.git/config` pointing at a missing user-directory store. Add Project and `ag2c doctor --repair` treat that as relocated or stale: a copied store is rebound; a missing store is re-enrolled and the old history is marked unrecoverable.

## Agent compatibility

The installer places the same Agent Skills-compatible Skills in Codex, Claude Code, Cursor (`~/.cursor/skills`), and the generic user Skill location (`~/.agents/skills`). The tray reports each entry separately.

- A harness that supports Agent Skills can enter the full automatic workflow.
- An unknown harness may still be stopped by the Git delivery guard, but AG2C cannot promise it will select the Skill before editing.
- The local guard is a Git delivery boundary, not an operating-system write ACL. A process that edits Git configuration can bypass it.

This release is Windows-only and single-user. Multi-user coordination and remote evidence exchange are not included.

## Evidence and CI

The tray is the normal evidence view. Maintainers can also inspect locally:

```bash
ag2c evidence
ag2c evidence --task <task-id>
ag2c evidence --format json
```

Full receipts stay in the external store. Commits carry only `AG2C-Task` and `AG2C-Evidence` trailers. Another machine cannot rebuild the Ledger from those digests. Remote CI should run the project's own tests and use branch protection. See [local evidence and CI](docs/CI_VERIFICATION.md).

Knowledge, floors, and public-interface cards are maintainer tools (`ag2c knowledge`, `ag2c govern`). They are not required to start using AG2C. See [automatic governance](docs/AUTOMATIC_GOVERNANCE.md).

## Documentation

- [Adoption, machines, and legacy migration](docs/ADOPTION.md)
- [Automatic governance contract](docs/AUTOMATIC_GOVERNANCE.md)
- [Architecture and evidence model](docs/ARCHITECTURE.md)
- [Entry slicing](docs/ENTRY_SLICING.md)
- [Policy reference](docs/POLICY_REFERENCE.md)
- [Local evidence and CI](docs/CI_VERIFICATION.md)
- [Contributing](CONTRIBUTING.md)
- [Security policy](SECURITY.md)
- [Changelog](CHANGELOG.md)

## License

MIT
