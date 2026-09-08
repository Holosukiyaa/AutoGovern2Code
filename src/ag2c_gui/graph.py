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


def build_governance_graph(details: Mapping[str, Any] | None) -> dict[str, Any]:
    """Compile files and knowledge cards the tray lists, with coverage on each file."""

    source = _mapping(details)
    cards = [_mapping(item) for item in _items(source.get("cards"))]
    knowledge_status = {_text(item.get("id")): _mapping(item) for item in _items(source.get("knowledge")) if _text(item.get("id"))}
    findings = [_mapping(item) for item in _items(_mapping(source.get("index")).get("findings"))]
    pending = [_mapping(item) for item in _items(_mapping(source.get("pending")).get("items") or source.get("pending"))]
    if pending and not isinstance(source.get("pending"), Mapping) and not _items(_mapping(source.get("pending")).get("items")):
        pending = [_mapping(item) for item in _items(source.get("pending"))]
    worktrees = [_mapping(item) for item in _items(source.get("worktrees"))]
    checkers = [_text(item.get("id") or item) for item in _items(source.get("checkers"))]

    nodes: dict[str, dict[str, Any]] = {}
    writing = _worktree_paths(worktrees)

    def mark_writing(node_id: str, task: Mapping[str, Any]) -> None:
        node = nodes.get(node_id)
        if node is None:
            return
        flags = list(node["flags"])
        if "writing" not in flags:
            flags.append("writing")
        writers = list(node.get("writers") or [])
        if task["id"] not in writers:
            writers.append(task["id"])
        nodes[node_id] = _node(
            node_id,
            kind=node["kind"],
            title=node["title"],
            summary=node["summary"],
            flags=flags,
            path=node.get("path") or "",
            protocol=node.get("protocol") or "",
            detection=node.get("detection") or "",
            extra={"writers": writers, "writingGoal": task["goal"]},
        )

    for card in cards:
        card_id = _text(card.get("id"))
        kind = _text(card.get("type")) or "knowledge"
        if not card_id:
            continue
        flags: list[str] = []
        protocol = ""
        detection = "、".join(_text(item) for item in _items(card.get("checkers")) if _text(item)) or ("、".join(checkers) if kind == "floor" else "无检测")
        if kind == "boundary":
            protocol = _text(card.get("summary")) or "有对外协议"
        elif kind == "knowledge":
            protocol = "无对外协议"
            flags.extend(_knowledge_flags(knowledge_status.get(card_id, {})))
            if is_enrollment_placeholder(_mapping(card.get("jurisdiction"))):
                flags.append("placeholder")
            elif is_document_knowledge(card) and not is_code_file_knowledge(card):
                flags.append("document")
            if not _items(card.get("references")) and not card.get("jurisdiction") and "abandoned" not in flags:
                flags.append("abandoned")
        elif kind == "constitution":
            detection = detection if detection != "无检测" else "交付门禁"
        paths = _scope_paths(card)
        extra: dict[str, Any] = {}
        if card.get("scopes"):
            extra["scopes"] = _items(card.get("scopes"))
        jurisdiction = _mapping(card.get("jurisdiction"))
        if jurisdiction:
            extra["jurisdiction"] = jurisdiction
            extra["span"] = str(jurisdiction.get("span") or "none")
        nodes[card_id] = _node(
            card_id,
            kind=kind if kind in KIND_LABELS else "knowledge",
            title=knowledge_title(card, fallback=card_id) if kind == "knowledge" else (_text(card.get("title")) or card_id),
            summary=_text(card.get("summary")),
            flags=flags,
            path="、".join(paths[:4]),
            protocol=protocol,
            detection=detection,
            extra=extra or None,
        )

    knowledge_cards = [card for card in cards if _text(card.get("type")) == "knowledge"]
    file_span_households = [card for card in knowledge_cards if _jurisdiction_span(card) == "file"]
    for card in knowledge_cards:
        card_id = _text(card.get("id"))
        if not card_id or card_id not in nodes or not is_document_knowledge(card):
            continue
        parent_id = _file_span_parent(card, file_span_households)
        if parent_id:
            nodes[card_id]["parentCard"] = parent_id
    knowledge_paths = [path for card in knowledge_cards for path in _scope_paths(card)]
    floor_dirs = _floor_directories(cards)
    finding_dirs = _artifact_directories(findings)
    for directory in list(dict.fromkeys(floor_dirs + finding_dirs)):
        if not directory or _covers(knowledge_paths, directory):
            continue
        gap_id = f"gap:{directory}"
        finding_hit = any(_covers([directory], _text(item.get("artifact_id"))) for item in findings)
        summary = f"{directory} 已被目录认领，但没有知识卡说明它是什么。"
        if finding_hit:
            summary = f"{directory} 有未被认领的文件，也没有知识卡。"
        nodes[gap_id] = _node(
            gap_id,
            kind="gap",
            title=directory,
            summary=summary,
            flags=["unowned"],
            path=directory,
            protocol="无对外协议",
            detection="缺知识卡",
        )

    for finding in findings:
        if _text(finding.get("finding_type")) != "scope-uncovered":
            continue
        artifact = _text(finding.get("artifact_id"))
        directory = _directory_of(artifact) or _normalize_path(artifact)
        if not directory:
            continue
        gap_id = f"gap:{directory}"
        if gap_id not in nodes:
            nodes[gap_id] = _node(
                gap_id,
                kind="gap",
                title=directory,
                summary=_text(finding.get("message")) or f"{directory} 没有主人。",
                flags=["unowned"],
                path=directory,
                protocol="无对外协议",
                detection="无主文件",
            )

    if any(_text(item.get("kind")) == "undeclared-product" for item in pending) or any(
        _text(item.get("action")) == "declare-product-checks" for item in pending
    ):
        nodes["gap:product"] = _node(
            "gap:product",
            kind="gap",
            title="产品验收",
            summary="还没有产品验收。任务可以合进仓库，但不能声称产品做完了。",
            flags=["undeclared"],
            path=".",
            protocol="未声明",
            detection="缺产品检查",
        )

    for task in writing:
        matched = False
        for path in task["paths"] or ["."]:
            for node_id, node in list(nodes.items()):
                if node["kind"] == "constitution":
                    continue
                if _covers([node.get("path") or "", node_id], path) or _covers(node.get("path", "").split("、"), path):
                    mark_writing(node_id, task)
                    matched = True
            gap_id = f"gap:{_normalize_path(path).split('/')[0]}" if _normalize_path(path) else ""
            if gap_id and gap_id in nodes:
                mark_writing(gap_id, task)
                matched = True
        if not matched:
            work_id = f"work:{task['id']}"
            nodes[work_id] = _node(
                work_id,
                kind="work",
                title=task["goal"],
                summary="AI 正在写一块图谱上没有知识卡的地方。",
                flags=["writing", "unowned"],
                path="、".join(task["paths"]) or "未声明路径",
                protocol="无",
                detection="施工未挂叶",
                extra={"writers": [task["id"]], "writingGoal": task["goal"]},
            )

    census = _mapping(source.get("census"))
    if census:
        actual_floor_gaps = {
            "gap:" + (_directory_of(_text(item.get("artifact_id"))) or _normalize_path(_text(item.get("artifact_id"))))
            for item in findings
            if item.get("finding_type") == "scope-uncovered"
        }
        for node_id in [key for key in nodes if key.startswith("gap:") and key != "gap:product" and key not in actual_floor_gaps]:
            nodes.pop(node_id)
        for household in _items(census.get("households")):
            card_id = household["id"]
            declaration = _mapping(household.get("jurisdiction"))
            flags = [flag for flag in nodes.get(card_id, {}).get("flags", []) if flag == "writing"]
            freshness = household.get("freshness")
            identity = _text(household.get("identity"))
            placeholder = is_enrollment_placeholder(declaration)
            if placeholder:
                flags.append("placeholder")
            elif identity == "exploring":
                flags.append("exploring")
            if identity == "opaque" or {issue["code"] for issue in household.get("issues", [])} & {
                "opaque-claimed",
                "undecomposed-directory",
                "child-unclaimed",
                "grain-overflow",
            }:
                flags.append("opaque")
            if freshness == "stale":
                flags.append("stale")
            elif freshness == "never" and not placeholder and identity not in {"exploring", ""}:
                flags.append("unreviewed")
            if declaration.get("status") == "legacy" or (declaration.get("status") == "retired" and household.get("code_count")):
                flags.append("abandoned")
            issue_codes = {issue["code"] for issue in household.get("issues", [])}
            if issue_codes & {"implementation-check-missing", "implementation-check-mismatch", "implementation-check-reused"}:
                flags.append("undeclared")
            if issue_codes & {"floor-link-missing", "floor-scope-mismatch", "replacement-missing"}:
                flags.append("unowned")
            if "competing-current-implementations" in issue_codes or len(household.get("canvas_engines", [])) > 1:
                flags.append("multiple")
            paths = [pattern for scope in household.get("scopes", []) for pattern in scope.get("includes", [])]
            nodes[card_id] = _node(
                card_id,
                kind=household["kind"],
                title=household["title"],
                summary=household["summary"],
                flags=flags,
                path="、".join(paths),
                detection="、".join(household.get("checkers", [])) or "未绑定实现检测",
                extra={
                    "household": household,
                    "jurisdiction": declaration,
                    "freshness": freshness,
                    "coversDirectories": [],
                    "span": str(declaration.get("span") or "none"),
                    "scopes": household.get("scopes") or [],
                },
            )
        history_by_target = _mapping(source.get("file_history"))
        for directory in _items(census.get("directories")):
            target = str(directory.get("target") or "app")
            flags = []
            if directory.get("unowned"):
                flags.append("unowned")
            if directory.get("ambiguous"):
                flags.append("ambiguous")
            owners = [str(item) for item in directory.get("owners") or []]
            owner_titles: list[str] = []
            directory_path = _normalize_path(str(directory.get("path") or ".")) or "."
            for owner in owners:
                node = nodes.get(owner)
                if node is None:
                    continue
                title = _text(node.get("title")) or owner
                if title not in owner_titles:
                    owner_titles.append(title)
                covered = list(node.get("coversDirectories") or [])
                if directory_path not in covered:
                    covered.append(directory_path)
                node["coversDirectories"] = covered
            history = _mapping(_mapping(history_by_target.get(target)))
            for relative in [_normalize_path(str(item)) for item in directory.get("files") or []]:
                if not relative:
                    continue
                extra: dict[str, Any] = {
                    "floors": _floors_for(cards, relative),
                    "coveredBy": list(owner_titles),
                    "coverageLabel": "、".join(owner_titles) if owner_titles else "无知识卡覆盖",
                }
                commit = _mapping(history.get(relative))
                if commit:
                    extra["lastCommit"] = commit
                file_id = f"file:{target}:{relative}"
                nodes[file_id] = _node(
                    file_id,
                    kind="file",
                    title=_basename(relative),
                    summary=relative,
                    flags=flags,
                    path=f"{target}:{relative}",
                    extra=extra,
                )

    file_card_by_path: dict[str, Mapping[str, Any]] = {}
    for card in knowledge_cards:
        if not is_document_knowledge(card):
            continue
        paths = _scope_paths(card)
        if len(paths) == 1:
            file_card_by_path[paths[0]] = card
    for node in nodes.values():
        if node.get("kind") != "file":
            continue
        rel = _normalize_path(_text(node.get("summary")))
        file_card = file_card_by_path.get(rel)
        if file_card is None:
            continue
        title = knowledge_title(file_card)
        node["coveredBy"] = [title]
        node["coverageLabel"] = title
        node["parentCard"] = _text(file_card.get("id"))

    knowledge_by_title = {
        _text(node.get("title")) or node["id"]: node
        for node in nodes.values()
        if node.get("kind") == "knowledge"
    }
    for node in nodes.values():
        if node.get("kind") != "file":
            continue
        owners = [knowledge_by_title[title] for title in node.get("coveredBy") or [] if title in knowledge_by_title]
        role, role_label = _file_role(list(node.get("coveredBy") or []), node.get("flags") or [], owners)
        node["role"] = role
        node["roleLabel"] = role_label
        claim_labels: list[str] = []
        extra_flags = list(node.get("flags") or [])
        for owner in owners:
            owner_flags = list(owner.get("flags") or [])
            title = _text(owner.get("title")) or owner["id"]
            if "placeholder" in owner_flags:
                claim_labels.append(placeholder_claim(title))
                if "placeholder" not in extra_flags:
                    extra_flags.append("placeholder")
            else:
                claim_labels.append(title)
            if "exploring" in owner_flags and "exploring" not in extra_flags and "placeholder" not in extra_flags:
                extra_flags.append("exploring")
        node["claimLabels"] = claim_labels
        if extra_flags != list(node.get("flags") or []):
            node["flags"] = extra_flags
            node["statusTag"] = status_tag_key(extra_flags)
            node["statusLabel"] = STATUS_TAG_LABELS[node["statusTag"]]
        replacements: list[str] = []
        for owner in owners:
            for item in _items(_mapping(owner.get("household")).get("replaced_by")):
                text = _text(item)
                if text and text not in replacements:
                    replacements.append(text)
        node["replacedBy"] = replacements
        node.setdefault("coverageLabel", "、".join(node.get("coveredBy") or []) or "无知识卡覆盖")

    for node in nodes.values():
        if node.get("coversDirectories") and node.get("kind") != "file":
            node["coverageLabel"] = "覆盖 " + "、".join(list(node["coversDirectories"])[:8])

    counts = {flag: 0 for flag in (*LAZINESS_FLAGS, "exploring", "placeholder", "document", "current", "nodes", "leaves", "files")}
    for node in nodes.values():
        counts["nodes"] += 1
        if node["kind"] == "file":
            counts["files"] += 1
        if node["kind"] in {"knowledge", "gap", "work"}:
            counts["leaves"] += 1
        if node["lazy"]:
            for flag in node["flags"]:
                if flag in counts:
                    counts[flag] += 1
        elif "placeholder" in node.get("flags", []):
            counts["placeholder"] += 1
        elif "exploring" in node.get("flags", []):
            counts["exploring"] += 1
        elif "document" in node.get("flags", []):
            counts["document"] += 1
        else:
            counts["current"] += 1
    lazy_total = sum(counts[flag] for flag in LAZINESS_FLAGS)
    file_count = counts["files"]
    card_count = sum(1 for node in nodes.values() if node.get("kind") == "knowledge")

    return {
        "schema": GRAPH_SCHEMA,
        "nodes": sorted(nodes.values(), key=lambda item: (item["kind"], item["id"])),
        "counts": counts,
        "lazy": lazy_total > 0,
        "census": {key: census.get(key) for key in ("observed_at", "required", "revisions", "counts")},
        "headline": (
            f"文件树 {file_count} 个文件 · 知识卡 {card_count} 张。开工 {counts['exploring']} · 黑盒 {counts['opaque']} · 废弃未清 {counts['abandoned']}。搜 frontend 可定位前端。无主 {counts['unowned']} · 未普查 {counts['unreviewed']} · 过期 {counts['stale']} · 多实现线索 {counts['multiple']} · 未验收 {counts['undeclared']}"
            if file_count or lazy_total
            else f"{counts['leaves']} 张知识叶，没有可藏的偷懒"
        ),
    }


