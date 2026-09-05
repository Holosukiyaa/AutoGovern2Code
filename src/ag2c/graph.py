"""File tree and knowledge-card payload for the Hello ImGui tray."""

from __future__ import annotations

from typing import Any, Iterable, Mapping


GRAPH_SCHEMA = "ag2c.governance_graph.v1"
OPEN_TASK_STATES = frozenset({"active", "verified"})
LAZINESS_FLAGS = ("opaque", "abandoned", "unowned", "ambiguous", "stale", "unreviewed", "multiple", "undeclared", "writing")
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
}
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


def _basename(path: str) -> str:
    text = _normalize_path(path)
    if not text or text == ".":
        return "."
    return text.rsplit("/", 1)[-1]


def _primary_flag(flags: Iterable[str]) -> str:
    ordered = [flag for flag in LAZINESS_FLAGS if flag in set(flags)]
    return ordered[0] if ordered else "current"


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
    flag_list = [flag for flag in (*LAZINESS_FLAGS, "exploring") if flag in set(flags)]
    primary = _primary_flag(flag_list) if any(flag in LAZINESS_FLAGS for flag in flag_list) else ("exploring" if "exploring" in flag_list else "current")
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
        "statusLabel": " · ".join(FLAG_LABELS[flag] for flag in flag_list) or FLAG_LABELS["current"],
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
            if not _items(card.get("references")) and "abandoned" not in flags:
                flags.append("abandoned")
        elif kind == "constitution":
            detection = detection if detection != "无检测" else "交付门禁"
        paths = _scope_paths(card)
        nodes[card_id] = _node(
            card_id,
            kind=kind if kind in KIND_LABELS else "knowledge",
            title=_text(card.get("title")) or card_id,
            summary=_text(card.get("summary")),
            flags=flags,
            path="、".join(paths[:4]),
            protocol=protocol,
            detection=detection,
        )

    knowledge_cards = [card for card in cards if _text(card.get("type")) == "knowledge"]
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
            if identity == "exploring":
                flags.append("exploring")
            if identity == "opaque" or {issue["code"] for issue in household.get("issues", [])} & {
                "opaque-claimed",
                "undecomposed-directory",
                "child-unclaimed",
                "grain-overflow",
            }:
                flags.append("opaque")
            if freshness in {"never", "stale"}:
                flags.append("unreviewed" if freshness == "never" else "stale")
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
                extra={"household": household, "jurisdiction": declaration, "freshness": freshness, "coversDirectories": []},
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

    counts = {flag: 0 for flag in (*LAZINESS_FLAGS, "exploring", "current", "nodes", "leaves", "files")}
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
        elif "exploring" in node.get("flags", []):
            counts["exploring"] += 1
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
