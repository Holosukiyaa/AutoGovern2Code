# Architecture and evidence model

AutoGovern2Code (AG2C) separates the user experience from its enforcement internals. The user talks to Codex normally. The enrolled repository and installed Skill make governance automatic.

```text
normal coding request
        |
root AGENTS.md + installed Skill       automatic entry before writes
        |
task record + external Git worktree    isolated construction
        |
Policy + SQLite index + slicer         deterministic responsibility route
        |
trusted argv-only checkers             repository-native proof
        |
verified change digest                 binds proof to exact bytes
        |
fast-forward integration               controlled delivery
        |
JSON task record + hash-chain Ledger   durable local evidence
```

## Enrollment

The Skill uses `ag2c setup --project .` on a clean Git repository. Setup selects first enrollment, legacy migration, or an existing-project upgrade. First enrollment:

1. detects the current tracked project roots;
2. creates a conservative baseline Policy split by detected top-level project areas and a Manifest;
3. adds a managed `AGENTS.md` block;
4. commits those reviewable enrollment files;
5. installs the packaged `ag2c-governed-development` Skill;
6. activates a machine-local pre-commit guard;
7. builds the initial index and records enrollment evidence.

The tracked enrollment is portable. Machine paths, generated indexes, local hooks, active task records, and Ledger data live under ignored `.ag2c/state` or other ignored files.

## Coverage maturity

Policy records one of two user-visible coverage levels:

- `baseline`: AG2C owns detected project areas and runs all detected native checks conservatively. Unknown paths expand routing rather than being guessed into a narrow owner.
- `structured`: maintainers have declared finer responsibilities, relations, and optionally public contracts and scenarios.

`ag2c upgrade` refreshes only a baseline marked `managed_by: ag2c`. It never overwrites a project-maintained structured Policy. `ag2c coverage` exposes the current level without requiring users to read cards or slices.

## Local recovery

The Skill checks `ag2c guard status` before the first write. `ag2c doctor --repair` restores the packaged Skill, exact Python hook, prior hook delegation, activation record, and index. It validates but does not rewrite the evidence Ledger. Tracked upgrades require a clean canonical checkout and produce a narrow maintenance commit plus Ledger event.

## Automatic task state

Each task moves through machine states:

```text
active -- passing verification for current bytes --> completed
   |                                                ^
   +-- failed verification remains active           |
   +-- changed bytes invalidate the passing proof ---+
```

The canonical checkout and source HEAD are captured at task start. AG2C creates a `ag2c/<task-id>` branch in an external sibling worktree. Writes in the canonical checkout, a changed source HEAD, ungoverned paths, governance-control mutations, failed checks, or stale evidence all block integration.

## Correction evidence

AG2C distinguishes participation from correction. A start record proves only that AG2C was present. A correction requires a machine-observed event, such as:

- the actual diff expanding beyond the initial route;
- a canonical-checkout write being detected and blocked;
- a trusted checker failing before a later passing attempt;
- a checker mutating governed bytes and forcing another verification;
- integration being blocked because the canonical branch changed.

The task record links every intervention to a Ledger event digest. A later passing verification does not erase earlier failures.

## Exact-byte binding

Before checks, AG2C rebuilds the index and compiles a route from the actual diff. The verification stores a digest of the full binary Git diff plus untracked file content in a dedicated hash-chained Ledger event. `task finish` validates that event, recomputes the digest before commit, then recomputes it from the resulting commit. Any source edit or pre-commit-hook mutation requires another verification.

## Git guard

The local pre-commit guard rejects commits from the canonical checkout and from worktree branches not created under `ag2c/`. Activation uses the exact Python interpreter that installed AG2C and delegates an existing user pre-commit hook after the AG2C checks pass.

The guard is one layer, not the only trust boundary. The Skill, task state machine, clean-checkout checks, exact diff digest, trusted checkers, fast-forward-only integration, and Ledger verification must all agree before completion.

## Internal routing model

Manifest, Policy, cards, scopes, public contract bindings, SQLite index, and entry slicing remain internal deterministic machinery. They are documented for maintainers and integrations in [Entry Slicing](ENTRY_SLICING.md) and [Policy Reference](POLICY_REFERENCE.md), but are not part of ordinary user operation.

## Detachability

AG2C may inspect and test a governed repository. Product code must not import AG2C, read AG2C state, or require AG2C during build or runtime. Removing local AG2C state must not change product behavior; it only removes the governed development path and its evidence.

## Current limits

Version `0.3` governs one local Git repository per enrollment and one integrator at a time. The local guard is not an operating-system write ACL. A hostile process with filesystem and Git-configuration access can bypass local controls; remote enforcement requires protected branches and required CI checks, planned for the team version.