LINEAGE_SCHEMA = "ag2c.lineage.v1"
LINEAGE_PROJECT_ID = "project:root"
LINEAGE_UNGROUPED_ID = "module:ungrouped"
# G6 antv-dagre-combo analogue: LR ranks, combos wrap card nodes.
LINEAGE_CARD_W = 220.0
LINEAGE_CARD_MIN_W = 220.0
LINEAGE_CARD_MAX_W = 440.0
LINEAGE_CARD_H = 40.0
KNOWLEDGE_TITLE_LIMIT = 20
LINEAGE_CARD_GAP_X = 10.0
LINEAGE_CARD_GAP_Y = 10.0
LINEAGE_MODULE_PAD = 16.0
LINEAGE_MODULE_HEADER = 36.0
LINEAGE_MODULE_MIN_W = 220.0
LINEAGE_MODULE_GAP = 20.0
LINEAGE_RANK_SEP = 72.0
LINEAGE_ORIGIN_X = 64.0
LINEAGE_ORIGIN_Y = 32.0
LINEAGE_PROJECT_W = 200.0
LINEAGE_PROJECT_H = 48.0
LINEAGE_EMPTY_INNER_H = 28.0
LINEAGE_COLLAPSED_W = 200.0
LINEAGE_COLLAPSED_H = 48.0


