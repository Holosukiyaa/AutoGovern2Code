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
python -m pip install "git+https://github.com/Holosukiyaa/AutoGovern2Code.git@v0.6.0"
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
