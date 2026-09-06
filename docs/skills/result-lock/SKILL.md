---
name: result-lock
description: >
  Delivery loop for a sparse task: write one checkable finished-state
  portrait (result, not plan), lock it, implement immediately, then
  run a hostile Close — live-simulate every claimed surface (click,
  type, screenshot after each action, real HTTP/CLI) and write an
  evidence chain that quotes this-session tool output. Lazy proof
  (narrative, "tests passed", first-paint screenshot, unread hunt
  PASSes) is UNPROVEN / SHORTCUT-SUSPECT; you may not call the task
  done without Close. Do not ask the user to confirm or to permit
  starting. Applies to any task kind (behavior, API, CLI, data,
  document, UI, bugfix, refactor). Use when the user asks for 结果门,
  先出结果, 锁定结果, 自审, 证据链, "done looks like", proof the work
  is not a shortcut, or runs /result-lock. Use at the start of a task
  whose finished state is underspecified, and after a large
  implementation is claimed complete.
---

# Result lock

One loop: portrait → do → simulate → evidence chain. The portrait is what is true when the work is done, as seen from outside the implementation — not steps, files-to-edit, or architecture.

This is not plan mode.

## Phase

- **Close only** — user asked 自审 / 证据链, or this loop just finished implementing.
- **Open only** — user asked only for the portrait (`先出结果`, `只出结果门`, `/result-lock` with 先别做 / 先别写代码).
- **Open → Do → Close** — anything else that is a task to accomplish. This is the default.

Do not ask which phase. Infer it and go.

## Do not nag

After one portrait, the default is to work. Forbidden: asking whether the portrait is OK, whether to start, whether to continue, whether to test, whether to audit, or presenting a menu whose real question is permission. Pick one concrete default, mark it `INFERRED` if you guessed, and proceed.

Stop only for a real blocker (missing secret, destructive data loss) or when the user explicitly said not to implement yet. A vague request is not a blocker.

Named corrections from the user are applied and work continues. Do not restart a confirmation round. Do not re-emit the full portrait unless the target itself changed.

## What "done" means

Done is what a person outside the code can check: a user, a caller, an operator, a reader.

If a codebase exists, inspect just enough to name the current observable surfaces this task will change, then describe them as they will be when done. If there is no product yet, invent the full portrait; almost everything will be `INFERRED`. Omit surface kinds this task does not produce.

A stack, protocol, or filename appears in the portrait only if it is part of the observable result. Internals never do.

## Density

Specific enough that two people could accept or reject it without seeing code. Vague goals are not a portrait.

**Behavior / bugfix / refactor** — scenario; observable before; observable after (copy, values, ordering, timing); nearby scenarios that must stay as they are.

**Interface (API, RPC, event, caller-facing library)** — invocation; input fields/types/example; success status/body/example; each failure the caller sees; what is not in the contract.

**Command / job / operator action** — exact invocation; stdout/stderr/exit; files or records written; success vs failure as printed or written.

**Artifact (file, document, dataset, report)** — where the user finds it; structure and invariants; a short excerpt as it will read; what is absent.

**Visual surface (page, window, panel, email, print) — only if this task has one** — regions and contents; controls, labels, columns, actions; color, type size, weight, spacing as concrete values; empty/loading/error/denied/success as shown; one screen of sample content.

## Phase Open

1. List `STATED` facts from the user text.
2. Choose the surface kinds this finished work actually has.
3. Infer the rest until every included surface is checkable. Prefer one default over a menu.
4. Write the portrait in the Open shape below. Put inferences in their own section.
5. Set Status to `LOCKED`. Write `.grok/result-lock.md` at the git repo root if git is available.
6. Unless this is Open only, go to Phase Do in the same turn. Do not wait.

## Phase Do

Implement the locked portrait. Do not ask to begin. Do not write a how-to for approval. You may not tell the user the task is done. The only completion is a Phase Close verdict. Enter Close in the same effort; do not ask whether to audit.

## Phase Close

Close is hostile. Its job is to try to **disprove** the delivery. A Close written from memory, from the implementation story, or from unit tests is itself a shortcut.

You may not say the task is complete. The Close verdict is the only completion. If this session's tool trace does not yet contain live-simulation calls for every claimed surface, make those calls **before** writing a single Close heading. Time, tokens, inconvenience, and "it obviously works" are not exemptions.

### Automatic fail

Treat any of these as the Artifact or as a hunt `PASS` and the verdict is `SHORTCUT-SUSPECT` (or `UNPROVEN` if the surface was simply never exercised):

- Restating what you built, "should work", "looks correct", "I verified it"
- Compile / typecheck / unit tests used as a stand-in for live use
- Reading the new source
- One first-paint screenshot, or a screenshot you did not look at
- Hunt rows `PASS` with no inspection clause
- A weaker mechanism that is not a concrete alternate implementation ("a bug", "a mistake")
- An Artifact line with no quoted fragment from this session's tool output
- Simulation listed as "N/A", "unit tests", or empty for a surface the portrait claimed

### Central test

For every acceptance claim, name a **weaker mechanism**: a specific wrong implementation that would still produce the evidence you currently have (hardcoded fixture, copied sibling, happy-path only, swallowed error). Then either:

- kill it with a this-session artifact a weaker implementation could not have produced, or
- mark the claim `UNPROVEN` / `SHORTCUT-SUSPECT`.

