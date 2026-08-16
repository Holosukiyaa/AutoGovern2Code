# Adoption

Users should not hand-author AG2C governance before receiving value. One tool setup and one explicit project adoption request are the only setup steps; normal coding requests are the daily interface.

## Install

On Windows 10 or 11 (x64), download `AutoGovern2Code-Setup-Windows-x64.exe` from the [latest GitHub Release](https://github.com/Holosukiyaa/AutoGovern2Code/releases/latest) and double-click it. It installs per user without administrator access, bundles its own Python runtime, adds `ag2c` to the user PATH, and installs the packaged Skills. It does not create a desktop application or background service.

The current community installer is unsigned. If Windows SmartScreen intervenes, verify the download against the Release's `SHA256SUMS.txt`, then use **More info > Run anyway**. Do not run copies obtained from another site.

On macOS or Linux, install the tagged GitHub source with Python 3.11 or newer:

```bash
python -m pip install "git+https://github.com/Holosukiyaa/AutoGovern2Code.git@v0.5.0"
ag2c setup
```

GitHub Releases are the only distribution channel. The wheel and source archive attached to a Release are developer artifacts. For a local source checkout, use `python -m pip install -e .`.

`ag2c setup` installs the packaged Skill in Codex, Claude Code, and generic Agent Skills user locations. Limit it with a repeatable `--harness` option, or use `ag2c skill install --destination <directory>` for an intentionally isolated harness setup.

The Windows uninstaller removes the bundled runtime, its user PATH entry, and packaged Skills that were not modified after installation. It deliberately does not rewrite enrolled repositories or erase their evidence. Reinstall AG2C before asking an enrolled project to make further governed changes.

## Enroll once

From a clean Git repository, invoke the Skill:

```text
$ag2c-governed-development enroll this project in AutoGovern2Code
```

Enrollment is refused when the worktree is dirty, empty, not a Git repository, or already enrolled. AG2C commits only its generated enrollment files. Existing `AGENTS.md`, `CLAUDE.md`, `.gitignore`, and pre-commit behavior are preserved through managed blocks and hook delegation.

Internally the Skill runs `ag2c setup --project .`. The command chooses enrollment, legacy `.deg` migration, or an existing-project upgrade without asking the user to identify the case.

## Work normally

After enrollment, use the AI agent normally. Root `AGENTS.md` and `CLAUDE.md` instructions require the Skill for every change request. The Skill performs route, worktree, verification, commit, merge, and evidence commands without asking the user to operate governance.

## Review evidence

`ag2c evidence` is read-only. Its default output summarizes files, checks, proven correction, blocked actions, the merged commit, and evidence completeness. Treat a task as managed successfully only when it was controlled from the start, its final verification passed, its verified digest reached the recorded commit, the merge was fast-forward, and the Ledger remains valid.

Every successful task also commits a portable receipt. Use `ag2c ci verify --commit HEAD --rerun`, or the published GitHub Action, to validate it independently from local ignored evidence.

## Clone on another machine

Tracked enrollment travels with Git; machine-local activation does not. Install AutoGovern2Code and run `ag2c setup` on the new machine, then open Codex in the clone normally. The repository gate makes the Skill run `ag2c doctor --repair` when `ag2c guard status` reports an inactive clone. Repair restores the Skill, Git guard, existing hook delegation, index, and activation evidence before any project write.

## Upgrade or migrate

- `ag2c upgrade` refreshes AG2C-managed baseline areas, detected native checkers, managed instructions, Skill, hook, and index. It requires a clean canonical worktree and commits only changed tracked governance files.
- `ag2c migrate` converts a clean pre-public `.deg` enrollment. The complete original `.deg` contents are archived under `.ag2c/state/legacy-deg`; the new Ledger records the old Ledger digest instead of rewriting history.
- `ag2c doctor --repair` repairs machine-local activation and never claims a damaged Ledger was repaired.
