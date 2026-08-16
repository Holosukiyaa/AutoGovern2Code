# Portable receipts and CI verification

Local evidence is useful for explaining what the AI did, but a different machine cannot trust a developer's ignored state directory. AG2C therefore writes one tracked receipt into every governed task commit.

## What a receipt binds

A receipt under `.ag2c/receipts/<task-id>.json` records:

- the task's source commit and final changed paths;
- a digest computed from Git modes, paths, and exact file bytes;
- the selected responsibility route and acceptance state;
- every trusted checker result;
- the exact tracked Manifest and Policy objects used for verification;
- failed attempts, proven correction, and blocked-action counts.

The receipt has its own canonical JSON digest. `ag2c ci verify` reconstructs the product change from Git objects, excluding the receipt itself, and rejects mismatched paths, content, policy, checks, or receipt identity.

## Verify locally

The checkout must contain the commit history back to the receipt's source commit:

```bash
ag2c ci verify --commit HEAD
ag2c ci verify --commit HEAD --rerun
```

`--rerun` additionally requires a clean checkout at that commit. AG2C rebuilds its index, recomputes the route from the committed diff, confirms that the checker plan is unchanged, and runs the trusted checks into temporary evidence state.

## GitHub Actions

Add a workflow such as `.github/workflows/ag2c.yml`:

```yaml
name: AG2C proof

on:
  pull_request:
  push:
    branches: [main]

permissions:
  contents: read

jobs:
  verify:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v6
        with:
          ref: ${{ github.event.pull_request.head.sha || github.sha }}
          fetch-depth: 0
      - uses: Holosukiyaa/AutoGovern2Code/.github/actions/verify@v0.5.0
```

The Action installs the matching AG2C release, validates the receipt, and reruns checks. Set `rerun: "false"` only when another job already runs the exact trusted commands.

For team repositories, make this job a required branch-protection check. The local Git guard controls a single-user construction path; remote branch protection controls what collaborators can push or merge.

## Boundary

The receipt proves that the committed bytes, declared route, and recorded checks agree. It does not prove that the checker commands are sufficient for the product, that the host operating system was uncompromised, or that a repository administrator cannot replace both policy and branch rules. Those are project and platform trust decisions.
