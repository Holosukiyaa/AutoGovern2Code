# AG2C Core routing example

This fixture demonstrates the deterministic routing core used automatically by
the AG2C Skill. It is intentionally not a separately enrolled Git repository.

Run from this directory:

```bash
ag2c index build
ag2c slice --path app:src/client.py --contract app:example.hello@1.0.0
ag2c check --path app:src/client.py --contract app:example.hello@1.0.0
ag2c ledger verify
```

The path selects the client Floor. The contract then expands the slice to the
hello Boundary, the application producer Floor, and the consumer Scenario.
