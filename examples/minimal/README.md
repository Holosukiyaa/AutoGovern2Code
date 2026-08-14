# DEG Core routing example

This fixture demonstrates the deterministic routing core used automatically by
the DEG Skill. It is intentionally not a separately enrolled Git repository.

Run from this directory:

```bash
deg index build
deg slice --path app:src/client.py --contract app:example.hello@1.0.0
deg check --path app:src/client.py --contract app:example.hello@1.0.0
deg ledger verify
```

The path selects the client Floor. The contract then expands the slice to the
hello Boundary, the application producer Floor, and the consumer Scenario.
