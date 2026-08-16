# Policy Reference

> Maintainer reference: Policy is internal configuration generated at enrollment
> and consumed by the Skill and AG2C Core. Ordinary users are not expected to edit
> or understand it.

AG2C reads two versioned JSON documents from the external per-project store.
On Windows this is normally
`%LOCALAPPDATA%\AutoGovern2Code\projects\<project-key>`. The repository's local
Git config points to the Manifest. Unknown schema versions fail closed.

## Manifest

Generated location: `<project-store>/manifest.json`

```json
{
  "schema": "ag2c.manifest.v1",
  "project": {"id": "orders", "root": "C:/code/orders"},
  "policy": "policy.json",
  "state_dir": "state",
  "ledger": "ledger.jsonl",
  "targets": [
    {
      "id": "api",
      "path": "services/api",
      "governed_roots": ["src", "contracts"],
      "exclude": ["src/generated/**", "src/**/__pycache__/**"]
    }
  ]
}
```

| Field | Meaning |
| --- | --- |
| `schema` | Must be `ag2c.manifest.v1`. |
| `project.id` | Stable lowercase project identity. |
| `project.root` | Absolute path of the locally managed Git clone. |
| `policy` | Policy path relative to the external Manifest directory. |
| `state_dir` | Rebuildable state directory relative to the external Manifest. |
| `ledger` | Hash-chained evidence file. |
| `targets[].id` | Stable id used in path and contract entries. |
| `targets[].path` | Repository path relative to the project root; `.` is allowed. |
| `targets[].governed_roots` | Files or directories that require ownership. |
| `targets[].exclude` | Glob patterns removed from observation. |

Target paths remain relative to `project.root`; governance storage location does
not change how project paths are routed. An explicit maintainer fixture may use
a relative `project.root`, resolved from the Manifest directory.

## Policy

Generated location: `<project-store>/policy.json`

```json
{
  "schema": "ag2c.policy.v1",
  "coverage": {
    "level": "baseline",
    "strategy": "conservative",
    "managed_by": "ag2c",
    "areas": ["src", "tests"]
  },
  "cards": [],
  "relations": [],
  "contracts": [],
  "checkers": []
}
```

### Coverage

| Field | Meaning |
| --- | --- |
| `level` | `baseline` for conservative generated ownership, or `structured` for project-maintained responsibility and contracts. |
| `strategy` | Must be `conservative`; unknown entries expand routing and checks. |
| `managed_by` | `ag2c` permits `ag2c upgrade` to refresh generated areas and native checkers; any other value leaves Policy ownership with the project. |
| `areas` | Informational top-level areas detected for baseline coverage. |

Coverage metadata does not weaken routing rules. Missing metadata is inferred for older Policy files, while `ag2c upgrade` writes the explicit current form for AG2C-generated baselines.

### Cards

```json
{
  "id": "floor.api",
  "type": "floor",
  "title": "Orders API",
  "summary": "Owns HTTP order operations.",
  "scopes": [
    {
      "target": "api",
      "include": ["src/http/**"],
      "exclude": ["src/http/generated/**"],
      "ownership": "primary"
    }
  ],
  "checkers": ["check.api"],
  "references": ["docs/orders-api.md"]
}
```

| Field | Meaning |
| --- | --- |
| `id` | Stable card identity. |
| `type` | `constitution`, `floor`, `boundary`, `knowledge`, `scenario`, or `task`. |
| `title` | Short human-readable name. |
| `summary` | Current responsibility or navigation statement. |
| `scopes` | Target-qualified path selectors. |
| `checkers` | Trusted checker ids owned by the card. |
| `references` | Files to open during the hydration phase. |

Only Floor cards may use `ownership: primary`. Every Floor requires a primary
scope and at least one Floor checker. Knowledge and Task cards cannot own
checkers.

### Scope patterns

Patterns are slash-normalized and case-sensitive:

- `src/api.py` matches one exact file;
- `src/http/*` matches one path segment below `src/http`;
- `src/http/**` matches the directory and all descendants;
- `src/**/__pycache__/**` uses `**` as zero or more directories.

An artifact is covered only when exactly one primary Floor scope matches it.
Reference and supporting scopes do not participate in primary ownership.

### Relations

```json
{"source": "floor.worker", "type": "depends_on", "target": "floor.api"}
```

| Type | Required shape | Effect |
| --- | --- | --- |
| `depends_on` | Floor -> Floor | Adds an implementation dependency to the slice. |
| `explains` | Knowledge -> Floor | Adds local navigation for a selected Floor. |
| `producer` | Boundary -> Floor | Declares a public handoff producer. |
| `consumer` | Boundary -> Floor | Declares a public handoff consumer. |
| `governs` | Constitution -> any card | Declares a global invariant relationship. |
| `related_to` | Any card pair | Records a non-routing relationship. |

### Public contract bindings

```json
{
  "target": "api",
  "id": "orders.cancel",
  "version": "2.0.0",
  "boundary": "boundary.orders",
  "scenarios": ["scenario.cancel-order"]
}
```

The resulting entry is `api:orders.cancel@2.0.0`. A binding requires:

- an exact target, contract id, and version;
- a Boundary card;
- at least one producer and consumer relation from that Boundary;
- at least one Scenario card;
- Boundary and Scenario checkers.

### Checkers

```json
{
  "id": "check.api",
  "stage": "floor",
  "target": "api",
  "command": ["python", "-B", "-m", "pytest", "tests/api", "-q"],
  "cwd": ".",
  "timeout": 300
}
```

| Field | Meaning |
| --- | --- |
| `id` | Stable checker identity. |
| `stage` | `static`, `floor`, `boundary`, or `scenario`. |
| `target` | Optional target whose root anchors `cwd`. |
| `command` | Non-empty argv array. Shell strings are rejected. |
| `cwd` | Relative working directory. |
| `timeout` | Positive timeout in seconds. |

Checker stage must match the owning card type. Every checker must be bound to a
card. AG2C executes the argv with `shell=False` and does not install checker tools.

## Generated state

`<project-store>/state/index.sqlite` is rebuildable and contains target revisions, observed
artifacts, ownership, findings, and an integrity digest over all indexed facts.

`<project-store>/ledger.jsonl` is durable local evidence. Each line contains a
sequence number, previous event digest, payload, and event digest. It is never
placed in the governed repository. Task records, receipts, hooks, and worktrees
live in the same project store.
