<!--
provenance: author=holo(研究圆桌), against=48d4eeaf3e4321591080c6bf30089ced83923ca1, at=2026-09-11
讨论确认后逐字整理；与 AI-HUMAN-DIFFERENCES.md 并列，不混入该文。
-->

# AG2K 对 AG2C 的启发：行为准入与认知准入的对照

> 背景：AG2K（AutoGovern2Knowledge）是项目家族中管"知识准入"的兄弟——
> observe → propose → admit 流水线，admission 不暴露给 AI，签名离线发布。
> AG2C 管"行为准入"（代码变更过 verify 门）。本文把 AG2K 的三板斧摆到 AG2C 面前，
> 照出三个不对称，并给出反向攻击与归宿。
>
> 状态：第一轮对照结论（2026-09-11 讨论确认），待逐条转化为设计任务。

## 一、对照总览：同一个东西的两半

AG2C 治行为：代码变更必须过 verify 门（机器校验 + 监管）。
AG2K 治认知：知识必须过 admission 门（observe → propose → admit）。

把两者并排放，照出一个不对称：**代码有门，认知没门**。
AG2C 里知识卡只需 actor+reason 即可写入，写完立刻成为权威知识，
下一个任务的 reuse_menu 直接注入。AG2K 的存在本身就是对这个不对称的指控。

## 二、启发 1：propose/admit 分离 → 知识卡两态

AG2K 最狠的设计：AI 能 observe、能 propose，但 **admit 这个动作根本不暴露给它**。

搬过来：卡应该分两态——AI 写的是 *proposal*，经过 admit 才是 *knowledge*。
未 admit 的卡进 reuse_menu 时打标或降权。

这直接回应负面总榜 4.2（知识卡是持久化注入通道，S 级）：
现状是"AI 写完即真理"，注入通道没有任何一道闸。

## 三、启发 2：离线签名 → 可信基循环的外部锚点

AG2C 的账本、收据、portrait 全在 store 里，而 store 在 AI 的活动半径内——
信任根在爆炸半径里，这是 4.1（可信基循环，S 级）的循环。

AG2K 的答案是**签名离线发布：信任根放圈外**。搬过来就是：
定期把 ledger digest + 知识卡 digest 做一个离线签名的快照，verify 时校验。
AI 在圈内怎么折腾，都伪造不了圈外的锚。

## 四、启发 3：小内核 → 信任核心瘦身

AG2K 是个小工具，准入手核小到一个人能审完。这示范了一条原则：
**信任成本正比于可信基大小**。

AG2C 越来越大，verify / ledger / regulator 这些信任关键路径应该隔离成
最小可审核心，其余全是可替换外围。

## 五、反向攻击：全量 admit 的瓶颈与分拣

不能全量照搬。AG2C 每个任务都可能动卡，张张人工 admit 会把用户变成瓶颈，
违背主线图景"终点是用户，仅限判断"。

所以还是得走分拣：**被 reuse_menu 高频引用、或被 portrait 依赖的卡才上浮
人工 admit；普通卡走机器校验下沉**。事实下沉到机器，判断上浮到用户——
分拣标准本身，就是政策沙盘（正面机制 6.1）的好题目。

## 六、AGF 反投影：decider 洞 B 的复现

这本质上是 AGF 七维里 decider 维度的问题：AG2K 把知识 admission 的 decider
钉死在 human/offline，AG2C 知识卡的 decider 目前是 AI 自己。

反投影测试发现的洞 B（decider 缺 AI 裁决档且单值）在这里又冒出来了——
说明那个洞是真的，不是测试的假阳性。

## 七、后续

- [ ] 知识卡两态（proposal / admitted）的数据模型与 reuse_menu 打标
- [ ] 离线签名快照的仪式设计（可套用 5.1 朝廷模型）
- [ ] 信任关键路径的最小核心清单
- [ ] 卡上浮分拣标准（进政策沙盘）
