"""Extracted by flatten-split."""
from __future__ import annotations
import hashlib
from typing import Any, Iterable, Mapping
from .graph import GRAPH_SCHEMA, KIND_LABELS, LAZINESS_FLAGS, STATUS_TAG_LABELS, _artifact_directories, _basename, _covers, _directory_of, _file_role, _file_span_parent, _floor_directories, _floors_for, _items, _jurisdiction_span, _knowledge_flags, _mapping, _node, _normalize_path, _scope_paths, _text, _worktree_paths, is_code_file_knowledge, is_document_knowledge, is_enrollment_placeholder, knowledge_title, placeholder_claim, status_tag_key

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
