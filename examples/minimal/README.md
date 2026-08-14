# DEG minimal example

This example demonstrates a producer, a consumer, a public contract binding, and
a scenario checker.

Run from this directory:

```bash
deg index build
deg slice --path app:src/client.py --contract app:example.hello@1.0.0
deg check --path app:src/client.py --contract app:example.hello@1.0.0
deg ledger verify
```

The path selects the client Floor. The contract then expands the slice to the
hello Boundary, the application producer Floor, and the consumer Scenario.
