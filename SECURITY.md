# Security Policy

## Supported versions

Only the latest minor release receives security fixes before DEG 1.0.

## Reporting

Please report suspected vulnerabilities privately to the repository maintainers
before opening a public issue. Include the affected version, configuration, impact,
and a minimal reproduction when possible.

## Trust model

DEG policy is trusted project configuration. Checker argv can execute repository
tools with the current user's permissions. Review policy changes like executable
code and protect the branch that publishes accepted policy.

DEG does not execute commands found in card summaries, Knowledge references, task
goals, source comments, or model output. Configured checkers run with `shell=False`.

The JSONL Ledger detects event deletion, reordering, and mutation through a hash
chain. It does not provide signatures or an external timestamp authority; copy the
head digest to a protected CI artifact or signing system when those guarantees are
required.

## Automatic governance boundary

Enrollment installs a local Git pre-commit guard that blocks commits from the
canonical checkout and unmanaged worktree branches. The guard delegates an
existing pre-commit hook after DEG permits the task commit. Task integration also
requires a clean, unchanged canonical branch, a passing final verification bound
to the current change digest, and a fast-forward merge.

The local guard is not an operating-system access-control boundary. A hostile
process with permission to edit Git configuration or invoke Git with alternate
hooks can bypass it. Protect shared branches with required CI checks before using
DEG as a team security control.

Task goals, model output, source comments, and Skill prose never become executable
commands. Only checker argv already present in the trusted Policy can run.