def _lineage_text_width(value: str) -> float:
    width = 0.0
    for char in str(value or "").replace("\n", " "):
        width += 16.0 if ord(char) > 127 else 8.5
    return width


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


def assign_lineage_ordinals(nodes: Iterable[Mapping[str, Any]]) -> None:
    """Number modules 1, 2, 3; nested cards 1-2 then 1-1-1 so indexes do not collide."""
    records = [item for item in nodes if isinstance(item, dict)]
    by_parent: dict[str, list[dict[str, Any]]] = {}
    for node in records:
        if str(node.get("kind") or "") not in {"module", "knowledge", "group"}:
            continue
        by_parent.setdefault(str(node.get("parent") or ""), []).append(node)

    def sort_key(node: dict[str, Any]) -> tuple[Any, ...]:
        kind = str(node.get("kind") or "")
        if kind == "module":
            return (0, str(node.get("title") or ""), str(node.get("id") or ""))
        if kind == "group":
            return (0, str(node.get("title") or ""), str(node.get("id") or ""))
        return (1, int(node.get("index") or 0), str(node.get("title") or ""), str(node.get("id") or ""))

    def walk(parent_key: str, prefix: list[int]) -> None:
        kids = by_parent.get(parent_key, [])
        kids.sort(key=sort_key)
        for index, kid in enumerate(kids, 1):
            path = prefix + [index]
            kid["ordinal_path"] = path
            kid["ordinal_label"] = "-".join(str(item) for item in path)
            walk(str(kid.get("visual_id") or kid.get("id") or ""), path)

    walk(LINEAGE_PROJECT_ID, [])


