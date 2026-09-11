# AutoGovern2Code (AG2C)

**Keep using your coding agent. AG2C runs the engineering process behind it.**

[![Release](https://img.shields.io/github/v/release/Holosukiyaa/AutoGovern2Code)](https://github.com/Holosukiyaa/AutoGovern2Code/releases/latest)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

[中文](README.zh-CN.md) · [Adoption](docs/ADOPTION.md) · [Architecture](docs/dev/ARCHITECTURE.md) · [Releases](https://github.com/Holosukiyaa/AutoGovern2Code/releases/latest)

Current release: **v0.10.0** (2026-09-11). Alpha. Windows only. Single-user and local.

AutoGovern2Code is a local open-source governance layer for AI coding. Add a Git project once. The AI entry is a generic MCP connect prompt (placeholders, no vendor lock-in) plus **检测 MCP**. Skill text lives inside that MCP. Work happens in an external Git worktree, the project's own checks run, and only verified bytes fast-forward. Evidence stays on this machine.

The project never receives an `.ag2c` directory, AG2C-generated `AGENTS.md` or `CLAUDE.md`, or evidence files. Product build and runtime never depend on AG2C.

## Use on Windows (no-install portable)

Requirements: Windows 10 or 11 x64. Python is not required. The tray is a Dear ImGui window (Hello ImGui docking shell) and does not embed a browser or Qt. The download is a single folder: `AutoGovern2Code.exe`, `ag2c\`, `git\`, `data\`, and `portable.ini`. It never writes PATH, the registry, the Start Menu, or login startup. Put the folder anywhere — a USB drive works — and move it freely; the first command after a move re-points the project registry and the Git guard hooks to the new location automatically. Shipped MinGit is used even if another Git is on PATH.

1. Download `AutoGovern2Code-Portable-Windows-x64.zip` from the [latest GitHub Release](https://github.com/Holosukiyaa/AutoGovern2Code/releases/latest).
2. Extract it anywhere and double-click `AutoGovern2Code.exe`.
3. Click **Add project** and choose a non-empty Git repository.
4. Click **检测 MCP** once (or run `ag2c mcp health`). Copy the generic connect prompt if your agent needs it. Start a new agent session, then keep working in that repository as usual.

Closing the window hides it to the tray; Git delivery guards on enrolled projects stay active. The portable build does not register login startup; if you want that, drop a shortcut to `AutoGovern2Code.exe` into `shell:startup`.

The package is unsigned, so Windows SmartScreen may warn. Download it only from this repository, compare the file with `SHA256SUMS.txt`, then choose **More info > Run anyway**. The bundled Git remains a separate GPL-2.0 program inside the folder at `git\`. AG2C uses that bundled MinGit for its operations; the project's `.git` and history stay put.

## What you see after adding a project

The desktop window is the normal interface. For each project it shows:

- **AI entry** — generic MCP connect prompt + health check. One local stdio server carries Skill text and live tools. The prompt does not name a vendor or a user path. Git-hook status is inside that health check, not a separate Delivery row.
- **Observed records** — finished tasks, what they implemented or fixed, and whether the run was process-complete.
- **Worktrees, journals, and recent evidence** — open construction copies, versioned logs, and local receipts.
- **Stop / Resume / Uninstall project** — stop leaves the project listed with its archive; resume reconnects it; uninstall deletes that project's governance archive.

A passing construction check is not the same as product acceptance. Until the project declares contracts or boundary/scenario checks, AG2C keeps Product as **undeclared**. Stale or conflicting Knowledge can block product acceptance even after the process finished.

## What happens in the background

```text
normal coding request
  -> connect AG2C MCP once; tools and Skill text arrive with the session
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

Any coding agent that can launch a local stdio MCP server can connect. AG2C writes known client configs when those files already exist on this machine; the connect prompt itself does not name a vendor.

- An agent that connected the AG2C MCP can enter the full automatic workflow.
- An agent that never connected MCP may still be stopped by the Git delivery guard, but AG2C cannot promise it will call tools before editing.
- The local guard is a Git delivery boundary, not an operating-system write ACL. A process that edits Git configuration can bypass it.

This release is Windows-only and single-user. Multi-user coordination and remote evidence exchange are not included.

## Evidence and CI

The tray is the normal evidence view. Maintainers can also inspect locally:

```bash
ag2c evidence
ag2c evidence --task <task-id>
ag2c evidence --format json
```

Full receipts stay in the external store. Commits carry only `AG2C-Task` and `AG2C-Evidence` trailers. Another machine cannot rebuild the Ledger from those digests. Remote CI should run the project's own tests and use branch protection. See [local evidence and CI](docs/dev/CI_VERIFICATION.md).

Knowledge, floors, and public-interface cards are maintainer tools (`ag2c knowledge`, `ag2c govern`). They are not required to start using AG2C. See [automatic governance](docs/dev/AUTOMATIC_GOVERNANCE.md).

## Documentation

- [Adoption, machines, and legacy migration](docs/ADOPTION.md)
- [Automatic governance contract](docs/dev/AUTOMATIC_GOVERNANCE.md)
- [Architecture and evidence model](docs/dev/ARCHITECTURE.md)
- [Directory households](docs/dev/DIRECTORY-CENSUS.md)
- [Local evidence and CI](docs/dev/CI_VERIFICATION.md)
- Agent skills ship inside the package (`src/ag2c/skills/`); MCP clients receive them as instructions and `ag2c://skill/<name>` resources, other agents install them with `ag2c skill install`
- [Contributing](CONTRIBUTING.md)
- [Security policy](SECURITY.md)
- [Changelog](CHANGELOG.md)

## License

MIT
