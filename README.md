# DEG

**Deterministic Engineering Governance** turns exact change entries into a small,
reviewable responsibility and verification plan.

[中文说明](README.zh-CN.md) | [Entry Slicing](docs/ENTRY_SLICING.md) | [Policy Reference](docs/POLICY_REFERENCE.md) | [Adoption Guide](docs/ADOPTION.md) | [Architecture](docs/ARCHITECTURE.md)

DEG is a development-time control plane. It observes repositories, maps files and
public contracts to explicit owners, expands declared boundaries, selects trusted
checkers, and records check evidence in a hash-chained ledger. It never becomes a
runtime dependency of the software it governs.

## Why DEG exists

Repository-wide instructions are too broad for focused work, while keyword search
is too weak to decide ownership or acceptance. DEG starts from stable coordinates:

```text
exact path                         public contract
    |                                    |
    v                                    v
primary Floor + local Knowledge    Boundary binding
    |                                    |
    +---- declared dependencies    producer + consumer + scenario
                     \             /
                      verification plan
```

If an entry is missing, ambiguous, or unknown, DEG expands validation
conservatively. It never turns uncertainty into a narrower check plan.

## Install

DEG requires Python 3.11 or newer and has no third-party runtime dependencies.

For the current source release:

```bash
git clone https://github.com/Holosukiyaa/DEG.git
cd DEG
python -m pip install -e .
```

After a PyPI release is published, `python -m pip install deg-governance` installs
the same `deg` command.

## Five-minute start

From the root of an existing repository:

```bash
deg init
```

Review `.deg/manifest.json` and `.deg/policy.json`, then run:

```bash
deg index build
deg index findings
deg slice --path app:src/example.py --output .deg/state/change-slice.md
deg check --path app:src/example.py
deg ledger verify
```

`deg init` creates a deliberately small starter policy. Replace its sample
`git diff --check` checker with the repository's real tests, builds, contract
checks, and end-to-end scenarios.

## Core commands

| Command | Purpose |
| --- | --- |
| `deg init` | Create a starter manifest and policy. |
| `deg index build` | Observe governed files and compute ownership coverage. |
| `deg index verify` | Fail when policy, target revisions, or governed content changed. |
| `deg slice` | Compile a bounded responsibility and check closure. |
| `deg check` | Run only the trusted argv-based checkers selected by the slice. |
| `deg ledger verify` | Verify the evidence event hash chain. |
| `deg doctor` | Check configuration, tools, index freshness, and ledger integrity. |

## Configuration

`.deg/manifest.json` declares where governed repositories live:

```json
{
  "schema": "deg.manifest.v1",
  "project": { "id": "example" },
  "policy": ".deg/policy.json",
  "state_dir": ".deg/state",
  "ledger": ".deg/ledger.jsonl",
  "targets": [
    {
      "id": "app",
      "path": ".",
      "governed_roots": ["src"],
      "exclude": ["src/generated/**"]
    }
  ]
}
```

`.deg/policy.json` declares:

- **Constitution** cards for global invariants;
- **Floor** cards for unique primary ownership;
- **Knowledge** cards for narrow, current navigation;
- **Boundary** cards for cross-component handoffs;
- **Scenario** cards for real consumer workflows;
- relations, public contract bindings, and trusted checkers.

See [`examples/minimal`](examples/minimal) for a complete policy.
Every field is documented in the [Policy Reference](docs/POLICY_REFERENCE.md).

## Design rules

1. A goal describes intent but never decides ownership by itself.
2. Every governed artifact has exactly one primary Floor.
3. Public contracts route through a Boundary to producers, consumers, and scenarios.
4. Knowledge explains current code; it does not own compliance rules.
5. Uncertainty expands reading and verification, not code-edit permission.
6. Static coverage is not product acceptance.
7. Checkers are configured argv arrays and run without a shell.
8. Governed products do not import DEG or require DEG at runtime.

The full method is documented in [Entry Slicing](docs/ENTRY_SLICING.md).

## Project status

DEG `0.1` is an alpha release. Its manifest, policy, slice, index, and ledger
formats are versioned, but compatibility guarantees begin with `1.0`.

## License

MIT