def lineage_card_width(node: Mapping[str, Any]) -> float:
    """Elastic card width from numbered title/status, clamped for one combo row."""
    heading = lineage_heading(node)
    extra = str(node.get("replaced_by") or node.get("status") or "")
    if node.get("replaced_by"):
        extra = "已被 " + extra + " 替换"
    inner = max(_lineage_text_width(heading), _lineage_text_width(extra[:24])) + 28.0
    return min(LINEAGE_CARD_MAX_W, max(LINEAGE_CARD_MIN_W, inner))


def lineage_card_height(_node: Mapping[str, Any]) -> float:
    return LINEAGE_CARD_H


def lineage_uid(kind: str, key: str) -> int:
    digest = hashlib.md5(f"{kind}:{key}".encode("utf-8")).digest()
    value = int.from_bytes(digest[:8], "big") & 0x7FFFFFFFFFFFFFFF
    return value or 1


def _card_module_path(card: Mapping[str, Any]) -> str:
    root_files_only = False
    for scope in _items(card.get("scopes")):
        record = _mapping(scope)
        for pattern in _items(record.get("include") or record.get("includes")):
            raw = str(pattern).replace("\\", "/").strip()
            if not raw:
                continue
            if ":" in raw and not raw.startswith(("http:", "https:")):
                raw = raw.partition(":")[2]
            if not raw:
                continue
            if "*" in raw:
                # Directory glob: src/** names the src module.
                return _normalize_path(raw)
            if "/" in raw.lstrip("./"):
                # A nested file pattern names its directory, not the file.
                return _normalize_path(raw).rsplit("/", 1)[0]
            # A root-level file pattern (".gitattributes", "README.md") is not a
            # module path; keep looking for a directory pattern.
            root_files_only = True
    if root_files_only:
        return ""
    return _normalize_path(_text(card.get("title")))


def _status_from_graph(graph_nodes: dict[str, Mapping[str, Any]], card_id: str, fallback: str) -> str:
    record = _mapping(graph_nodes.get(card_id))
    return _text(record.get("statusLabel")) or fallback


def _knowledge_status_tag(card: Mapping[str, Any], graph_nodes: Mapping[str, Mapping[str, Any]], card_id: str) -> str:
    record = _mapping(graph_nodes.get(card_id))
    tag = _text(record.get("statusTag"))
    if tag:
        return tag
    if is_enrollment_placeholder(_mapping(card.get("jurisdiction"))):
        return "placeholder"
    if is_document_knowledge(card) and not is_code_file_knowledge(card):
        return "document"
    flags = _items(record.get("flags"))
    return status_tag_key(str(item) for item in flags)


def _knowledge_status_label(card: Mapping[str, Any], graph_nodes: Mapping[str, Mapping[str, Any]], card_id: str) -> str:
    record = _mapping(graph_nodes.get(card_id))
    label = _text(record.get("statusLabel"))
    if label:
        return label
    return STATUS_TAG_LABELS.get(_knowledge_status_tag(card, graph_nodes, card_id), FLAG_LABELS["current"])


