# AG2C 自管摩擦清单（可逐条消）

> 地位：自己管自己已经立住。这里是**摩擦**，不是外管那种大洞，也不是要拆棘轮/半套代理。
> 来源：2026-09-13–14 会话实测。每条单独开任务消；不要一次全改。
> 对照：[GOVERNANCE-PACK.md](GOVERNANCE-PACK.md) 才是外管主线。

消掉时保持：三次硬化仍在；代理仍只代机械活；动态预算超标仍不升级。

---

## F1 人定预算过时，第三次锁门

**现象：** 套件秒数、`docs`/`tests` 行数是 policy 里写死的。机器一慢或文档正当变长，第三次同警告就把 verify 锁死。出路是 `govern checker --budget-seconds` 或抬 `budget_lines`。

**为何是摩擦：** 人定价不符就要重新谈，这是棘轮本意。烦在「正当长一点」和「慢机器」也会撞锁，代理按规矩**不**代勾 over-budget。

**以后怎么消：** 人定秒数允许按本机最近实测重锚（仍留痕、仍要 actor/reason）；行数帽对 docs 用「本次只增文档」的窄通道。不要改成动态超标也升级，也不要代理自动勾超预算。

**实测：** `check.suite-tasks` 60s→90s→120s；`floor.docs` 1400→1600。

---

## F2 门外档案稍改就要求全量验收

**现象：** 任务中途 `apply` 加一张知识卡，policy digest 变了，verify 要求 `declare --full-scan`，哪怕 diff 只有一篇 md。

**为何是摩擦：** 防「改判罚规则却只跑一角」有道理。税和风险不成比例的是：加文档卡 ≠ 改 checkers 命令。

**以后怎么消：** 全量仅当 checkers/绑定/always/代理旗标变化；只加/改知识卡摘要或新文档卡走原切片。不要取消 governance-changed 记账。

---

## F3 `tests/` 一间房绑了所有套件

**现象：** `knowledge.tests` 覆盖 `tests/**`，卡上挂着 suite-gui/governance/tasks… 改 `test_config.py` 一条用例，切片把全家测试拖进来。

**为何是摩擦：** 房间划法问题，不是偶发超时。套件文件本已按 `tests/suites.py` 切开，绑定没有跟着切。

**以后怎么消：** 每套件一间子房（或 checker 只绑对应 test 模块 glob），`fast` 仍 always。不要取消 always 的 cheap fast。

---

## F4 不相干切片仍跑桌面启动

**现象：** 只改 `docs/dev/*.md`，start/verify 仍带 `check.knowledge.ag2c-gui`（托盘起来）。

**为何是摩擦：** 场景检查绑得宽。GUI 退役后这条可能自然消失。

**以后怎么消：** 桌面场景只绑 `src/ag2c_gui/**`（或 GUI 退役后删这条）。不要在「只改文档」时靠它当产品过关。

---

## F5 流程绿、产品灯仍 incomplete / not-run

**现象：** finish 成功，evidence 里产品仍 incomplete，scenario not-run。

**为何是摩擦：** 场景没进本刀切片时的老实账。人容易看成「没过关」。

**以后怎么消：** evidence 写清「本刀未跑场景 ≠ 产品失败」；或 docs-only 明示产品不适用。不要为了灯绿就每刀强跑全部场景。

---

## F6 普查 code_version：MCP 与 CLI PYTHONPATH 不一致

**现象：** MCP `ag2c_census --record` 与 `PYTHONPATH=src python -m ag2c govern census` 各记一套版本，随后 verify 报 `census-version-mismatch`。

**为何是摩擦：** 工具链双入口，不是立法错误。

**以后怎么消：** 同一项目普查只认一种运行时（激活的 pythonw -m ag2c）；或 mismatch 时提示用哪条命令重录，而不是先锁门。

---

## F7 抬楼层 `budget_lines` 一次 apply 可能写不上

**现象：** `apply_change(..., card_id=floor.docs, budget_lines=1600)` 有时 ledger 有事件、读回来仍是 1400；补 `include`/`title` 再调用才写上。知识卡 household 一次就能抬。

**为何是摩擦：** 楼层卡和知识卡更新路径不对称。

**以后怎么消：** 楼层抬帽与知识卡同一条命令、同一必填项；失败要报错，禁止「digest 有了、字段没变」。

---

## 不要写进本清单的

- 代理只 settle/点名普查/软帽警告，不代超预算、不代合入 — **半套是本分**。
- 动态预算超标不硬化 — 故意不惩罚增长。
- 调度器 Phase 2 仍影子 — 另一条线，不是本清单的「摩擦债」。
- 外管治理包、sow 原生命令、flatten 写死 `src/ag2c` — 见 GOVERNANCE-PACK.md，比摩擦大。

建议消的顺序：F3 → F2 → F1/F7 → F4（或随 GUI 退役）→ F5 → F6。
