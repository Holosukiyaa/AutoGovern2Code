# Adoption

Users should not hand-author AG2C governance before receiving value. Installation and one explicit enrollment request are the only setup steps; normal coding requests are the daily interface.

## Install

```bash
python -m pip install "git+https://github.com/Holosukiyaa/AutoGovern2Code.git"
ag2c skill install
```

For a local source checkout, use `python -m pip install -e .`. After a PyPI release, `python -m pip install autogovern2code` installs the same CLI and packaged Skill.

The default Skill destination is `~/.agents/skills`. Use `ag2c skill install --destination <directory>` only for an intentionally isolated Codex setup.

## Enroll once

From a clean Git repository, invoke the Skill:

```text
$ag2c-governed-development enroll this project in AutoGovern2Code
```

Enrollment is refused when the worktree is dirty, empty, not a Git repository, or already enrolled. AG2C commits only its generated enrollment files. Existing `AGENTS.md`, `.gitignore`, and pre-commit behavior are preserved through managed blocks and hook delegation.

## Work normally

After enrollment, use the AI agent normally. The root `AGENTS.md` requires the Skill for every change request. The Skill performs route, worktree, verification, commit, merge, and evidence commands without asking the user to operate governance.

## Review evidence

`ag2c evidence` is read-only. Treat a task as managed successfully only when it was controlled from the start, its final verification passed, its verified digest reached the recorded commit, the merge was fast-forward, and the Ledger remains valid.

## Clone on another machine

Tracked enrollment travels with Git; machine-local activation does not. Install AutoGovern2Code and its Skill on the new machine, then open Codex in the clone normally. The repository gate makes the Skill run `ag2c activate` when `ag2c guard status` reports an inactive clone. Activation restores the Git guard, preserves an existing hook delegate, rebuilds the index, and records a new activation event before any project write.
