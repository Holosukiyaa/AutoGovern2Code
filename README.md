# AutoGovern2Code (AG2C)

**Use Codex normally. AG2C automatically keeps every project change isolated, checked, evidenced, and safely integrated.**

[中文](README.zh-CN.md) | [Adoption](docs/ADOPTION.md) | [How automatic governance works](docs/AUTOMATIC_GOVERNANCE.md) | [Architecture and evidence](docs/ARCHITECTURE.md)

AutoGovern2Code is a local, open-source governance layer for AI coding. It is not another project-management UI and it does not ask users to operate cards, policies, or approval screens. Once a Git project is enrolled, its root instructions and AG2C Skill put Codex on the governed construction path before the first write.

## What changes for the user

Before AG2C:

```text
Ask Codex to change the project -> hope the right files and checks were used
```

After one-time enrollment:

```text
Ask Codex to change the project
  -> route responsibility before writing
  -> create an external Git worktree
  -> implement only there
  -> recompute scope from the actual diff
  -> run trusted project checks
  -> bind passing evidence to the exact bytes
  -> fast-forward the verified commit
  -> retain a tamper-evident record
```

The user still says things like "fix this bug" or "add this feature." Governance stays in the background. Failures and proof remain visible.

## Install once

Requirements: Python 3.11 or newer, Git, and Codex CLI or the Codex IDE extension.

Install from GitHub:

```bash
python -m pip install "git+https://github.com/Holosukiyaa/AutoGovern2Code.git@v0.3.0"
ag2c setup
```

For local development from a cloned checkout:

```bash
python -m pip install -e .
ag2c setup
```

`ag2c setup` installs the Skill in `~/.agents/skills`, where current Codex clients discover user-level skills. It does not enroll the current directory unless the Skill explicitly calls `ag2c setup --project .`.

## Enroll one project

Open Codex in a clean, non-empty Git repository and say:

```text
$ag2c-governed-development enroll this project in AutoGovern2Code
```

Enrollment creates and commits a reviewable root `AGENTS.md` gate plus `.ag2c` policy files. It also installs a machine-local Git guard, detects common native tests, builds the initial responsibility index, and records enrollment evidence.

That is the last governance workflow the user needs to start. Future development requests automatically use AG2C because Codex reads the enrolled repository instructions before working.

AG2C starts with conservative baseline coverage split by detected top-level project areas. Unknown or new paths broaden the route and checks instead of being guessed into a narrow area. Maintainers can later declare structured responsibilities and public contracts without changing the user workflow.

## Automatic recovery and upgrades

The Skill runs `ag2c guard status` before a change. After a clone, interpreter move, missing hook, or Skill update it runs `ag2c doctor --repair` before writing. `ag2c upgrade` refreshes AG2C-managed areas and native checkers in a clean project. `ag2c migrate` converts a clean pre-public `.deg` enrollment, archives the complete original `.deg` contents under ignored state, and links the old Ledger digest from the new evidence chain.

## What AG2C proves

- The canonical checkout was not used as a construction directory.
- A task and external worktree existed before the first governed write.
- The final route was calculated from the actual Git diff, not only the AI's plan.
- Failed checks stayed in history and a later pass proved the correction.
- The passing evidence covered the exact bytes that were committed.
- The original branch was still clean and unchanged at integration time.
- The verified commit entered through a fast-forward merge.
- Task evidence still agrees with the hash-chained Ledger.

Any missing fact produces an incomplete management result, never a false success.

## Read the evidence

The evidence interface is read-only:

```bash
ag2c evidence
ag2c evidence --task <task-id>
ag2c evidence --format json
```

The default output stays in user language: files changed, checks passed, failed attempts corrected, blocked unsafe actions, final commit, and evidence completeness. `--format json` retains the complete machine-readable record.

## Safety boundary

AG2C is detachable development-time infrastructure. Enrolled products do not import AG2C and do not require it to build, test, or run. Removing the local AG2C installation removes the governed construction path, not product functionality.

Version `0.3` targets one local user and one Git repository per enrollment. The local guard is not an operating-system security boundary. Shared teams still need protected remote branches and required CI checks.

The first supported harness is Codex. The deterministic CLI and persisted contracts are designed so other coding-agent Skills can be added later without changing enrolled products.

## Maintainer documentation

- [Adoption and clone activation](docs/ADOPTION.md)
- [Automatic governance contract](docs/AUTOMATIC_GOVERNANCE.md)
- [Architecture and evidence model](docs/ARCHITECTURE.md)
- [Entry slicing](docs/ENTRY_SLICING.md)
- [Policy reference](docs/POLICY_REFERENCE.md)
- [Contributing](CONTRIBUTING.md)
- [Security policy](SECURITY.md)

## License

MIT
