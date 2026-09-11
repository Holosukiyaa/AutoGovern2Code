"""AGF 七维信任坐标：task start 的进场申报（最小切口——只申报和记录，不执法）。

坐标系宪法在 AGF 仓（C:\\WorkSpace\\Code\\agf，src/agf/models.py）。本模块的
封闭枚举逐字对齐 AGF，刻意不 import agf 包——指针而非引擎：AGF 修宪
（如洞 B 的 decider 分档、洞 D 的 effect+cognitive）落地后人工同步此处，
同步本身是一次有意识的修宪吸收，不是依赖漂移。

设计依据：docs/dev/AGF-INSPIRATIONS.md（对账三件套：坐标申报/对账/降档棘轮
——本模块是第一件；对账 checker 是后续任务）、docs/dev/AG2K-INSPIRATIONS.md
（信任阶梯 L0-L3，decider 按层级分档）。

推导的保守原则：未申报的维度从 path_specs 触及卡片的 jurisdiction 推导，
多张卡冲突时取更严的档（rank 最大）；卡片 jurisdiction 覆盖不到的维度
（effect/quality/failure/grain）用保守默认值。申报永远优先于推导——申报
是动作进场时的意图表达，推导只是缺省。
"""

from __future__ import annotations

from typing import Any

from .errors import AG2CError

# --- AGF 封闭枚举（逐字对齐 agf/src/agf/models.py，2026-09-11） ---
EFFECTS = ("none", "read", "write", "external", "irreversible")
CONTRACTS = ("none", "partial", "machine")
MEANINGS = ("none", "summary", "projection")
QUALITIES = ("none", "heuristic", "human", "gold")
DECIDERS = ("none", "machine", "confirm", "review")
GRAINS = ("step", "run", "flow", "conversation")
FAILURES = ("fail_closed", "retry", "skip", "escalate")

COORDINATE_ENUMS: dict[str, tuple[str, ...]] = {
    "effect": EFFECTS,
    "contract": CONTRACTS,
    "meaning": MEANINGS,
    "quality": QUALITIES,
    "decider": DECIDERS,
    "grain": GRAINS,
    "failure": FAILURES,
}
COORDINATE_FIELDS = tuple(COORDINATE_ENUMS)

#: 严格度升序：多卡冲突取 rank 最大者。只列卡片 jurisdiction 可推导的维度
#: （grain 的结构粒度（subtree/.../file）与 AGF 的时间粒度（step/.../conversation）
#: 是两把尺子，不映射；effect/quality/failure 不在卡片上）。
STRICTNESS_RANKS: dict[str, dict[str, int]] = {
    "contract": {value: rank for rank, value in enumerate(CONTRACTS)},
    "decider": {value: rank for rank, value in enumerate(DECIDERS)},
    "meaning": {value: rank for rank, value in enumerate(MEANINGS)},
}

#: 卡片 jurisdiction 的 meaning 枚举（none/named）到 AGF（none/summary/
#: projection）的语义近似映射：卡片"有名"≈"给人看懂到摘要级"。
_MEANING_FROM_CARD = {"none": "none", "named": "summary"}

#: 卡片覆盖不到维度的保守默认。effect=write 是事实性默认（AG2C 任务必然写
#: worktree）；grain=run（任务=一次运行）；failure=fail_closed（AG2C 既有
#: 姿态）；quality=none（不虚报质量档）。
CONSERVATIVE_DEFAULTS: dict[str, str] = {
    "effect": "write",
    "contract": "none",
    "meaning": "none",
    "quality": "none",
    "decider": "none",
    "grain": "run",
    "failure": "fail_closed",
}

#: 维度间约束警告的 kind。刻意不加入 checks.ESCALATABLE_KINDS：约束机查刚
#: 上线，先观察误报率，永不硬化成门。
CONSTRAINT_WARNING_KIND = "coordinate-constraint"


