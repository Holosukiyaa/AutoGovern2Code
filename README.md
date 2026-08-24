# AutoGovern2Code (AG2C)

**Keep using your coding agent normally. AG2C puts the engineering process behind it.**

[中文](README.zh-CN.md) | [Adoption](docs/ADOPTION.md) | [Automatic governance](docs/AUTOMATIC_GOVERNANCE.md) | [Architecture](docs/ARCHITECTURE.md)

AutoGovern2Code is a local, open-source governance layer for AI coding. Once a Git project is added, a compatible coding agent can discover AG2C through its installed Skill. AG2C routes the change, creates an external worktree, runs project checks, integrates only verified bytes, and keeps the evidence outside the project.

The project itself receives no `.ag2c` directory, no AG2C-generated `AGENTS.md` or `CLAUDE.md`, and no evidence files. Product build and runtime never depend on AG2C.

## Windows: install and choose a project

Requirements: Windows 10 or 11 x64 and Git. Python is not required.

1. Download `AutoGovern2Code-Setup-Windows-x64.exe` from the [latest GitHub Release](https://github.com/Holosukiyaa/AutoGovern2Code/releases/latest).
2. Double-click the installer. It installs for the current user and starts the AG2C tray application.
3. Open AG2C from the system tray, click **Add project**, and choose any non-empty Git repository.
4. Continue using Codex, Claude Code, or another compatible harness in that repository as usual.

The tray application starts with Windows. It lists every managed project and answers only the questions users need: is the project protected, can a coding agent enter correctly, has delivery enforcement been installed, and is there successful evidence? It does not expose cards or ask users to configure governance.

The unsigned community installer may trigger Windows SmartScreen. Download it only from this repository, compare it with `SHA256SUMS.txt`, and use **More info > Run anyway** after verification.

## What happens in the background

```text
normal coding request
  -> Skill detects that this Git repository is managed
  -> AG2C routes responsibility before writing
  -> work happens in an external Git worktree
  -> actual diff determines the final scope
  -> repository-native checks run
  -> evidence is bound to the exact committed bytes
  -> verified commit fast-forwards into the original branch
  -> the tray shows the result and local evidence
```

If the canonical checkout is dirty, the branch moves, checks fail, scope is not governed, or evidence becomes stale, AG2C refuses delivery. A failed check remains in the record even after the AI corrects it.

## Where governance lives

On Windows, AG2C stores its registry, policy, indexes, worktrees, Ledger, and receipts below:

```text
%LOCALAPPDATA%\AutoGovern2Code\
  projects.json
  projects\<project-key>\
```

The Git repository keeps only local, untracked Git configuration pointing to that store and an external `core.hooksPath`. These values are inside `.git/config`; they do not enter commits or travel to another clone.

Removing a project from the tray disconnects local enforcement but keeps its evidence by default. Uninstalling AG2C does not rewrite user repositories or erase evidence.

## Agent compatibility

The installer places the same Agent Skills-compatible Skill in Codex, Claude Code, and the generic user Skill location. The tray reports each detected entry separately.

- A harness that supports Agent Skills can enter the complete automatic workflow.
- An unknown harness may still be stopped by the Git delivery guard, but AG2C cannot promise that it will select the Skill before editing.
- The local guard is a Git delivery boundary, not an operating-system write ACL. A process that deliberately edits Git configuration can bypass it.

This release is intentionally single-user. Multi-user coordination and remote evidence exchange remain future work.

## macOS, Linux, and source development

The desktop installer is currently Windows-only. Python 3.11 or newer can run AG2C from a tagged GitHub source release:

```bash
python -m pip install "git+https://github.com/Holosukiyaa/AutoGovern2Code.git@v0.7.0"
ag2c setup
```

For a local source checkout:

```bash
python -m pip install -e .
ag2c setup
```

These command-line paths are for non-Windows users and contributors. The wheel and source archive attached to a Release are developer artifacts; ordinary Windows users need only the installer.

## Evidence and CI

The tray is the normal evidence interface. Advanced local inspection remains read-only:

```bash
ag2c evidence
ag2c evidence --task <task-id>
ag2c evidence --format json
```

Full governance evidence stays local so the project remains free of governance files. Commits contain only `AG2C-Task` and `AG2C-Evidence` message trailers. Another machine cannot reconstruct the full local Ledger from those digests alone; normal CI should independently run the project's tests and use branch protection. See [local evidence and CI](docs/CI_VERIFICATION.md).

## Knowledge freshness

Knowledge cards can explicitly reference source files or documentation. After a
sync, AG2C stores byte digests for those references. If a selected reference
changes, the next entry slice reports stale Knowledge and conservatively expands
validation to every Floor in the affected target. Existing projects with no
synced Knowledge anchors keep their legacy routing behavior.

```bash
ag2c knowledge status
ag2c knowledge sync --card knowledge.worker \
  --actor codex \
  --reason "Reviewed implementation changes"
ag2c govern ingest --actor codex --reason "Project docs or areas changed"
ag2c govern apply --action add --id knowledge.handbook \
  --title Handbook --summary "Operator contract" --include handbook.md \
  --actor codex --reason "Handbook is now the operator contract"
ag2c govern pending
ag2c govern retrieve --path app:src/value.py --goal "change value"
```

First enrollment ingests README files, docs, and detected public surfaces. Later changes go through `ag2c govern` and require a reason. `ag2c task start` returns the matching Knowledge; after merge, `ag2c task finish` lists new directories or documents that still need a governance update. Synced Knowledge stores the lead line of each referenced file; if that claim is rewritten, status becomes `conflict` and `ag2c govern settle` leaves it until an explicit `ag2c knowledge sync` after review.

## Browser viewer

After installing the Python package, start the local governance viewer with:

```powershell
ag2c viewer --open
```

When developing from this repository, run the source checkout directly:

```powershell
$env:PYTHONPATH="$PWD\src"
python -m ag2c viewer --open
```

On Windows, you can also double-click `start-governance-viewer.cmd` in the repository root (it uses local port `18995`).
Start it from Explorer or a normal user terminal, rather than a restricted code runner: the
governance service needs to write the user-level governance store, project Git configuration,
and AI Skill directories.

The viewer listens only on `127.0.0.1` and generates a session token at startup.
Click **Add project** and choose a Git project in the built-in folder browser to inspect its status,
governance cards, scopes, checkers, Knowledge freshness, index findings, contract
relations, and Ledger summary. Press `Ctrl+C` to stop the viewer.

## Maintainer documentation

- [Adoption and migration](docs/ADOPTION.md)
- [Automatic governance contract](docs/AUTOMATIC_GOVERNANCE.md)
- [Architecture and evidence model](docs/ARCHITECTURE.md)
- [Entry slicing](docs/ENTRY_SLICING.md)
- [Policy reference](docs/POLICY_REFERENCE.md)
- [Local evidence and CI](docs/CI_VERIFICATION.md)
- [Contributing](CONTRIBUTING.md)
- [Security policy](SECURITY.md)

## License

MIT
