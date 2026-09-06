# Architecture and evidence model

AutoGovern2Code separates a small user interface from its deterministic enforcement engine. The tray chooses projects and reports results; it is not required for an active Git guard or an in-progress governed task.

```text
tray project selection
        |
external registry + Git-local pointer       enrollment without project files
        |
Agent Skill + guard status                  automatic agent entry
        |
external task record + Git worktree         isolated construction
        |
Policy + SQLite index + entry slicer        deterministic responsibility route
        |
repository-native argv checkers             product proof
        |
exact-byte digest + hash-chain Ledger       local governance proof
        |
evidence trailers + fast-forward merge      controlled delivery
        |
tray evidence view                          user-readable outcome
```

## External project store

`storage.py` owns a per-user registry and one directory per managed clone. The generated project key combines a readable repository name with a hash of its absolute path, so repositories with the same name remain independent.

On Windows the root is `%LOCALAPPDATA%\AutoGovern2Code`; `AG2C_DATA_ROOT` can isolate tests and development. Linux and macOS use `XDG_DATA_HOME` or the normal per-user data directory fallback.

The canonical repository stores only two local Git config values, `ag2c.manifest` and `ag2c.project-key`, plus an external `core.hooksPath`. Nothing is added to the working tree or index. External worktrees are stored below the matching project store.

## Enrollment and migration

New enrollment detects tracked top-level areas and native tests, writes a conservative Manifest and Policy externally, builds the index, installs Skills, creates the guard, and records an enrollment event. Dirty state is allowed at registration time but blocks task start.

Legacy `.deg` and `.ag2c` projects are externalized transactionally. Existing evidence is archived in the project store, AG2C-managed instruction blocks are removed, and the tracked governance directories are deleted in one maintenance commit. Rollback restores files, staging, and hook configuration if the commit fails.

## Coverage maturity

- `baseline`: generated conservative ownership for detected project areas; unknown paths broaden routing and checks.
- `structured`: maintainer-authored responsibilities, relationships, public contracts, and scenarios.

`ag2c upgrade` may refresh only a baseline marked `managed_by: ag2c`. It does not replace a maintainer-owned structured Policy.

## Task state and correction evidence

```text
active -- passing verification for current bytes --> verified
   |                                                |
   +-- failed verification remains active           +-- finish --> completed
   +-- changed bytes return the task to active      |
   +-- canonical HEAD moves --> refresh or abandon  +-- abandon --> abandoned
```

Open worktrees are tracked independently of the tray window. `ag2c task list` reports whether a worktree is constructing, verified but unmerged, diverged from the canonical HEAD, missing, completed, or abandoned.

The task captures the canonical branch, source HEAD, and Policy/Manifest digests before construction. If the canonical branch later advances, `ag2c task refresh` rebases the task worktree onto the new HEAD and invalidates passing evidence. If history no longer contains the source commit, refresh refuses and the worktree must be abandoned. A large actual diff, or a changed Policy or Manifest, expands validation conservatively. Verification records actual-diff expansion, dirty-canonical detection, failed trusted checks, checker mutation, and integration conflicts. A later pass never erases an earlier failure.

## Exact-byte binding

Verification binds source commit, normalized paths, Git file modes, symlink targets, deletions, and clean-filtered Git object identities. `task finish` checks this digest before commit and reconstructs it from final Git objects after commit, so source edits or a mutating hook invalidate stale evidence.

The full self-digesting receipt binds route, checks, acceptance, Manifest, Policy, correction, and blocked actions. It is written under the external project store. Final commits contain only `AG2C-Task` and `AG2C-Evidence` trailers. Those trailers identify local evidence but do not make the full Ledger portable.

## Desktop boundary

The Windows tray host is a Dear ImGui application through Hello ImGui (`imgui-bundle`, MIT). It starts the frozen AG2C runtime as a child process on a random `127.0.0.1` port, uses a per-session header token, and shows projects, the file tree, a read-only knowledge-card pedigree canvas (`imgui-node-editor`, MIT), knowledge cards, and an inspector in Hello ImGui dock spaces. Network calls run on a worker thread. It does not embed Edge WebView2, does not use PySide/Qt, and does not import ImGuizmo, ImmVision, or 3D plotting modules. The Python runtime serves a local JSON API for the tray. It does not ship HTML viewer assets, cookies, or an in-page folder browser. The server rejects non-local hosts and origins and sends a restrictive content security policy.

The UI can add, inspect, recheck, open, and stop managing projects. It cannot edit Policy or evidence. Hello ImGui's portable folder dialog handles project selection, so users never type paths. Knowledge cards, unowned directories, stale or abandoned cards, undeclared product checks, and open AI worktrees are flagged in the tree, card list, and inspector.

## Git guard and limits

The external pre-commit guard rejects commits from the canonical checkout and branches not created by AG2C, then delegates any previous hook. The Skill, task state, diff digest, trusted checks, fast-forward integration, and Ledger must all agree before success.

This is a single-user local governance boundary, not an operating-system ACL. A hostile process with filesystem and Git-config access can bypass it. A harness without Agent Skills may be blocked at delivery without entering the full workflow before editing. Remote team coordination and portable evidence exchange are not implemented in this release.

## Detachability

Product code must not import AG2C, read its external store, or require its tray or runtime during build and execution. Removing AG2C changes the development path only, never product behavior.