def build_lineage(
    details: Mapping[str, Any] | None,
    *,
    project_name: str = "",
    hide_empty_leftovers: bool = False,
    file_counts: Mapping[str, int] | None = None,
) -> dict[str, Any]:
    """Project → module → knowledge cards. Constitution sits on the project node."""
    source = _mapping(details)
    cards = [_mapping(item) for item in _items(source.get("cards"))]
    relations = [_mapping(item) for item in _items(source.get("relations"))]
    graph_nodes = {
        _text(item.get("id")): _mapping(item)
        for item in _items(_mapping(source.get("graph")).get("nodes"))
        if _text(item.get("id"))
    }
    project_info = _mapping(source.get("project"))
    name = project_name or _text(project_info.get("name")) or "项目"
    constitution = next((item for item in cards if _text(item.get("type") or item.get("kind")) == "constitution"), None)
    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, str]] = []

    def add_node(visual_id: str, payload: dict[str, Any]) -> None:
        payload["visual_id"] = visual_id
        nodes[visual_id] = payload

    add_node(
        LINEAGE_PROJECT_ID,
        {
            "id": _text((constitution or {}).get("id")) or LINEAGE_PROJECT_ID,
            "kind": "project",
            "kindLabel": "项目",
            "title": name,
            "summary": _text((constitution or {}).get("summary")),
            "status": _text((constitution or {}).get("title")) or "宪章",
            "path": "",
            "parent": "",
            "layer": 0,
            "empty": False,
            "replaced_by": "",
        },
    )
    floors = [item for item in cards if _text(item.get("type") or item.get("kind")) == "floor"]
    floor_ids = { _text(item.get("id")) for item in floors if _text(item.get("id")) }
    for floor in floors:
        floor_id = _text(floor.get("id"))
        if not floor_id:
            continue
        path = _card_module_path(floor)
        add_node(
            floor_id,
            {
                "id": floor_id,
                "kind": "module",
                "kindLabel": "模块",
                "title": path or _text(floor.get("title")) or floor_id,
                "summary": _text(floor.get("summary")),
                "status": "",
                "path": path,
                "parent": LINEAGE_PROJECT_ID,
                "layer": 1,
                "empty": True,
                "replaced_by": "",
            },
        )
        edges.append({"source": LINEAGE_PROJECT_ID, "target": floor_id, "type": "module"})
    replacements = {
        _text(item.get("source")): _text(item.get("target"))
        for item in relations
        if _text(item.get("type") or item.get("relation_type")) == "replaced_by"
    }
    replacement_titles = {
        card_id: _text(item.get("title")) or card_id
        for item in cards
        for card_id in [_text(item.get("id"))]
        if card_id
    }
    explained: dict[str, list[str]] = {}
    hung: set[str] = set()
    for item in relations:
        if _text(item.get("type") or item.get("relation_type")) != "explains":
            continue
        knowledge_id = _text(item.get("source"))
        floor_id = _text(item.get("target"))
        if floor_id not in nodes:
            continue
        explained.setdefault(floor_id, []).append(knowledge_id)
        hung.add(knowledge_id)
    knowledge_cards = {
        _text(item.get("id")): item
        for item in cards
        if _text(item.get("type") or item.get("kind")) == "knowledge" and _text(item.get("id"))
    }
    counts = file_counts or {}
    hidden_leftovers: set[str] = set()
    if hide_empty_leftovers:
        hidden_leftovers = {
            card_id
            for card_id, card in knowledge_cards.items()
            if is_empty_leftover_parent(card, file_count=int(counts.get(card_id, 0) or 0))
        }
    for floor_id, card_ids in explained.items():
        unique_ids = [card_id for card_id in dict.fromkeys(card_ids) if card_id not in hidden_leftovers]
        nodes[floor_id]["empty"] = not unique_ids
        nodes[floor_id]["status"] = f"{len(unique_ids)} 张知识卡" if unique_ids else "还没有知识卡"
        for index, knowledge_id in enumerate(unique_ids):
            card = knowledge_cards.get(knowledge_id) or _mapping(graph_nodes.get(knowledge_id))
            visual_id = f"{knowledge_id}@{floor_id}"
            replaced = replacements.get(knowledge_id, "")
            add_node(
                visual_id,
                {
                    "id": knowledge_id,
                    "kind": "knowledge",
                    "kindLabel": "知识卡",
                    "title": knowledge_title(card, fallback=knowledge_id),
                    "summary": _text(card.get("summary")),
                    "status": _knowledge_status_label(card, graph_nodes, knowledge_id),
                    "statusTag": _knowledge_status_tag(card, graph_nodes, knowledge_id),
                    "path": _text(nodes[floor_id].get("path")),
                    "parent": floor_id,
                    "layer": 2,
                    "empty": False,
                    "replaced_by": replacement_titles.get(replaced, replaced),
                    "index": index,
                    **_lineage_span_fields(card),
                },
            )
            edges.append({"source": floor_id, "target": visual_id, "type": "card"})
    file_span_households = [card for card in knowledge_cards.values() if _jurisdiction_span(card) == "file"]
    for node in list(nodes.values()):
        if node.get("kind") != "knowledge":
            continue
        card = knowledge_cards.get(_text(node.get("id")))
        if card is None or not is_document_knowledge(card):
            continue
        parent_id = _file_span_parent(card, file_span_households)
        if not parent_id:
            continue
        parent_visual = f"{parent_id}@{node.get('parent')}"
        if parent_visual not in nodes:
            continue
        node["parent"] = parent_visual
        node["layer"] = 3
        node["path"] = (_scope_paths(card) or [""])[0]
        nodes[parent_visual]["nested"] = True

    # Nest directory rooms under their longest-prefix parent room so the card
    # tree mirrors the real directory hierarchy (core/* rooms under the core
    # room, frontend pages/styles under the frontend room, and so on).
    # Exploring households never act as parents: they are census scaffolding,
    # not a directory grouping the maintainer chose.
    def _room_directory(card: Mapping[str, Any]) -> str:
        paths = [_normalize_path(path) for path in _scope_paths(card)]
        if not paths:
            return ""
        shortest = min(paths, key=len)
        if shortest.endswith("/**"):
            return shortest[:-3]
        return shortest.rstrip("/")

    room_dirs: dict[str, str] = {}
    for card_id, card in knowledge_cards.items():
        if is_document_knowledge(card):
            continue
        directory = _room_directory(card)
        if directory:
            room_dirs[card_id] = directory
    for node in list(nodes.values()):
        if node.get("kind") != "knowledge" or int(node.get("layer") or 0) != 2:
            continue
        card_id = _text(node.get("id"))
        card = knowledge_cards.get(card_id)
        if card is None or is_document_knowledge(card):
            continue
        my_dir = room_dirs.get(card_id) or ""
        if not my_dir:
            continue
        best_id = ""
        best_len = -1
        for other_id, other_dir in room_dirs.items():
            if other_id == card_id or len(other_dir) <= best_len:
                continue
            if not my_dir.startswith(other_dir + "/"):
                continue
            other_card = knowledge_cards.get(other_id) or {}
            if is_enrollment_placeholder(_mapping(other_card.get("jurisdiction"))):
                continue
            best_id = other_id
            best_len = len(other_dir)
        if not best_id:
            continue
        parent_visual = f"{best_id}@{node.get('parent')}"
        if parent_visual not in nodes:
            continue
        node["parent"] = parent_visual
        node["layer"] = 3
        nodes[parent_visual]["nested"] = True

    # Crowded 一文件一张 rooms: fold file cards into one collapsible group node
    # per subdirectory (routers/ under backend), so 60+ flat cards stay readable.
    # Group nodes are presentation-only: kind "group", never auto-expanded.
    for room in file_span_households:
        room_id = _text(room.get("id"))
        room_dir = room_dirs.get(room_id) or ""
        if not room_dir:
            continue
        room_visuals = [vid for vid, node in nodes.items() if node.get("id") == room_id]
        for room_visual in room_visuals:
            children = [
                node
                for node in nodes.values()
                if node.get("parent") == room_visual and node.get("kind") == "knowledge"
            ]
            if len(children) < 6:
                continue
            subdirs: dict[str, list[dict[str, Any]]] = {}
            for child in children:
                rel = _normalize_path(_text(child.get("path")))
                if rel.startswith(room_dir + "/"):
                    rel = rel[len(room_dir) + 1 :]
                if "/" not in rel:
                    continue
                subdirs.setdefault(rel.split("/", 1)[0], []).append(child)
            for subdir, members in sorted(subdirs.items()):
                if len(members) < 2:
                    continue
                group_visual = f"{room_visual}/dir:{subdir}"
                add_node(
                    group_visual,
                    {
                        "id": group_visual,
                        "kind": "group",
                        "kindLabel": "子目录",
                        "title": subdir + "/",
                        "summary": "",
                        "status": f"{len(members)} 张文件卡",
                        "statusTag": "",
                        "path": f"{room_dir}/{subdir}",
                        "parent": room_visual,
                        "layer": 3,
                        "empty": False,
                        "replaced_by": "",
                        "index": 0,
                    },
                )
                for member in members:
                    member["parent"] = group_visual
                    member["layer"] = 4

    orphans = [card_id for card_id in knowledge_cards if card_id not in hung and card_id not in hidden_leftovers]
    if orphans:
        add_node(
            LINEAGE_UNGROUPED_ID,
            {
                "id": LINEAGE_UNGROUPED_ID,
                "kind": "module",
                "kindLabel": "模块",
                "title": "未挂到模块",
                "summary": "这些知识卡还没有认领到项目里的某一块。",
                "status": f"{len(orphans)} 张知识卡",
                "path": "",
                "parent": LINEAGE_PROJECT_ID,
                "layer": 1,
                "empty": False,
                "replaced_by": "",
            },
        )
        edges.append({"source": LINEAGE_PROJECT_ID, "target": LINEAGE_UNGROUPED_ID, "type": "module"})
        for index, knowledge_id in enumerate(orphans):
            card = knowledge_cards[knowledge_id]
            visual_id = f"{knowledge_id}@{LINEAGE_UNGROUPED_ID}"
            replaced = replacements.get(knowledge_id, "")
            add_node(
                visual_id,
                {
                    "id": knowledge_id,
                    "kind": "knowledge",
                    "kindLabel": "知识卡",
                    "title": knowledge_title(card, fallback=knowledge_id),
                    "summary": _text(card.get("summary")),
                    "status": _knowledge_status_label(card, graph_nodes, knowledge_id),
                    "statusTag": _knowledge_status_tag(card, graph_nodes, knowledge_id),
                    "path": "",
                    "parent": LINEAGE_UNGROUPED_ID,
                    "layer": 2,
                    "empty": False,
                    "replaced_by": replacement_titles.get(replaced, replaced),
                    "index": index,
                    **_lineage_span_fields(card),
                },
            )
            edges.append({"source": LINEAGE_UNGROUPED_ID, "target": visual_id, "type": "card"})
    siblings: dict[str, list[dict[str, Any]]] = {}
    for node in nodes.values():
        if node.get("kind") != "knowledge":
            continue
        siblings.setdefault(str(node.get("parent") or ""), []).append(node)
    for kids in siblings.values():
        kids.sort(key=lambda item: (int(item.get("index") or 0), str(item.get("title") or "")))
        for index, child in enumerate(kids):
            child["index"] = index
    assign_lineage_ordinals(nodes.values())
    for _floor_id, node in list(nodes.items()):
        if node.get("kind") == "module" and node.get("empty") and not node.get("status"):
            node["status"] = "还没有知识卡"
        if node.get("kind") in {"module", "knowledge", "group"}:
            kids = [
                {
                    "id": child["id"],
                    "title": child["title"],
                    "visual_id": child["visual_id"],
                    "ordinal_label": child.get("ordinal_label") or "",
                }
                for child in nodes.values()
                if child.get("parent") == node.get("visual_id") and child.get("kind") == "knowledge"
            ]
            if node.get("kind") == "module" or kids:
                node["cards"] = kids
            if kids:
                node["empty"] = False
                if node.get("kind") == "knowledge":
                    node["nested"] = True
                    grouped = sum(
                        1
                        for child in nodes.values()
                        if child.get("kind") == "group"
                        and child.get("parent") == node.get("visual_id")
                        for grand in nodes.values()
                        if grand.get("kind") == "knowledge" and grand.get("parent") == child.get("visual_id")
                    )
                    node["status"] = f"{len(kids) + grouped} 张文件卡"
                child_tags = [
                    _text(child.get("statusTag"))
                    for child in nodes.values()
                    if child.get("parent") == node.get("visual_id") and child.get("kind") == "knowledge"
                ]
                tag = worst_status_tag(child_tags)
                if node.get("kind") == "module":
                    node["statusTag"] = tag
                    if tag and tag != "current":
                        node["status"] = STATUS_TAG_LABELS.get(tag, "") or f"{len(kids)} 张知识卡"
                    else:
                        node["status"] = f"{len(kids)} 张知识卡"
    expanded = {LINEAGE_PROJECT_ID}
    for node in nodes.values():
        if node.get("kind") == "module" and not node.get("empty"):
            expanded.add(str(node.get("visual_id") or node["id"]))
    layout_lineage_view(list(nodes.values()), expanded)
    return {
        "schema": LINEAGE_SCHEMA,
        "nodes": list(nodes.values()),
        "edges": [item for item in edges if item.get("type") == "module"],
    }


