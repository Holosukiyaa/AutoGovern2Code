# Directory households and versioned census

A floor owns a directory for routing. A document explains a rule. Neither proves
that a directory belongs to the current product. A **directory household** is a
knowledge card with a `jurisdiction`: capability, implementation identity,
lifecycle, directory scopes, entrypoints, explicit floor links and its own checks.

The tray graph shows code directories separately from cards. A README cannot
cover sibling source code. Unowned files, overlapping claims, competing current
implementations and old implementations remain visible. Frontend entrypoint and
canvas-engine references are investigation signals, not proof that code is unused.
Generated code checked into Git remains part of the census; ignored caches and
dependencies do not. File totals are evidence, not a target for deletion.

## Register, review, then enforce

Use `ag2c govern household --help` to register or update one directory card. All
changes require an actor and a substantive reason. The command validates a staged
policy before replacing it. Do not edit the external policy directly.

```powershell
ag2c govern household --id knowledge.workbench --title "Product workbench" --summary "The shipped browser entry and interaction shell" --include "src/frontend/**" --floor floor.src --capability frontend --implementation frontend.main --entrypoint src/frontend/src/main.tsx --actor reviewer --reason "Traced the shipped entry, imports and run interactions"
ag2c govern census
ag2c govern census --record --card knowledge.workbench --actor reviewer --reason "Reviewed the implementation, ownership boundaries and known gaps at this revision"
ag2c govern household-gate --mode enforce --actor reviewer --reason "Require directory ownership and reviewed implementation-specific checks"
```

Registration without a checker is allowed so missing evidence can be recorded
honestly; it remains an explicit gap. Bind a real implementation-specific check
with `--command-json` (an argv JSON array) or `--checker` (an existing checker ID).
Commands run without a shell and receive `AG2C_IMPLEMENTATION`. A generic diff
check, a checker bound to another implementation, identical commands relabelled
as different implementations, omitted required checks and skipped implementation
checks cannot satisfy the enforced household gate. A declared binding is still a
reviewer's claim: tests must actually exercise the named implementation. AG2C
does not infer behavioral coverage from an exit code.

Use directory exclusions to split ownership, not overlapping catch-all cards.
An old card uses `--status legacy --replaced-by knowledge.workbench`; retain its
scope and checks while its code exists. A `retired` card must have no remaining
code and must retain its replacement link. Replacement links must stay within
the same capability and cannot form cycles. Separate modules of one implementation
can share its identity; different current identities for one capability are shown
as competing implementations. Updating an old path retains old checks and routes
replacement regression checks as well.

## Freshness is not the refresh button

`govern census` is an observation. Only `--record` records a human/agent review.
Each review includes UTC time, actor, reason, responsibility summary, directory
and declaration digests, file counts, project Git commits and declared versions,
dirty-worktree markers, and latest scoped source commit/date/summary. Reviews
form a per-card history and are bound to the append-only ledger. The tray shows
the latest 12 reviews; the complete history remains in the external store.

Adding, deleting or changing a scoped file, changing the card, replacement links
or bound checks makes the review stale. An unrelated project commit does not
invalidate an unchanged directory: the old survey version and the current
project version remain separately visible. Age in days is informational; no
invented time-to-live silently turns an old survey into a new one. Ordinary
`govern settle` never refreshes a directory census.

Enforcement is explicit per project for backwards compatibility. In observe mode
the graph reports gaps without pretending delivery is blocked. In enforce mode,
the check runner and task finish reject unowned or multiply owned changed code,
invalid household relationships, absent/stale census and missing implementation
checks. A final worktree review must match the exact bytes under test. A whole
project check checks all households; a scoped task checks its selected households.

## Tray acceptance

Search by directory, card ID, responsibility or implementation. Select a node
directly or through the picker; follow labelled floor, scope and replacement
links. Inspect exclusions, full file lists, entrypoints, checker commands, issues,
survey time/version, latest source change and review history. Status filtering
keeps neighboring nodes so a suspicious directory does not lose its owner or
replacement context. Refreshing an unchanged graph preserves the selected node.

Do not mark a cleanup complete until the reviewed current product is identified,
obsolete implementations are either removed with evidence or explicitly retained,
and the actual product tests pass. A tidy graph alone is not product acceptance.