def validate_declaration(declaration: dict[str, Any]) -> dict[str, str]:
    """校验申报的七维坐标：未知维度、非字符串、非法枚举值一律拒绝。"""
    if not isinstance(declaration, dict):
        raise AG2CError("coordinates must be an object of dimension=value")
    unknown = set(declaration) - set(COORDINATE_FIELDS)
    if unknown:
        raise AG2CError(
            "unknown coordinate dimensions: " + ", ".join(sorted(unknown))
            + "（合法维度：" + ", ".join(COORDINATE_FIELDS) + "）"
        )
    cleaned: dict[str, str] = {}
    for dim, value in declaration.items():
        text = str(value or "").strip()
        if text not in COORDINATE_ENUMS[dim]:
            raise AG2CError(
                f"coordinate {dim} must be one of {list(COORDINATE_ENUMS[dim])}: {value!r}"
            )
        cleaned[dim] = text
    return cleaned


def _card_coordinate(jurisdiction: dict[str, Any], dim: str) -> str | None:
    """从一张卡的 jurisdiction 推导单个维度；不可映射的维度返回 None。"""
    if dim == "contract":
        value = str(jurisdiction.get("contract") or "none")
        return value if value in CONTRACTS else None
    if dim == "decider":
        value = str(jurisdiction.get("decider") or "none")
        return value if value in DECIDERS else None
    if dim == "meaning":
        return _MEANING_FROM_CARD.get(str(jurisdiction.get("meaning") or "none"))
    return None


def derive_from_cards(jurisdictions: list[dict[str, Any]]) -> dict[str, str]:
    """多张卡冲突取更严的档（严格度 rank 最大者）。"""
    derived: dict[str, str] = {}
    for dim, ranks in STRICTNESS_RANKS.items():
        best: str | None = None
        for jurisdiction in jurisdictions:
            value = _card_coordinate(jurisdiction, dim)
            if value is None:
                continue
            if best is None or ranks[value] > ranks[best]:
                best = value
        if best is not None:
            derived[dim] = best
    return derived


def resolve_coordinates(
    declaration: dict[str, Any] | None,
    jurisdictions: list[dict[str, Any]],
) -> dict[str, Any]:
    """合并申报与推导，返回三桶来源标注 + effective。

    declared 优先于 derived，derived 优先于保守默认；三桶互不相交，
    effective 是三桶的合并——后续对账 checker 按桶追责（申报错了是人/AI
    的意图问题，推导错了是推导规则问题）。
    """
    declared = validate_declaration(declaration or {})
    derived = derive_from_cards(jurisdictions)
    effective: dict[str, str] = {}
    buckets: dict[str, dict[str, str]] = {"declared": {}, "derived": {}, "defaults": {}}
    for dim in COORDINATE_FIELDS:
        if dim in declared:
            buckets["declared"][dim] = declared[dim]
        elif dim in derived:
            buckets["derived"][dim] = derived[dim]
        else:
            buckets["defaults"][dim] = CONSERVATIVE_DEFAULTS[dim]
        effective[dim] = buckets["declared"].get(dim) or buckets["derived"].get(dim) or buckets["defaults"][dim]
    return {
        "effective": effective,
        "declared": buckets["declared"],
        "derived": buckets["derived"],
        "defaults": buckets["defaults"],
    }


def constraint_warnings(task_id: str, effective: dict[str, str]) -> list[dict[str, str]]:
    """维度间约束的第一条机查：quality=human 但 decider 不到人（confirm/review）。

    AGF 假说（AGF-INSPIRATIONS.md 二）：quality=human → decider≥confirm 可机查。
    质量要人拍板而拍板者里没有人的时候，声明自相矛盾——警告不拦，记
    warning-history 追踪（kind 不在 ESCALATABLE_KINDS，永不硬化）。
    """
    warnings: list[dict[str, str]] = []
    if effective.get("quality") == "human" and effective.get("decider") in ("none", "machine"):
        warnings.append(
            {
                "kind": CONSTRAINT_WARNING_KIND,
                "key": f"{task_id}:quality-human-decider",
                "detail": (
                    "quality=human 要求人参与拍板，但 decider="
                    + str(effective.get("decider"))
                    + "（none/machine 没有人）；若质量真由人定，decider 应为 confirm/review"
                ),
            }
        )
    return warnings
