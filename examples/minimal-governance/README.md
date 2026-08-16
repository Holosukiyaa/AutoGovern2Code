# External policy fixture

This governance fixture is intentionally outside `examples/minimal`. It proves
that the managed project does not need `.ag2c`, agent instructions, or evidence
files in its own directory.

```bash
ag2c --manifest ../minimal-governance/manifest.json index build
ag2c --manifest ../minimal-governance/manifest.json slice --path app:src/client.py --contract app:example.hello@1.0.0
ag2c --manifest ../minimal-governance/manifest.json check --path app:src/client.py --contract app:example.hello@1.0.0
```

Read `../../docs/ENTRY_SLICING.md` before changing scopes or adding a checker.
