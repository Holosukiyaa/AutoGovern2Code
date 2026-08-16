# Adoption

Users should not hand-author AG2C governance before receiving value. One tool setup and one explicit project adoption request are the only setup steps; normal coding requests are the daily interface.

## Install

```bash
python -m pip install "git+https://github.com/Holosukiyaa/AutoGovern2Code.git@v0.3.0"
ag2c setup
```

For a local source checkout, use `python -m pip install -e .`. After a PyPI release, `python -m pip install autogovern2code` installs the same CLI and packaged Skill.

`ag2c setup` installs the packaged Skill in `~/.agents/skills`. Use `ag2c skill install --destination <directory>` only for an intentionally isolated Codex setup.

## Enroll once

From a clean Git repository, invoke the Skill:

```text
$ag2c-governed-development enroll this project in AutoGovern2Code
```

Enrollment is refused when the worktree is dirty, empty, not a Git repository, or already enrolled. AG2C commits only its generated enrollment files. Existing `AGENTS.md`, `.gitignore`, and pre-commit behavior are preserved through managed blocks and hook delegation.

Internally the Skill runs `ag2c setup --project .`. The command chooses enrollment, legacy `.deg` migration, or an existing-project upgrade without asking the user to identify the case.

## Work normally

After enrollment, use the AI agent normally. The root `AGENTS.md` requires the Skill for every change request. The Skill performs route, worktree, verification, commit, merge, and evidence commands without asking the user to operate governance.

## Review evidence

`ag2c evidence` is read-only. Its default output summarizes files, checks, proven correction, blocked actions, the merged commit, and evidence completeness. Treat a task as managed successfully only when it was controlled from the start, its final verification passed, its verified digest reached the recorded commit, the merge was fast-forward, and the Ledger remains valid.

## Clone on another machine

Tracked enrollment travels with Git; machine-local activation does not. Install AutoGovern2Code and run `ag2c setup` on the new machine, then open Codex in the clone normally. The repository gate makes the Skill run `ag2c doctor --repair` when `ag2c guard status` reports an inactive clone. Repair restores the Skill, Git guard, existing hook delegation, index, and activation evidence before any project write.

## Upgrade or migrate

- `ag2c upgrade` refreshes AG2C-managed baseline areas, detected native checkers, managed instructions, Skill, hook, and index. It requires a clean canonical worktree and commits only changed tracked governance files.
- `ag2c migrate` converts a clean pre-public `.deg` enrollment. The complete original `.deg` contents are archived under `.ag2c/state/legacy-deg`; the new Ledger records the old Ledger digest instead of rewriting history.
- `ag2c doctor --repair` repairs machine-local activation and never claims a damaged Ledger was repaired.
