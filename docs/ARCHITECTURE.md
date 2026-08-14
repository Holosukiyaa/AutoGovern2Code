# Architecture

DEG separates policy, current repository facts, and historical evidence because
they have different owners and lifecycles.

```text
.deg/policy.json               normative and descriptive responsibility model
          |
          v
.deg/state/index.sqlite        rebuildable repository observation
          |
          v
entry slice                    bounded responsibility and checker closure
          |
          v
trusted checker processes      repository-native evidence
          |
          v
.deg/ledger.jsonl              append-only hash-chained event history
```

## Components

### Manifest

Declares project identity, target repository locations, governed roots, state
location, policy location, and ledger location. It contains placement, not rules.

### Policy

Declares cards, scopes, explicit relations, exact public contract bindings, and
checker argv. Policy is human-reviewed input and is never inferred from semantic
similarity.

### Index

Observes governed files, Git revision state, content digests, and primary
ownership coverage. It is disposable and must be rebuilt after source or policy
changes.

### Slicer

Compiles path and contract entries into a deterministic closure. Unknown or
ambiguous coordinates produce conservative expansion.

### Checker runner

Runs only checker argv declared in policy, with `shell=False`. Product-native
commands remain the authority for build, test, conformance, and scenario facts.

### Ledger

Stores canonical JSON events. Every event includes its sequence, the previous
event digest, and its own digest. Removing, reordering, or rewriting an event
breaks verification.

## Dependency boundary

DEG may read and execute checks against governed targets. Governed application
code must not import DEG, read DEG state, or require DEG during build or runtime.

## Acceptance states

DEG reports `static`, `floor`, `boundary`, `scenario`, and `complete` separately.
A stage with no policy checker is `not-applicable`; a scoped slice that does not
select an existing stage is `not-run`. Complete acceptance is only available for
`deg check --all` when every policy checker passes.

## Current limits

Version `0.1` indexes file identity and ownership, not language symbols or import
graphs. Dependencies are policy-declared. Ledger locking is local-filesystem
oriented; teams that require concurrent distributed writers should place event
append behind a single CI job or external append service.