def lineage_boxes_overlap(left: Mapping[str, Any], right: Mapping[str, Any], *, gap: float = 1.0) -> bool:
    """True when two laid-out nodes' rectangles collide (with a gap buffer)."""
    ax, ay = float(left.get("x") or 0), float(left.get("y") or 0)
    bx, by = float(right.get("x") or 0), float(right.get("y") or 0)
    aw, ah = float(left.get("width") or 0), float(left.get("height") or 0)
    bw, bh = float(right.get("width") or 0), float(right.get("height") or 0)
    return not (ax + aw + gap <= bx or bx + bw + gap <= ax or ay + ah + gap <= by or by + bh + gap <= ay)


def _hide_lineage_branch(node: dict[str, Any], kids_of: dict[str, list[dict[str, Any]]]) -> None:
    node["hidden"] = True
    node["outward_hull"] = None
    visual_id = str(node.get("visual_id") or node.get("id") or "")
    for child in kids_of.get(visual_id, []):
        _hide_lineage_branch(child, kids_of)


def _pack_lineage_children(
    children: list[dict[str, Any]],
    *,
    x: float,
    y: float,
    width: float,
    expanded: set[str],
    kids_of: dict[str, list[dict[str, Any]]],
) -> float:
    cursor = y
    for child in children:
        visual_id = str(child.get("visual_id") or child.get("id") or "")
        nested = kids_of.get(visual_id, [])
        height = lineage_card_height(child)
        child["hidden"] = False
        child["x"] = x
        child["y"] = cursor
        child["width"] = width
        child["height"] = height
        child["group"] = bool(nested)
        cursor += height + LINEAGE_CARD_GAP_Y
        if not (nested and visual_id in expanded):
            for grand in nested:
                _hide_lineage_branch(grand, kids_of)
    return max(0.0, cursor - y - LINEAGE_CARD_GAP_Y)


