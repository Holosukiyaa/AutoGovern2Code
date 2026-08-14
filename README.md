# DEG

**Keep AI changes on a governed path and retain proof that DEG corrected and verified the work.**

[中文](README.zh-CN.md) | [Automatic governance](docs/AUTOMATIC_GOVERNANCE.md) | [Evidence architecture](docs/ARCHITECTURE.md)

DEG is not a project-management UI. After one-time enrollment, people keep using Codex normally. The agent automatically follows the repository gate, routes responsibility, works in an external Git worktree, runs trusted project checks, and can integrate only the exact change covered by current evidence.

## What users get

- AI cannot commit directly from the canonical checkout.
- Work is routed before the first write; uncertainty broadens verification.
- Actual changes outside the initial route trigger a recorded correction.
- Failed checks block completion; a later passing attempt proves the correction loop.
- Any change after verification invalidates the evidence.
- A dirty or advanced canonical branch blocks integration.
- Every task records its route, interventions, checks, commit, and fast-forward merge.

## One-time setup

DEG requires Python 3.11 or newer. From a source checkout:

```bash
python -m pip install .
deg skill install
```

After the package is published, `python -m pip install deg-governance` installs the same command and Skill payload.

In a clean Git project, tell Codex:

```text
$deg-governed-development enroll this project in DEG
```

The Skill creates the root `AGENTS.md` gate, detects the current project surface and common native tests, commits the enrollment files, installs the local Git guard, and records the first Ledger evidence.

After that, never start DEG manually. Ask Codex for normal product work.

## Automatic path

```text
normal user request
  -> DEG Skill before the first write
  -> read-only route
  -> external task worktree
  -> implementation
  -> route actual diff and run trusted checks
  -> commit the verified bytes
  -> fast-forward the original branch
  -> retain task and Ledger evidence
```

Users do not need to learn cards, Policy, Floors, Boundaries, Scenarios, or Checker selection. Those remain internal mechanisms for deciding what the agent must read and prove.

## Read-only evidence

```bash
deg evidence
deg evidence --task <task-id>
deg evidence --format json
```

Evidence reports whether DEG controlled the task from the beginning, what it blocked or corrected, verification attempts and outcomes, the merged commit, and Ledger integrity.

## Delivery contract

A managed task is complete only when:

1. DEG created the task record and external worktree before any write.
2. The canonical checkout stayed clean and at the original HEAD.
3. Every actual change was governed and routed from the final diff.
4. The verified change digest still matches the bytes being committed.
5. Every selected trusted checker passed.
6. The task commit reached the original branch by fast-forward.
7. The task evidence and Ledger hash chain are valid.

Missing evidence is an incomplete management result, never a successful one.

## Boundary

DEG is a detachable development-time control plane. Governed products do not import DEG or require it to build or run. Version `0.2` targets a local, single-user Git workflow; remote branch protection, concurrent teams, and hosted evidence are future work.

## License

MIT