No discriminator → not proven. A discriminator you did not run → not proven.

### Collect

1. Acceptance source: the `LOCKED` portrait in `.grok/result-lock.md` if it exists, else `.grok/result-gate.md`. Otherwise the claims from Phase Open this session. Do not re-interpret the original sparse request.
2. `git status` and `git diff` (staged and unstaged), or the files edited this session.
3. Session evidence only: tool traces. Words in the assistant message are not evidence.
4. Shared surfaces that read the same state, data, or component — you will hit them in simulation, not mention them.
5. Live simulation of every claimed finished surface. Report comes after the tool calls, never before.

### Live simulation

Use the product as the outsider in the portrait would. Bring it up if it is not running. Strongest tool this session, in order: browser or computer-use MCP → real HTTP/CLI against the live process → headless screenshot or script. Missing the first tool is a reason to use the next, not to skip.

- **Visual / UI:** open the real URL or window. Click, type, submit, navigate. Screenshot **after each meaningful action** and **read the image**. Hit sibling routes and empty/error/denied from the portrait. First paint alone is not simulation.
- **Interface:** real requests to the running service. Capture status and body for success **and** at least one failure.
- **Command / job:** actually invoke it. Keep stdout/stderr/exit and files it wrote.
- **Artifact:** open the produced file. Quote the excerpt that must exist.

If a surface was not exercised, the claim is `UNPROVEN`. Write what tool was missing. Do not write what you would have seen.

### Evidence chain

For each claim: Mechanism (`path:line`) → Weaker mechanism (concrete wrong implementation) → Discriminator → Artifact (`<tool/command>` + quoted fragment from its output) → `HELD` | `UNPROVEN` | `CONTRADICTED`.

A test counts only if it executed the changed path and asserted the requirement, not the new code's internals — and it still does not replace live simulation of that surface.

### Shortcut hunt

Against this diff. Default is `FAIL` until you inspected. `N/A` only when that smell cannot apply to this change. `PASS` requires a clause naming what you looked at.

1. **Coincidence.** Wrong sibling branches would still produce this output → `FAIL`. Name the untested branch.
2. **Borrowed shape.** Copied nearby pattern; error handling, lifecycle, types, ownership, or invariants differ and were not adjusted → `FAIL`.
3. **Tautological tests.** The test cannot fail unless the implementation's own structure changes → not evidence.
4. **Unrun / paper verification.** No this-session tool output, or the surface was not exercised live (UI not clicked, API not called, command not invoked, artifact not opened) → `FAIL`. First-paint screenshot only → `FAIL` for behavioral claims.
5. **Unexercised siblings.** Other entry points that share the changed state were not hit → those surfaces `UNPROVEN`.
6. **Hardcoded coincidence.** Implementation literals match the current fixture and a different valid input was not tried → `FAIL`.
7. **Assumption as fact.** Behavior claimed about code not read this session and not in the diff → `UNPROVEN`.
8. **Silent success.** Swallowed errors or catch-alls that look fine without the intended path, with no discriminator → `FAIL`.

### Verdict

Exactly one. You may not write `PROVEN` because you are confident.

- **PROVEN** — every claim `HELD`; hunt has no `FAIL` and no bare `PASS`; every claim has a concrete weaker mechanism, a discriminator you ran, and a quoted this-session artifact; every claimed surface has a live-simulation artifact in the tool trace.
- **UNPROVEN** — missing discriminator, quoted artifact, sibling hit, or live simulation. List them.
- **SHORTCUT-SUSPECT** — hunt `FAIL`, a claim `CONTRADICTED`, or any automatic-fail substitute above.

If not `PROVEN` and the gap is in work you just did, fix it and re-run Close, including new simulation. Do not ask whether to fix. If you cannot, stop and report residual risk. `UNPROVEN` / `SHORTCUT-SUSPECT` means the original task is **not done**.

## Open shape

```text
## Result lock
Task: <finished state in one line>
Status: LOCKED

### Done looks like
<2–4 sentences: the finished thing as encountered from outside>

### Surfaces
#### <surface name> [<kind>]
(STATED) or (INFERRED) on each concrete line.
- Encountered as:
- Contents:
- Example:
- Empty / error / denied / success:
- Unchanged nearby:

### Out of result
- <what will not exist when done>

### Inferences
- <each INFERRED detail, one line>
```

## Close shape

```text
## Close
Task: <one line>
Verdict: PROVEN | UNPROVEN | SHORTCUT-SUSPECT

### Criteria
- C1: <claim>

### Change map
- <path>: <what changed> → <C#>

### Evidence chain
C1:
  Mechanism: <path:line>
  Weaker: <concrete wrong implementation that would still look green>
  Discriminator: <observation that was actually run>
  Artifact: <tool/command> → "<quoted fragment from this session>"
  Status: HELD | UNPROVEN | CONTRADICTED

### Simulation
- <surface>: <clicks / requests / invocations — not unit tests, not empty> → <tool artifact>

### Shortcut hunt
- Coincidence: PASS|FAIL|N/A — <what was inspected>
- Borrowed shape: ...
- Tautological tests: ...
- Unrun / paper verification: ...
- Unexercised siblings: ...
- Hardcoded coincidence: ...
- Assumption as fact: ...
- Silent success: ...

### Residual
- <what remains unproven, or none>
```