def _place_outward_column(
    parent: dict[str, Any],
    kids_of: dict[str, list[dict[str, Any]]],
    expanded: set[str],
    *,
    min_y: float = 0.0,
) -> float:
    """Place parent's children in a column right of it; returns the column bottom.

    Sibling cards in one module share the same column x, so each expanded
    sibling's column must start below the previous sibling's column (min_y);
    otherwise two open combos draw their children on top of each other.
    """
    visual_id = str(parent.get("visual_id") or parent.get("id") or "")
    nested = kids_of.get(visual_id, [])
    parent["outward_hull"] = None
    if not nested:
        return min_y
    if visual_id not in expanded or parent.get("hidden"):
        for child in nested:
            _hide_lineage_branch(child, kids_of)
        return min_y
    column_x = float(parent.get("x") or 0) + float(parent.get("width") or LINEAGE_CARD_W) + LINEAGE_RANK_SEP
    card_w = LINEAGE_CARD_MIN_W
    for child in nested:
        card_w = max(card_w, lineage_card_width(child))
    card_w = min(LINEAGE_CARD_MAX_W, card_w)
    hull_w = max(LINEAGE_MODULE_MIN_W, card_w + LINEAGE_MODULE_PAD * 2)
    inner_w = hull_w - LINEAGE_MODULE_PAD * 2
    inner_x = column_x + LINEAGE_MODULE_PAD
    start_y = max(float(parent.get("y") or 0), min_y)
    inner_y = start_y + LINEAGE_MODULE_HEADER
    cursor = inner_y
    child_floor = 0.0
    for child in nested:
        height = lineage_card_height(child)
        child["hidden"] = False
        child["group"] = bool(kids_of.get(str(child.get("visual_id") or child.get("id") or ""), []))
        child["x"] = inner_x
        child["y"] = cursor
        child["width"] = inner_w
        child["height"] = height
        cursor += height + LINEAGE_CARD_GAP_Y
        child_floor = max(child_floor, _place_outward_column(child, kids_of, expanded, min_y=child_floor))
    inner_h = max(0.0, cursor - inner_y - LINEAGE_CARD_GAP_Y)
    if not inner_h:
        inner_h = LINEAGE_EMPTY_INNER_H
    bottom = start_y + LINEAGE_MODULE_HEADER + inner_h + LINEAGE_MODULE_PAD
    parent["outward_hull"] = {
        "x": column_x,
        "y": start_y,
        "width": hull_w,
        "height": LINEAGE_MODULE_HEADER + inner_h + LINEAGE_MODULE_PAD,
        "title": lineage_heading(parent),
        "status": str(parent.get("status") or f"{len(nested)} 张文件卡"),
        "owner": visual_id,
    }
    return max(bottom, child_floor)


