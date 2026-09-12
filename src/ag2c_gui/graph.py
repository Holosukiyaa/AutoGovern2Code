"""File tree and knowledge-card payload for the Hello ImGui tray."""

from __future__ import annotations

import hashlib
from typing import Any, Iterable, Mapping


GRAPH_SCHEMA = "ag2c.governance_graph.v1"
OPEN_TASK_STATES = frozenset({"active", "verified"})
LAZINESS_FLAGS = ("opaque", "abandoned", "unowned", "ambiguous", "stale", "unreviewed", "multiple", "undeclared", "writing")
STATUS_TAG_ORDER = (
    "writing",
    "opaque",
    "placeholder",
    "exploring",
    "unreviewed",
    "stale",
    "abandoned",
    "document",
    "current",
)
STATUS_TAG_LABELS = {
    "writing": "AI正在写",
    "opaque": "黑盒",
    "placeholder": "占位",
    "exploring": "开工",
    "unreviewed": "未普查",
    "stale": "过期",
    "abandoned": "废弃未清",
    "document": "文档",
    "current": "在册",
}
FLAG_LABELS = {
    "abandoned": "废弃未清",
    "unowned": "无主",
    "stale": "过期",
    "undeclared": "未验收",
    "writing": "AI正在写",
    "current": "在册",
    "ambiguous": "重复认领",
    "unreviewed": "未普查",
    "multiple": "多实现待核查",
    "exploring": "开工",
    "opaque": "黑盒",
    "placeholder": "占位",
    "document": "文档",
}
STATUS_FLAGS = (*LAZINESS_FLAGS, "exploring", "placeholder", "document")
KIND_LABELS = {
    "constitution": "宪章",
    "floor": "目录认领",
    "knowledge": "知识卡",
    "boundary": "协议面",
    "gap": "空洞",
    "work": "施工",
    "file": "文件",
}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _items(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _normalize_path(value: str) -> str:
    text = value.replace("\\", "/").strip()
    if ":" in text and not text.startswith(("http:", "https:")):
        _target, _, remainder = text.partition(":")
        text = remainder or text
    text = text.lstrip("./")
    if text.endswith("/**"):
        text = text[:-3]
    text = text.rstrip("*").rstrip("/")
    return text


def _directory_of(path: str) -> str:
    normalized = _normalize_path(path)
    if not normalized or normalized in {".", "**"}:
        return ""
    if "/" not in normalized:
        return normalized if "." not in normalized else ""
    return normalized.rsplit("/", 1)[0]


def _scope_paths(card: Mapping[str, Any]) -> list[str]:
    paths: list[str] = []
    for scope in _items(card.get("scopes")):
        record = _mapping(scope)
        for pattern in _items(record.get("include") or record.get("includes")):
            path = _normalize_path(str(pattern))
            if path:
                paths.append(path)
    for reference in _items(card.get("references")):
        path = _normalize_path(str(reference))
        if path:
            paths.append(path)
    return list(dict.fromkeys(paths))


def _covers(paths: Iterable[str], candidate: str) -> bool:
    needle = _normalize_path(candidate)
    if not needle:
        return False
    for path in paths:
        if path == needle or needle.startswith(path + "/") or path.startswith(needle + "/"):
            return True
    return False


def _path_under(directory: str, candidate: str) -> bool:
    root = _normalize_path(directory)
    needle = _normalize_path(candidate)
    if not root or not needle:
        return False
    return needle == root or needle.startswith(root + "/")


def _scope_excludes(card: Mapping[str, Any]) -> list[str]:
    paths: list[str] = []
    for scope in _items(card.get("scopes")):
        record = _mapping(scope)
        for pattern in _items(record.get("exclude") or record.get("excludes")):
            path = _normalize_path(str(pattern))
            if path:
                paths.append(path)
    return list(dict.fromkeys(paths))


def _jurisdiction_span(card: Mapping[str, Any]) -> str:
    record = _mapping(card.get("jurisdiction"))
    value = _text(record.get("span") or "none")
    if value in {"file", "一文件一张"}:
        return "file"
    if value in {"folder", "整夹一张"}:
        return "folder"
    return "none"


COVERAGE_LABELS = {"none": "未打标", "folder": "整夹一张", "file": "一文件一张"}


def _lineage_span_fields(card: Mapping[str, Any]) -> dict[str, str]:
    if not card.get("jurisdiction"):
        return {"span": "", "spanLabel": ""}
    span = _jurisdiction_span(card)
    return {"span": span, "spanLabel": COVERAGE_LABELS.get(span, "未打标")}


def _household_owns_path(household: Mapping[str, Any], candidate: str) -> bool:
    includes = _scope_paths(household)
    if not any(_path_under(path, candidate) for path in includes):
        return False
    return not any(_path_under(path, candidate) for path in _scope_excludes(household))


def _file_span_parent(card: Mapping[str, Any], households: list[Mapping[str, Any]]) -> str:
    paths = _scope_paths(card)
    if len(paths) != 1:
        return ""
    needle = paths[0]
    best_id = ""
    best_len = -1
    for household in households:
        if _jurisdiction_span(household) != "file":
            continue
        if not _household_owns_path(household, needle):
            continue
        length = max((len(_normalize_path(path)) for path in _scope_paths(household)), default=0)
        if length > best_len:
            best_len = length
            best_id = _text(household.get("id"))
    return best_id


def _basename(path: str) -> str:
    text = _normalize_path(path)
    if not text or text == ".":
        return "."
    return text.rsplit("/", 1)[-1]


def _primary_flag(flags: Iterable[str]) -> str:
    ordered = [flag for flag in LAZINESS_FLAGS if flag in set(flags)]
    return ordered[0] if ordered else "current"


def status_tag_key(flags: Iterable[str]) -> str:
    flag_set = set(flags)
    for key in STATUS_TAG_ORDER:
        if key in flag_set:
            return key
    return "current"


def status_tag_label(flags: Iterable[str]) -> str:
    return STATUS_TAG_LABELS[status_tag_key(flags)]


def worst_status_tag(tags: Iterable[str]) -> str:
    rank = {key: index for index, key in enumerate(STATUS_TAG_ORDER)}
    best = ""
    best_rank = len(STATUS_TAG_ORDER)
    for tag in tags:
        key = str(tag or "")
        if key not in rank:
            continue
        if rank[key] < best_rank:
            best = key
            best_rank = rank[key]
    return best


def is_enrollment_placeholder(declaration: Mapping[str, Any] | None) -> bool:
    record = _mapping(declaration)
    if not record:
        return False
    if _text(record.get("meaning") or "none") != "none":
        return False
    if _text(record.get("status") or "current") not in {"", "current"}:
        return False
    return _text(record.get("implementation")).endswith(".exploring")


def is_document_knowledge(card: Mapping[str, Any]) -> bool:
    if _text(card.get("type") or card.get("kind")) != "knowledge":
        return False
    if card.get("jurisdiction"):
        return False
    return bool(_items(card.get("references")))


def is_empty_leftover_parent(card: Mapping[str, Any], *, file_count: int) -> bool:
    """Placeholder parent whose children were carved out and which owns no files itself.

    Such cards only hold the exclusion guard (src/** minus src/ag2c/** ...); they
    carry no design content, so the lineage graph can skip them by default. Both
    current placeholders and their legacy/retired equivalents qualify.
    """
    if file_count > 0:
        return False
    jurisdiction = _mapping(card.get("jurisdiction"))
    if not jurisdiction:
        return False
    if _text(jurisdiction.get("meaning") or "none") != "none":
        return False
    if not _text(jurisdiction.get("implementation")).endswith(".exploring"):
        return False
    if _text(jurisdiction.get("status") or "current") not in {"", "current", "legacy", "retired"}:
        return False
    return any(
        _items(_mapping(scope).get("exclude"))
        for scope in _items(card.get("scopes"))
    )


def _path_suffix(path: str) -> str:
    name = _normalize_path(path).rsplit("/", 1)[-1]
    if "." not in name or name.startswith("."):
        return ""
    return "." + name.rsplit(".", 1)[-1].lower()


def is_code_file_knowledge(card: Mapping[str, Any]) -> bool:
    """True for a 一文件一张 code card (cli.py), not a prose document (README.md)."""
    if not is_document_knowledge(card):
        return False
    paths = _scope_paths(card) or [_normalize_path(str(item)) for item in _items(card.get("references"))]
    if len(paths) != 1:
        return False
    from ag2c.households import CODE_SUFFIXES

    return _path_suffix(paths[0]) in CODE_SUFFIXES


def _index_card_entry(card: Mapping[str, Any]) -> dict[str, Any]:
    paths = _scope_paths(card)
    return {
        "id": _text(card.get("id")),
        "title": knowledge_title(card),
        "summary": _text(card.get("summary")),
        "path": paths[0] if len(paths) == 1 else "",
        "include": paths,
        "exclude": _scope_excludes(card),
        "span": _jurisdiction_span(card) if card.get("jurisdiction") else "none",
    }


def knowledge_lineage_index(
    cards: Iterable[Mapping[str, Any]],
    *,
    selected_ids: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Room → file-card tree. This is the coding index agents read before writing."""
    knowledge = [
        _mapping(item)
        for item in cards
        if _text(_mapping(item).get("type") or _mapping(item).get("kind")) == "knowledge"
    ]
    households = [item for item in knowledge if item.get("jurisdiction")]
    file_span = [item for item in households if _jurisdiction_span(item) == "file"]
    children: dict[str, list[dict[str, Any]]] = {}
    documents: list[dict[str, Any]] = []
    for card in knowledge:
        if not is_document_knowledge(card):
            continue
        parent_id = _file_span_parent(card, file_span)
        if parent_id:
            children.setdefault(parent_id, []).append(_mapping(card))
        else:
            documents.append(_mapping(card))
    selected = {str(item) for item in selected_ids} if selected_ids is not None else None

    def household_wanted(household: Mapping[str, Any]) -> bool:
        hid = _text(household.get("id"))
        if selected is None:
            return True
        if hid in selected:
            return True
        return any(_text(child.get("id")) in selected for child in children.get(hid, []))

    rooms: list[dict[str, Any]] = []
    for household in households:
        if not household_wanted(household):
            continue
        entry = _index_card_entry(household)
        entry["files"] = [_index_card_entry(child) for child in children.get(_text(household.get("id")), [])]
        rooms.append(entry)
    docs = [
        _index_card_entry(card)
        for card in documents
        if selected is None or _text(card.get("id")) in selected
    ]
    return {"rooms": rooms, "documents": docs}


def placeholder_claim(title: str) -> str:
    name = _text(title)
    suffix = " exploring household"
    if name.endswith(suffix):
        name = name[: -len(suffix)].strip()
    return f"占位 · {name}" if name else "占位"


def _file_role(covered_by: list[str], flags: Iterable[str], owner_records: list[Mapping[str, Any]]) -> tuple[str, str]:
    flag_set = set(flags)
    statuses = [_text(_mapping(item.get("jurisdiction")).get("status")) for item in owner_records]
    if "unowned" in flag_set or not covered_by:
        return "unowned", "没有知识卡管理"
    if "ambiguous" in flag_set or len(covered_by) > 1:
        return "ambiguous", "多张知识卡同时认领，归属不清"
    if any(status in {"legacy", "retired"} for status in statuses):
        return "leftover", "旧实现或已退役，可能是换方向后留下的"
    identities = [_text(_mapping(item.get("household")).get("identity")) for item in owner_records]
    meanings = [_text(_mapping(item.get("jurisdiction")).get("meaning") or _mapping(_mapping(item.get("household")).get("jurisdiction")).get("meaning")) for item in owner_records]
    if "opaque" in flag_set or any(identity == "opaque" for identity in identities):
        return "opaque", "已挂卡但未说清，是黑盒"
    if "exploring" in flag_set or any(identity == "exploring" or meaning == "none" for identity, meaning in zip(identities, meanings)):
        return "exploring", "正在开工，尚未说清"
    return "current", "当前知识卡管理"


def _floors_for(cards: list[Mapping[str, Any]], relative: str) -> list[str]:
    titles: list[str] = []
    for card in cards:
        if _text(card.get("type")) != "floor":
            continue
        if _covers(_scope_paths(card), relative):
            title = _text(card.get("title")) or _text(card.get("id"))
            if title and title not in titles:
                titles.append(title)
    return titles


def _node(
    node_id: str,
    *,
    kind: str,
    title: str,
    summary: str,
    flags: Iterable[str],
    path: str = "",
    protocol: str = "",
    detection: str = "",
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    flag_list = [flag for flag in STATUS_FLAGS if flag in set(flags)]
    tag = status_tag_key(flag_list)
    primary = tag if tag != "document" else "current"
    if primary == "placeholder":
        primary = "placeholder"
    elif any(flag in LAZINESS_FLAGS for flag in flag_list):
        primary = _primary_flag(flag_list)
    elif "exploring" in flag_list:
        primary = "exploring"
    payload = {
        "id": node_id,
        "kind": kind,
        "kindLabel": KIND_LABELS.get(kind, kind),
        "title": title,
        "summary": summary,
        "path": path,
        "protocol": protocol,
        "detection": detection,
        "flags": flag_list,
        "primary": primary,
        "statusTag": tag,
        "statusLabel": STATUS_TAG_LABELS[tag],
        "lazy": any(flag in LAZINESS_FLAGS for flag in flag_list),
    }
    if extra:
        payload.update(dict(extra))
    return payload


def _knowledge_flags(record: Mapping[str, Any]) -> list[str]:
    flags: list[str] = []
    status = _text(record.get("status"))
    source = _text(record.get("source_status"))
    assertion = _text(record.get("assertion_status"))
    reasons = [str(item) for item in _items(record.get("reasons"))]
    if status in {"stale", "conflict"} or source == "stale" or assertion in {"stale", "conflict"}:
        flags.append("stale")
    if status == "missing" or source == "missing" or any("missing" in reason for reason in reasons):
        flags.append("abandoned")
    if any(reason in {"reference-missing", "no-references"} or reason.startswith("assertion-missing:") for reason in reasons):
        if "abandoned" not in flags:
            flags.append("abandoned")
    return flags


def _floor_directories(cards: list[Mapping[str, Any]]) -> list[str]:
    directories: list[str] = []
    for card in cards:
        if _text(card.get("type")) != "floor":
            continue
        for path in _scope_paths(card):
            directory = path if "/" not in path and "." not in path else _directory_of(path) or path
            if directory and directory not in directories:
                directories.append(directory)
    return directories


def _artifact_directories(findings: list[Mapping[str, Any]]) -> list[str]:
    directories: list[str] = []
    for finding in findings:
        artifact = _text(finding.get("artifact_id") or finding.get("message"))
        directory = _directory_of(artifact) or _normalize_path(artifact)
        if directory and directory not in directories:
            directories.append(directory)
    return directories


def _worktree_paths(worktrees: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    active: list[dict[str, Any]] = []
    for task in worktrees:
        record = _mapping(task)
        state = _text(record.get("state"))
        lifecycle = _text(_mapping(record.get("worktree")).get("lifecycle"))
        if state not in OPEN_TASK_STATES and lifecycle not in {"in-progress", "verified-unmerged"}:
            continue
        paths = [_normalize_path(str(item)) for item in _items(record.get("paths"))]
        entry = _mapping(record.get("entry"))
        paths.extend(_normalize_path(str(item)) for item in _items(entry.get("paths")))
        paths = [path.removeprefix("app:") for path in paths if path]
        active.append(
            {
                "id": _text(record.get("id")) or f"work-{len(active)+1}",
                "goal": _text(record.get("goal")) or "未命名施工",
                "paths": list(dict.fromkeys(path for path in paths if path)),
            }
        )
    return active


KNOWLEDGE_TITLE_LIMIT = 20
def title_is_abstract(card: Mapping[str, Any]) -> bool:
    """File/document knowledge cards: the title is the 摘要. Households keep room names."""
    kind = _text(card.get("type") or card.get("kind"))
    if kind != "knowledge":
        return False
    return not bool(card.get("jurisdiction"))


def clip_knowledge_title(value: Any) -> str:
    return _text(value)[:KNOWLEDGE_TITLE_LIMIT]


def knowledge_title(card: Mapping[str, Any], *, fallback: str = "") -> str:
    title = _text(card.get("title")) or fallback or _text(card.get("id"))
    if title_is_abstract(card):
        return clip_knowledge_title(title)
    return title


def lineage_ordinal(node: Mapping[str, Any]) -> int:
    path = lineage_ordinal_path(node)
    return path[-1] if path else 0


def lineage_ordinal_path(node: Mapping[str, Any]) -> list[int]:
    raw = node.get("ordinal_path")
    if isinstance(raw, list) and raw:
        try:
            return [int(item) for item in raw]
        except (TypeError, ValueError):
            pass
    label = _text(node.get("ordinal_label"))
    if label:
        try:
            return [int(item) for item in label.split("-") if item]
        except (TypeError, ValueError):
            pass
    raw_index = node.get("index")
    try:
        return [int(raw_index) + 1]
    except (TypeError, ValueError):
        return []


def lineage_ordinal_label(node: Mapping[str, Any]) -> str:
    return "-".join(str(item) for item in lineage_ordinal_path(node))


def lineage_heading(node: Mapping[str, Any], *, title: str = "") -> str:
    name = title or str(node.get("title") or "")
    label = lineage_ordinal_label(node)
    if label and name:
        return f"{label}. {name}"
    return label or name

from .graph_build import build_governance_graph
