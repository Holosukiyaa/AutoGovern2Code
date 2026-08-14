# Entry Slicing

> Internal contract: ordinary users do not perform entry slicing. The installed
> DEG Skill derives these coordinates from a normal coding request before the
> first write, and `deg task verify` recompiles them from the actual diff.

[中文版本](zh-CN/ENTRY_SLICING.md)

Entry slicing is the method DEG uses to turn a proposed change into a bounded
responsibility, reading, and verification closure. It answers four questions
before implementation begins:

1. What exact repository fact is the change entering through?
2. Who owns that fact?
3. Which declared dependencies or public boundaries must participate?
4. Which checks can prove the resulting change?

An entry slice is not a list of files an agent is allowed to edit. It is a
minimum justified work context plus a validation plan.

## 1. Entry coordinates

DEG accepts deterministic coordinates, ordered from most useful to broadest:

| Coordinate | Syntax | Use |
| --- | --- | --- |
| Existing path | `target-id:path/to/file` | Modify or inspect an existing artifact. |
| Planned path | `target-id:path/to/new-file` | Route a file before it exists. |
| Public contract | `target-id:contract.id@version` | Change or review a producer/consumer handoff. |
| All policy areas | `--all` | Release, baseline, or complete acceptance. |

`--goal` is deliberately absent from this table. A goal is useful descriptive
context, but natural language does not grant ownership and cannot suppress checks.

## 2. Path closure

For each path, DEG evaluates primary Floor scopes:

```text
path
  -> exactly one primary Floor
  -> Knowledge whose narrow scope matches the path
  -> Floor dependencies declared with depends_on
  -> checkers bound to all selected cards
```

The path does not need to exist yet. A planned file can be routed by the scope it
will occupy. This is why new files should be sliced using their intended final
path, not a temporary filename.

Every governed artifact should match exactly one primary Floor:

- zero matches means `unowned`;
- more than one match means `ambiguous`;
- one match means `covered`.

Unowned and ambiguous entries enter conservative routing.

## 3. Contract closure

Public contract changes cannot be proven from one endpoint. A contract binding
therefore expands in the opposite direction from a path:

```text
contract id + exact version
  -> Boundary
  -> declared producer Floors
  -> declared consumer Floors
  -> required Scenario cards
  -> boundary, floor, and scenario checkers
```

Use a contract entry whenever a change affects a public request, response, event,
package, schema, wire format, command interface, or cross-repository artifact.
Include both a path and contract when implementation and public shape change in
the same task.

## 4. Conservative expansion

DEG uses a fail-closed routing rule:

> Uncertainty can only expand reading and verification.

A route becomes conservative when:

- no Floor owns an entry path;
- multiple Floors own it;
- a contract has no exact binding;
- a future policy extension reports stale or conflicting local knowledge.

Conservative expansion selects every Floor for the affected target. It does not
authorize editing every selected Floor. The implementation scope remains the
smallest change justified by the task; only the validation scope expands.

## 5. Slice versus hydrated context

A slice should stay small. DEG returns card identity, summary, selection reasons,
references, and the checker plan. It does not dump every policy body or every
source symbol into the result.

The intended workflow is two-phase:

```text
Phase 1: slice
  identify owners, boundaries, references, and checks

Phase 2: hydrate
  open only the selected references and real source files needed for the task
```

This distinction keeps AI context bounded and makes every loaded document
explainable through a selection reason.

## 6. Practical recipes

### Modify an existing file

```bash
deg slice --path api:src/http/orders.py --goal "Add cancellation reason"
```

### Add a new file

Use its intended path even before creation:

```bash
deg slice --path api:src/http/cancellation.py
```

### Change a public API

```bash
deg slice \
  --path api:src/http/orders.py \
  --contract api:orders.cancel@2.0.0
```

### Change a producer and consumer in separate repositories

```bash
deg slice \
  --path producer:src/package.py \
  --path consumer:src/install.go \
  --contract producer:package.install@1.2.0
```

### Run a release baseline

```bash
deg check --all
```

Only `--all` is eligible to produce `complete` acceptance, and only when every
policy checker runs and passes.

A stage with no checker in the project policy is `not-applicable`. A stage that
does have policy checkers but is outside the current slice is `not-run`.

## 7. Reading a slice

A slice contains:

- `entries`: requested paths and contracts;
- `route.state`: `precise` or `conservative`;
- `fallback_reasons`: why validation expanded;
- `cards`: the selected responsibility closure;
- `check_plan`: trusted checkers selected from those cards;
- `slice_digest`: a stable digest of the full decision.

Each card has explicit `selection_reasons`. Treat unexplained context as a policy
bug rather than silently adding it.

## 8. Policy authoring order

Adopt entry slicing in this order:

1. Declare targets and governed roots.
2. Create Floor scopes until every governed artifact has one owner.
3. Add real Floor checkers.
4. Add Knowledge only where local navigation materially helps.
5. Model public Boundaries and producer/consumer relations.
6. Bind exact contract identities and versions.
7. Add real consumer Scenarios.
8. Use `--all` only after lower stages are meaningful.

Starting with broad Knowledge or hundreds of rules usually produces noise without
ownership. Floors and real checkers establish the useful backbone first.

## 9. Anti-patterns

Do not:

- choose a Floor because its title resembles the task goal;
- use one global `src/**` Floor after the project has independent owners;
- hide an ambiguous path by adding overlapping scopes;
- treat a producer unit test as consumer compatibility evidence;
- expand the code-edit scope because validation expanded;
- bind `latest` instead of an exact public contract version;
- put executable commands in Knowledge text;
- report a static index with no findings as complete product acceptance.

## 10. Review checklist

Before implementation:

- [ ] Every entry uses a target-qualified path or exact contract identity.
- [ ] The route is precise, or every fallback reason is understood.
- [ ] Selected Knowledge is local and current enough to navigate.
- [ ] Public changes include producers, consumers, and scenarios.
- [ ] The check plan contains real project commands.

After implementation:

- [ ] Rebuild the index after the final source change.
- [ ] Recompile the same entry slice.
- [ ] Run the selected checks.
- [ ] Use `--all` for complete acceptance when required.
- [ ] Verify the Ledger hash chain.
