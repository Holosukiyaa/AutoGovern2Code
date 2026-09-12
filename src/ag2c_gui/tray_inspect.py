"""Extracted by flatten-split."""
from __future__ import annotations
from typing import Any
from .tray_host import SPAN_LABELS, _card_path_prefixes, _card_span, _clean_scope_path, _open_worktrees, _rel_under_card, _task_line, ancestor_prefixes, card_problem_status, cards_for_owners, claim_label, claim_owners, file_relpath, files_for_card, first_flag_label, is_directory_household, mcp_health_snapshot, node_matches, peer_rels, row_key, string_list, text

def project_gate_rows(
    project: dict[str, Any] | None,
    details: dict[str, Any] | None = None,
    *,
    mcp: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Always-on operator strip: MCP entry, observed records, construction."""
    if not project:
        return []
    managed = project.get("delivery_enforced")
    health = mcp if mcp is not None else mcp_health_snapshot(
        handshake=False,
        cwd=text(project, "root") or None,
        managed=None if managed is None else bool(managed),
    )
    if managed is False and health.get("ok"):
        health = {**health, "ok": False, "status": "broken", "label": "MCP 异常", "error": "Git hook is off"}
    entry_value = str(health.get("label") or "MCP 异常")
    entry_warn = not bool(health.get("ok"))
    completed = int(project.get("completed_tasks") or 0)
    last_line = _task_line(project.get("last_task") if isinstance(project.get("last_task"), dict) else None)
    if completed:
        records_value = f"{completed} 次入库"
        if last_line:
            records_value += " · " + last_line
    else:
        records_value = "尚未观察"
    open_rows = _open_worktrees(details)
    flags: list[str] = []
    for row in open_rows:
        life = str((row.get("worktree") or {}).get("lifecycle") or "")
        state = str(row.get("state") or "")
        if life == "diverged":
            flags.append("已分叉")
        elif life == "missing":
            flags.append("副本丢失")
        elif state == "verified" or life in {"verified-unmerged", "verified-stale"}:
            flags.append("改完了没合并")
    unique = list(dict.fromkeys(flags))
    if unique:
        construction_value = f"{len(unique)} 个异常 · " + "、".join(unique)
        construction_warn = True
    elif open_rows:
        construction_value = f"{len(open_rows)} 个进行中"
        construction_warn = False
    elif int(project.get("open_tasks") or 0) > 0:
        construction_value = f"{int(project['open_tasks'])} 个进行中"
        construction_warn = False
    else:
        construction_value = "没有进行中的施工"
        construction_warn = False
    return [
        {"id": "gate", "label": "AI 入口", "value": entry_value, "warn": entry_warn},
        {"id": "records", "label": "实际记录", "value": records_value, "warn": False},
        {"id": "worktrees", "label": "施工", "value": construction_value, "warn": construction_warn},
    ]

def inspect_fields(node: dict[str, Any]) -> dict[str, Any]:
    who = text(node, "coverageLabel") or "、".join(string_list(node, "coveredBy"))
    floors = "、".join(string_list(node, "floors")) or text(node, "floorLabel")
    when = text(node, "lastCommit") or text(node, "changedAt")
    role = text(node, "roleLabel") or first_flag_label(node)
    title = text(node, "title") or text(node, "path") or "点文件树或知识卡"
    flags = node.get("flags") if isinstance(node.get("flags"), list) else []
    placeholder = text(node, "statusTag") == "placeholder" or "placeholder" in {str(item) for item in flags}
    return {
        "mode": text(node, "kind") or "folder",
        "title": title,
        "status": first_flag_label(node),
        "summary": text(node, "summary"),
        "who": who or "—",
        "floors": floors or "—",
        "when": when or "—",
        "role": role or "—",
        "path": text(node, "path") or "—",
        "claim": "",
        "peers": [],
        "files": [],
        "cards": [],
        "message": "入学占位，还没有说清这个目录" if placeholder else "",
    }

def empty_inspect(headline: str = "") -> dict[str, Any]:
    return {
        "mode": "empty",
        "title": "点文件树或知识卡",
        "status": headline or "点文件树或知识卡查看归属。",
        "summary": "",
        "claim": "",
        "path": "",
        "peers": [],
        "files": [],
        "cards": [],
        "message": "",
    }

def file_owned_by_card(node: dict[str, Any], card: dict[str, Any]) -> bool:
    rel = file_relpath(node)
    owners = claim_owners(node)
    kind = text(card, "kind")
    card_id = text(card, "id")
    title = text(card, "title") or card_id
    if kind == "knowledge":
        if title in owners or card_id in owners:
            return True
        if text(node, "parentCard") == card_id:
            return True
        if card.get("jurisdiction") or card.get("household") or card.get("span"):
            return _rel_under_card(rel, card)
        return False
    if kind == "gap":
        if owners:
            return False
        prefixes = _card_path_prefixes(card)
        if not prefixes:
            return True
        return any(rel == prefix or rel.startswith(prefix + "/") for prefix in prefixes)
    if kind == "work":
        prefixes = _card_path_prefixes(card)
        return any(rel == prefix or rel.startswith(prefix + "/") or prefix.startswith(rel + "/") for prefix in prefixes)
    return False

def _file_card_summary(cards: list[dict[str, Any]], rel: str) -> str:
    for card in cards:
        if text(card, "kind") not in {"", "knowledge"} and text(card, "type") not in {"", "knowledge"}:
            continue
        if card.get("jurisdiction") or card.get("household"):
            continue
        includes: list[str] = []
        for scope in card.get("scopes") or []:
            if not isinstance(scope, dict):
                continue
            includes.extend(str(item) for item in (scope.get("include") or scope.get("includes") or []) if item)
        paths = [item.replace("\\", "/").split(":", 1)[-1].lstrip("/") for item in includes]
        if paths == [rel.replace("\\", "/").lstrip("/")]:
            return text(card, "summary")
    return ""

def design_summary_for_file(rel: str, owner_cards: list[dict[str, Any]], all_cards: list[dict[str, Any]]) -> str:
    if len(owner_cards) != 1:
        return ""
    owner = owner_cards[0]
    household = bool(owner.get("jurisdiction") or owner.get("household") or owner.get("span"))
    if not household:
        return text(owner, "summary")
    span = _card_span(owner)
    if span == "folder":
        return text(owner, "summary")
    if span == "file":
        return _file_card_summary(all_cards, rel)
    return ""

def inspect_file(
    node: dict[str, Any],
    files: list[tuple[str, dict[str, Any]]],
    cards: list[dict[str, Any]],
) -> dict[str, Any]:
    rel = file_relpath(node)
    owners = claim_owners(node)
    matched = cards_for_owners(cards, owners)
    related: list[dict[str, str]] = []
    seen: set[str] = set()
    for card in matched:
        title = text(card, "title") or text(card, "id")
        key = row_key(card, title)
        if key in seen:
            continue
        seen.add(key)
        related.append({"id": key, "title": title})
    for owner in owners:
        if owner in seen or any(item["title"] == owner for item in related):
            continue
        related.append({"id": owner, "title": owner})
    summary = design_summary_for_file(rel, matched, cards)
    return {
        "mode": "file",
        "title": text(node, "title") or rel.rsplit("/", 1)[-1],
        "status": card_problem_status(node),
        "summary": summary,
        "claim": claim_label(node),
        "path": rel,
        "peers": peer_rels(files, node),
        "files": [],
        "cards": related,
        "message": "未认领" if not owners else "",
    }

def inspect_card(card: dict[str, Any], files: list[tuple[str, dict[str, Any]]]) -> dict[str, Any]:
    governed = files_for_card(files, card)
    flags = card.get("flags") if isinstance(card.get("flags"), list) else []
    placeholder = text(card, "statusTag") == "placeholder" or "placeholder" in {str(item) for item in flags}
    household = is_directory_household(card)
    span = _card_span(card) if household else ""
    if placeholder:
        message = "入学占位，还没有说清这个目录"
    elif governed:
        message = ""
    else:
        message = "这张卡还没有落到文件树上的代码文件"
    show_design = bool(text(card, "summary")) and (not household or span == "folder")
    from .graph import knowledge_title, lineage_heading, lineage_ordinal_label

    summary = text(card, "summary") if show_design else ""
    title = knowledge_title(card)
    heading = lineage_heading(card, title=title)
    return {
        "mode": "card",
        "title": heading,
        "status": card_problem_status(card),
        "summary": summary,
        "detail": summary,
        "ordinal": lineage_ordinal_label(card),
        "claim": "",
        "path": "",
        "peers": [],
        "files": governed,
        "cards": [],
        "message": message,
        "span": span if household else None,
        "span_label": SPAN_LABELS.get(span, "未打标") if household else "",
        "card_id": text(card, "id"),
    }

def _exact_file_card(cards: list[dict[str, Any]], rel: str) -> dict[str, Any] | None:
    needle = rel.replace("\\", "/").lstrip("/")
    for card in cards:
        if text(card, "kind") not in {"", "knowledge"} and text(card, "type") not in {"", "knowledge"}:
            continue
        if card.get("jurisdiction") or card.get("household"):
            continue
        includes: list[str] = []
        for scope in card.get("scopes") or []:
            if not isinstance(scope, dict):
                continue
            includes.extend(_clean_scope_path(str(item)) for item in (scope.get("include") or scope.get("includes") or []) if item)
        if includes == [needle]:
            return card
    return None

def focus_file(
    files: list[tuple[str, dict[str, Any]]],
    cards: list[dict[str, Any]],
    rel: str,
) -> dict[str, Any] | None:
    node = next((item for path, item in files if path == rel), None)
    if node is None:
        return None
    owners = claim_owners(node)
    matched = cards_for_owners(cards, owners)
    file_card = _exact_file_card(cards, rel)
    primary = file_card or (matched[0] if matched else None)
    card_keys = {row_key(primary, text(primary, "title"))} if primary else set()
    prefixes: set[str] = set(ancestor_prefixes(rel))
    primary_key = row_key(primary, text(primary, "title")) if primary else ""
    inspect = inspect_file(node, files, cards)
    inspect["peers"] = []
    return {
        "selected_file": rel,
        "selected_card_key": primary_key,
        "highlight_card_keys": card_keys,
        "inspect_key": row_key(node, rel),
        "inspect": inspect,
        "highlight_paths": {rel} if owners else set(),
        "force_open": prefixes,
        "scroll_card_key": primary_key,
        "scroll_file_key": coverage_scroll_key(files, {rel}),
    }

def focus_card(
    files: list[tuple[str, dict[str, Any]]],
    card: dict[str, Any],
) -> dict[str, Any]:
    governed = files_for_card(files, card)
    prefixes: set[str] = set()
    for path in governed:
        prefixes.update(ancestor_prefixes(path))
    title = text(card, "title") or text(card, "id")
    key = row_key(card, title)
    card_id = text(card, "id") or key
    highlight = set(governed)
    return {
        "selected_file": "",
        "selected_card_key": key,
        "highlight_card_keys": {key},
        "inspect_key": key,
        "inspect": inspect_card(card, files),
        "highlight_paths": highlight,
        "force_open": prefixes,
        "scroll_card_key": key,
        "scroll_file_key": coverage_scroll_key(files, highlight),
    }

def coverage_rows(details: dict[str, Any] | None, query: str, flag: str) -> tuple[list[tuple[str, dict[str, Any]]], list[dict[str, Any]], str]:
    files: list[tuple[str, dict[str, Any]]] = []
    cards: list[dict[str, Any]] = []
    headline = "点文件树或知识卡查看归属。"
    if not details:
        return files, cards, "选择一个项目后，这里显示谁管理文件、是不是开工或黑盒。"
    graph = details.get("graph") if isinstance(details.get("graph"), dict) else {}
    raw_headline = graph.get("headline")
    if raw_headline:
        headline = str(raw_headline)
    nodes = graph.get("nodes") if isinstance(graph.get("nodes"), list) else []
    for raw in nodes:
        if not isinstance(raw, dict):
            continue
        kind = text(raw, "kind")
        if kind in {"knowledge", "gap", "work"}:
            if node_matches(raw, query, flag):
                cards.append(raw)
            continue
        if kind != "file" or not node_matches(raw, query, flag):
            continue
        rel = file_relpath(raw)
        if rel:
            files.append((rel, raw))
    return files, cards, headline

def file_tree_children(
    files: list[tuple[str, dict[str, Any]]],
) -> dict[str, list[tuple[str, str, str, dict[str, Any]]]]:
    """Nest files under folder prefixes. Root parent is '' so src/ag2c/a.py can open src."""
    buckets: dict[str, dict[str, tuple[str, str, dict[str, Any]]]] = {}
    for rel, node in files:
        parts = [part for part in rel.replace("\\", "/").split("/") if part]
        if not parts:
            continue
        for index, name in enumerate(parts):
            parent = "/".join(parts[:index])
            prefix = "/".join(parts[: index + 1])
            slot = buckets.setdefault(parent, {})
            if index == len(parts) - 1:
                slot[name] = ("file", prefix, node)
            elif name not in slot or slot[name][0] != "file":
                slot[name] = (
                    "dir",
                    prefix,
                    {"kind": "folder", "title": name, "path": prefix, "summary": "文件夹"},
                )
    tree: dict[str, list[tuple[str, str, str, dict[str, Any]]]] = {}
    for parent, slot in buckets.items():
        items = [(name, kind, prefix, node) for name, (kind, prefix, node) in slot.items()]
        items.sort(key=lambda item: (0 if item[1] == "dir" else 1, item[0].lower()))
        tree[parent] = items
    return tree

def coverage_scroll_key(files: list[tuple[str, dict[str, Any]]], highlight: set[str]) -> str:
    """Tree prefix pinned at the top of the file-tree body for a highlighted coverage."""
    hits = [rel for rel, _node in files if rel in highlight]
    if not hits:
        return ""
    if len(hits) == 1:
        rel = hits[0]
        return rel.rsplit("/", 1)[0] if "/" in rel else rel
    parts_list = [rel.split("/") for rel in hits]
    common: list[str] = []
    for index, piece in enumerate(parts_list[0]):
        if all(len(parts) > index + 1 and parts[index] == piece for parts in parts_list):
            common.append(piece)
        else:
            break
    if common:
        return "/".join(common)
    tree = file_tree_children([(rel, node) for rel, node in files if rel in highlight])

    def walk(parent: str) -> str:
        for _name, kind, prefix, _node in tree.get(parent, []):
            if kind == "file" and prefix in highlight:
                return prefix
            if kind == "dir":
                found = walk(prefix)
                if found:
                    return found
        return ""

    return walk("") or hits[0]
