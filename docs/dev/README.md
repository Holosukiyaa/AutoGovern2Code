# Developer documentation

This directory is the maintainer-facing doc set. If you only want to **use** AG2C in your own project, start with [docs/ADOPTION.md](../ADOPTION.md) instead — everything here describes how AG2C itself is built, governed, and verified.

- [ARCHITECTURE.md](ARCHITECTURE.md) — system architecture and the evidence model (store, ledger, census, receipts).
- [AUTOMATIC_GOVERNANCE.md](AUTOMATIC_GOVERNANCE.md) — the automatic governance contract: MCP for entry, Git hook for delivery, worktree isolation.
- [DIRECTORY-CENSUS.md](DIRECTORY-CENSUS.md) — directory households, coverage tags (未打标 / 整夹一张 / 一文件一张), and the census loop.
- [CI_VERIFICATION.md](CI_VERIFICATION.md) — local evidence, checkers, and how remote CI should relate to the local ledger.

Reading copies of the packaged agent skills no longer live in the repo; the source of truth is `src/ag2c/skills/`, served to MCP clients as instructions and `ag2c://skill/<name>` resources, and installed for other agents with `ag2c skill install`.
