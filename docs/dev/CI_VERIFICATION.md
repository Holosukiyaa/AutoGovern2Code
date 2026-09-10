# Local evidence and CI

AG2C keeps full governance evidence outside the project. This is the deliberate cost of leaving user repositories free of policy, Ledger, and receipt files.

## What local evidence binds

Each completed task stores a self-digesting receipt in the external project store. It binds:

- source commit, final paths, Git modes, and exact file bytes;
- final responsibility route and acceptance state;
- trusted checker commands and results;
- exact Manifest and Policy objects;
- failed attempts, proven correction, and blocked actions;
- final commit and the hash-chain Ledger event.

The commit message contains `AG2C-Task` and `AG2C-Evidence` trailers. They let the local store find and cross-check the matching receipt without adding a file to the project.

## Local verification

On the machine that manages the clone:

```bash
ag2c ci verify --commit HEAD
ag2c ci verify --commit HEAD --rerun
```

The first form validates the commit against the local receipt. `--rerun` also requires a clean checkout at that commit, recomputes the route, confirms the checker plan, and runs those checks again.

The tray is the normal read-only interface. `ag2c evidence` exposes the same facts for agents and maintainers.

## What remote CI can verify

A fresh CI runner receives Git history but not a developer's external store. The evidence digest proves identity only when the matching receipt is available; it cannot reconstruct missing evidence. AG2C therefore does not publish a composite Action that pretends to verify local evidence from Git alone.

Remote CI should independently run the repository's native tests, linters, builds, and security checks. Team repositories should protect their integration branch and require those checks. This proves the submitted product on the CI machine; it does not prove the developer's complete local construction history.

Portable, signed evidence export is a future team feature. It will require an explicit transport and trust model rather than silently putting governance internals back into every project.

## Trust boundary

Local evidence proves that AG2C's recorded route, checks, bytes, and integration agree. It does not prove that the selected checks are sufficient, that the host is uncompromised, or that a repository administrator cannot bypass branch rules.
