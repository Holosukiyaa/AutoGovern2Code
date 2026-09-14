# Developer documentation

This directory is the maintainer-facing doc set. If you only want to **use** AG2C in your own project, start with [docs/ADOPTION.md](../ADOPTION.md) instead — everything here describes how AG2C itself is built, governed, and verified.

- [ARCHITECTURE.md](ARCHITECTURE.md) — system architecture and the evidence model (store, ledger, census, receipts).
- [AUTOMATIC_GOVERNANCE.md](AUTOMATIC_GOVERNANCE.md) — the automatic governance contract: MCP for entry, Git hook for delivery, worktree isolation.
- [DIRECTORY-CENSUS.md](DIRECTORY-CENSUS.md) — directory households, coverage tags (未打标 / 整夹一张 / 一文件一张), and the census loop.
- [CI_VERIFICATION.md](CI_VERIFICATION.md) — local evidence, checkers, and how remote CI should relate to the local ledger.
- [AI-HUMAN-DIFFERENCES.md](AI-HUMAN-DIFFERENCES.md) — AI ≠ 人类：治理设计再审视（找不同阶段的负面研究总榜、已确认决策与 AI 原生机制）。
- [GOVERNANCE-PACK.md](GOVERNANCE-PACK.md) — **主指导：** 外挂治理包（卡片+checkers+检测脚本）与可选反向开发；GUI 不是主题。
- [SELF-GOVERNANCE-FRICTION.md](SELF-GOVERNANCE-FRICTION.md) — 自管摩擦清单（预算锁、全量税、测试房绑全家等），可逐条消；不是外管大洞。
- [PROXY-GOVERNANCE.md](PROXY-GOVERNANCE.md) — 代理人治理：从 25 分钟的脚本说起（梯子成本不变量、调度器六职责、授权矩阵四档、三层注意力与抽查校准）。
- [GUI-WEBVIEW2.md](GUI-WEBVIEW2.md) — 窗口皮肤：Hello ImGui → WebView2，保留首页/树/检查器/运维布局。
- [GUI-RETIREMENT.md](GUI-RETIREMENT.md) — 次要：ImGui 退役；继任壳见 GUI-WEBVIEW2.md（主线见 GOVERNANCE-PACK.md）。

Reading copies of the packaged agent skills no longer live in the repo; the source of truth is `src/ag2c/skills/`, served to MCP clients as instructions and `ag2c://skill/<name>` resources, and installed for other agents with `ag2c skill install`.