def layout_lineage_view(nodes: list[dict[str, Any]], expanded: set[str]) -> None:
    """Pack an LR dagre-combo view for the current expand set. Mutates x/y/width/height/hidden."""
    assign_lineage_ordinals(nodes)
    project_open = LINEAGE_PROJECT_ID in expanded
    modules = [node for node in nodes if node.get("kind") == "module"]
    modules.sort(key=lambda item: str(item.get("title") or ""))
    kids_of: dict[str, list[dict[str, Any]]] = {}
    for node in nodes:
        if node.get("kind") not in {"knowledge", "group"}:
            continue
        kids_of.setdefault(str(node.get("parent") or ""), []).append(node)
    for kids in kids_of.values():
        kids.sort(key=lambda item: (int(item.get("index") or 0), str(item.get("title") or "")))
    project = next((node for node in nodes if node.get("kind") == "project"), None)
    if project is not None:
        project["x"] = LINEAGE_ORIGIN_X
        project["y"] = LINEAGE_ORIGIN_Y
        project["width"] = LINEAGE_PROJECT_W
        project["height"] = LINEAGE_PROJECT_H
        project["hidden"] = False
        project["group"] = False
    if not project_open:
        for module in modules:
            module["hidden"] = True
            module["x"] = LINEAGE_ORIGIN_X
            module["y"] = LINEAGE_ORIGIN_Y
            module["width"] = LINEAGE_COLLAPSED_W
            module["height"] = LINEAGE_COLLAPSED_H
        for node in nodes:
            if node.get("kind") in {"knowledge", "group"}:
                node["hidden"] = True
        return
    module_x = LINEAGE_ORIGIN_X + LINEAGE_PROJECT_W + LINEAGE_RANK_SEP
    cursor_y = LINEAGE_ORIGIN_Y
    outward_floor = 0.0
    for module in modules:
        visual_id = str(module.get("visual_id") or module.get("id") or "")
        children = kids_of.get(visual_id, [])
        opened = bool(children) and visual_id in expanded
        module["hidden"] = False
        module["group"] = True
        if not opened:
            module["x"] = module_x
            module["y"] = cursor_y
            module["width"] = LINEAGE_COLLAPSED_W
            module["height"] = LINEAGE_COLLAPSED_H
            for child in children:
                child["x"] = module_x
                child["y"] = cursor_y
                child["width"] = LINEAGE_CARD_W
                child["height"] = LINEAGE_CARD_H
                _hide_lineage_branch(child, kids_of)
            cursor_y += LINEAGE_COLLAPSED_H + LINEAGE_MODULE_GAP
            continue
        card_w = LINEAGE_CARD_MIN_W
        for child in children:
            card_w = max(card_w, lineage_card_width(child))
        card_w = min(LINEAGE_CARD_MAX_W, card_w)
        width = max(LINEAGE_MODULE_MIN_W, card_w + LINEAGE_MODULE_PAD * 2)
        inner_x = module_x + LINEAGE_MODULE_PAD
        inner_w = width - LINEAGE_MODULE_PAD * 2
        inner_y = cursor_y + LINEAGE_MODULE_HEADER
        inner_h = _pack_lineage_children(
            children,
            x=inner_x,
            y=inner_y,
            width=inner_w,
            expanded=expanded,
            kids_of=kids_of,
        )
        if not inner_h:
            inner_h = LINEAGE_EMPTY_INNER_H
        height = LINEAGE_MODULE_HEADER + inner_h + LINEAGE_MODULE_PAD
        module["x"] = module_x
        module["y"] = cursor_y
        module["width"] = width
        module["height"] = height
        if visual_id in expanded:
            for child in children:
                outward_floor = max(
                    outward_floor,
                    _place_outward_column(child, kids_of, expanded, min_y=outward_floor),
                )
        cursor_y += height + LINEAGE_MODULE_GAP
    total_h = max(cursor_y - LINEAGE_MODULE_GAP - LINEAGE_ORIGIN_Y, LINEAGE_PROJECT_H)
    if project is not None:
        project["x"] = LINEAGE_ORIGIN_X
        project["y"] = LINEAGE_ORIGIN_Y + max(0.0, (total_h - LINEAGE_PROJECT_H) / 2.0)


def lineage_visible_boxes(nodes: list[dict[str, Any]], expanded: set[str]) -> list[dict[str, Any]]:
    """Visible hulls/nodes for overlap checks. Cards inside their own combo are omitted vs that combo."""
    layout_lineage_view(nodes, expanded)
    boxes = [node for node in nodes if not node.get("hidden")]
    return boxes


def lineage_step_overlaps(nodes: list[dict[str, Any]], expanded: set[str], *, gap: float = 8.0) -> list[tuple[str, str]]:
    """Pairs of visible items that collide, ignoring a card vs its parent combo hull."""
    boxes = lineage_visible_boxes(nodes, expanded)
    by_visual = {
        str(item.get("visual_id") or item.get("id") or ""): item
        for item in nodes
        if str(item.get("visual_id") or item.get("id") or "")
    }

    def ancestor_ids(node: Mapping[str, Any]) -> set[str]:
        found: set[str] = set()
        current = str(node.get("parent") or "")
        while current and current not in found:
            found.add(current)
            parent = by_visual.get(current)
            current = str((parent or {}).get("parent") or "")
        return found

    hits: list[tuple[str, str]] = []
    for index, left in enumerate(boxes):
        for right in boxes[index + 1 :]:
            left_id = str(left.get("visual_id") or left.get("id") or "")
            right_id = str(right.get("visual_id") or right.get("id") or "")
            if left_id in ancestor_ids(right) or right_id in ancestor_ids(left):
                continue
            if lineage_boxes_overlap(left, right, gap=gap):
                hits.append(
                    (
                        str(left.get("visual_id") or left.get("id")),
                        str(right.get("visual_id") or right.get("id")),
                    )
                )
    return hits


def lineage_related_ids(lineage: Mapping[str, Any] | None, node_id: str) -> list[str]:
    """Visual ids for a card or module: itself, copies under other modules, and parents."""
    if not node_id:
        return []
    related: list[str] = []
    seen: set[str] = set()
    for raw in _items(_mapping(lineage).get("nodes")):
        record = _mapping(raw)
        visual_id = _text(record.get("visual_id") or record.get("id"))
        matches = node_id in {visual_id, _text(record.get("id"))}
        if not matches:
            continue
        if visual_id not in seen:
            seen.add(visual_id)
            related.append(visual_id)
        parent = _text(record.get("parent"))
        while parent and parent not in seen:
            seen.add(parent)
            related.append(parent)
            parent_node = next(
                (
                    _mapping(item)
                    for item in _items(_mapping(lineage).get("nodes"))
                    if _text(item.get("visual_id") or item.get("id")) == parent
                ),
                {},
            )
            parent = _text(parent_node.get("parent"))
    return related
