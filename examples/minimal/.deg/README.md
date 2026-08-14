# Example policy entrypoint

The important entry is the exact path or contract, not a broad task sentence:

```bash
deg index build
deg slice --path app:src/client.py --contract app:example.hello@1.0.0
deg check --path app:src/client.py --contract app:example.hello@1.0.0
```

Read `../../docs/ENTRY_SLICING.md` before changing scopes or adding a checker.
