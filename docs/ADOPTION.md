# Adoption Guide

Adopt DEG incrementally. The first useful milestone is unique ownership plus real
Floor checks, not a complete architecture encyclopedia.

## 1. Choose a governance root

For one repository, place `.deg` in that repository root. For several sibling
repositories, place `.deg` in a common workspace and give every target a stable id.

## 2. Declare governed roots

Include source and public contract locations that should have an owner. Exclude
generated output, dependencies, caches, and vendored code unless the project truly
owns them.

## 3. Model Floors

Create the smallest set of real ownership domains. Run `deg index build` and
`deg index findings` until every governed artifact has exactly one owner.

## 4. Bind native checks

Replace the starter checker with the project's existing commands. Commands are
argv arrays, for example:

```json
{
  "id": "check.api-tests",
  "stage": "floor",
  "target": "api",
  "command": ["python", "-m", "pytest", "tests/api", "-q"],
  "cwd": ".",
  "timeout": 300
}
```

DEG does not install those tools; the repository or CI environment owns them.

## 5. Add local Knowledge

Knowledge summaries and references should help a contributor navigate one narrow
area. Do not put mandatory rules or executable commands in Knowledge.

## 6. Model public Boundaries

Add a Boundary when data or artifacts cross a component, process, language,
repository, or release-package boundary. Declare producer and consumer relations,
then bind exact contract versions.

## 7. Add scenarios

A Scenario should exercise the real consumer behavior that endpoint-local checks
cannot prove. Bind its checker to the Scenario card and its id to the contract.

## 8. Put DEG in CI

A minimal CI sequence is:

```bash
deg index build
deg index findings
deg check --all
deg ledger verify
```

Persist the ledger only when your evidence-retention policy requires it. For pull
requests, it is often better to upload the ledger and rendered slice as CI
artifacts and append accepted evidence from a single protected branch job.
