"""Extracted by flatten-split."""
from __future__ import annotations
import os
import time
from pathlib import Path
from typing import Any
from .custody import apply_custody_clicks, custody_model, draw_custody
from .tray_host import FILTERS, PRODUCT_LABELS, WORKTREE_LIFE_LABELS, card_list_label, claim_label, files_for_card, inspect_fields, issue_label, mcp_entry_text, project_gate_rows, state_label, string_list, text
from .imgui_tray import AppState, GATE_BUTTON_LABELS, _OPS_TABS, _SELECTED_ACTIVE_COLOR, _SELECTED_HOVER_COLOR, _TOAST_TTL_S, _TOAST_WIDTH, _WARN_COLOR, _activate_owner, _audit_log_path, _cached_all_rows, _cached_coverage, _cached_tree, _choose_project, _clip_label, _copy_mcp_entry, _focus_card, _focus_path, _load_details, _open_folder, _post, _refresh, _refresh_panel, _selectable, audit, node_key, widget_id

def _short_time(iso: str) -> str:
    """ISO timestamp → local 'MM-dd HH:mm' for compact history rows."""
    if not iso:
        return ""
    from datetime import datetime, timezone

    try:
        moment = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return iso[:16]
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone().strftime("%m-%d %H:%M")

def _gui_dashboard(state: AppState) -> None:
    """市长桌：看 / 否 / 授。旧决策队列不再占首页。"""
    with state.lock:
        details = state.details
        guard = dict(state.guard)
    apply_custody_clicks(state, draw_custody(custody_model(details, guard)))

def _gui_splash(state: AppState) -> None:
    """Full-window animated splash while loading; replaces per-pane progress bars."""
    from imgui_bundle import imgui

    with state.lock:
        loading = state.loading
        status = state.status
    if not loading:
        return
    viewport = imgui.get_main_viewport()
    imgui.set_next_window_pos(viewport.pos)
    imgui.set_next_window_size(viewport.size)
    imgui.set_next_window_bg_alpha(0.94)
    flags = (
        imgui.WindowFlags_.no_title_bar
        | imgui.WindowFlags_.no_resize
        | imgui.WindowFlags_.no_move
        | imgui.WindowFlags_.no_scrollbar
        | imgui.WindowFlags_.no_collapse
        | imgui.WindowFlags_.no_docking
        | imgui.WindowFlags_.no_saved_settings
        | imgui.WindowFlags_.no_inputs
    )
    imgui.begin("##splash", None, flags)
    try:
        import math

        now = imgui.get_time()
        width = float(viewport.size.x)
        height = float(viewport.size.y)
        imgui.dummy(imgui.ImVec2(width, height))  # grow boundaries so absolute cursor placement is legal
        title = "AutoGovern2Code"
        title_size = 40.0
        font = imgui.get_font()
        base_w = float(imgui.calc_text_size(title).x)
        title_w = base_w * (title_size / max(float(font.legacy_size), 1.0))
        pulse = 0.55 + 0.45 * math.sin(now * 2.2)
        title_pos = imgui.ImVec2(max((width - title_w) / 2.0, 8.0), height * 0.34)
        title_color = imgui.get_color_u32(imgui.ImVec4(0.62, 0.78, 1.0, pulse))
        imgui.get_window_draw_list().add_text(font, title_size, title_pos, title_color, title)
        subtitle = (status or "正在启动") + ("." * (int(now * 2.0) % 4)).ljust(3)
        subtitle_w = float(imgui.calc_text_size(subtitle).x)
        imgui.set_cursor_pos(imgui.ImVec2(max((width - subtitle_w) / 2.0, 8.0), height * 0.34 + title_size + 24.0))
        imgui.text_disabled(subtitle)
        bar_w = min(280.0, width - 32.0)
        imgui.set_cursor_pos(imgui.ImVec2(max((width - bar_w) / 2.0, 8.0), height * 0.34 + title_size + 52.0))
        imgui.progress_bar(-0.35 * now, imgui.ImVec2(bar_w, 6.0), "")
    finally:
        imgui.end()

def _status_bar(state: AppState) -> None:
    from imgui_bundle import imgui

    with state.lock:
        status = state.status
        busy = state.busy
        loading = state.loading
        guard_warning = state.guard_warning
    if guard_warning:
        imgui.text_colored((0.95, 0.35, 0.30, 1.0), guard_warning)
    prefix = ""
    if loading or busy:
        spin = "|/-\\"[int(imgui.get_time() * 8) % 4]
        prefix = f"{spin} 扫描中 · "
    imgui.text(prefix + status)
    drawer_labels = ("文件树", "检查器", "运维")
    btn_w = sum(float(imgui.calc_text_size(label).x) + 18.0 for label in drawer_labels) + 16.0
    width = float(imgui.get_window_width())
    imgui.same_line(max(8.0, width - btn_w))
    for index, label in enumerate(drawer_labels):
        visible = state.dock_visible(label)
        if visible:
            imgui.push_style_color(imgui.Col_.button, (0.28, 0.50, 0.78, 0.70))
            imgui.push_style_color(imgui.Col_.button_hovered, (0.32, 0.56, 0.84, 0.85))
        clicked = imgui.small_button(label)
        if visible:
            imgui.pop_style_color(2)
        if clicked:
            now = state.toggle_dock(label)
            audit(state, ("打开" if now else "关闭") + label, "状态栏", "")
        if index < len(drawer_labels) - 1:
            imgui.same_line()

def _gui_overlays(state: AppState) -> None:
    """Splash + toast notifications float above the dock layout."""
    _gui_splash(state)
    _gui_toasts(state)

def _gui_toasts(state: AppState) -> None:
    """In-app toast overlay for gate-block notifications. No external deps."""
    from imgui_bundle import imgui

    with state.lock:
        toasts = list(state.toasts)
    if not toasts:
        return
    now = time.monotonic()
    expired: list[str] = []
    viewport = imgui.get_main_viewport()
    y_offset = viewport.pos.y + 40.0
    for toast in toasts:
        age = now - toast["born"]
        if age > _TOAST_TTL_S:
            expired.append(toast["id"])
            continue
        alpha = 1.0 if age < _TOAST_TTL_S - 1.5 else max(0.0, (_TOAST_TTL_S - age) / 1.5)
        imgui.set_next_window_pos(
            imgui.ImVec2(viewport.pos.x + viewport.size.x - _TOAST_WIDTH - 16.0, y_offset),
            imgui.Cond_.always,
        )
        imgui.set_next_window_bg_alpha(0.92 * alpha)
        flags = (
            imgui.WindowFlags_.no_title_bar
            | imgui.WindowFlags_.no_resize
            | imgui.WindowFlags_.no_move
            | imgui.WindowFlags_.no_collapse
            | imgui.WindowFlags_.no_docking
            | imgui.WindowFlags_.no_saved_settings
            | imgui.WindowFlags_.always_auto_resize
        )
        kind_colors = {
            "gate-block": (0.95, 0.45, 0.30, 1.0),
            "verify-fail": (0.95, 0.35, 0.30, 1.0),
            "canonical-dirty": (0.95, 0.70, 0.30, 1.0),
            "census-stale": (0.95, 0.70, 0.30, 1.0),
            "hazard": (0.95, 0.25, 0.25, 1.0),
        }
        color = kind_colors.get(toast["kind"], (0.55, 0.75, 0.95, 1.0))
        imgui.begin(f"##toast-{toast['id']}", None, flags)
        imgui.text_colored(color, toast["title"])
        if toast["detail"]:
            imgui.text_wrapped(toast["detail"][:120])
        if imgui.is_window_hovered() and imgui.is_mouse_clicked(0):
            expired.append(toast["id"])
        imgui.end()
        y_offset += 70.0
    if expired:
        with state.lock:
            state.toasts = [t for t in state.toasts if t["id"] not in set(expired)]
        # Acknowledge in the queue so they don't reappear.
        try:
            from ag2c.notify import acknowledge
            for nid in expired:
                acknowledge(state._notify_project_id, nid)
        except Exception:
            pass

def _audit_body(state: AppState) -> None:
    """Operation log content, rendered inside the 运维 drawer's tab."""
    from imgui_bundle import imgui

    path = str(_audit_log_path())
    imgui.text_disabled(f"{len(state.audit_lines)} 条 · {path}")
    if imgui.small_button("清空"):
        state.audit_lines.clear()
    imgui.same_line()
    if imgui.small_button("打开日志文件"):
        try:
            if Path(path).is_file():
                os.startfile(path)  # noqa: S606
        except OSError:
            pass
    imgui.separator()
    imgui.begin_child("##audit-body", imgui.ImVec2(0.0, 0.0), 1)
    try:
        if not state.audit_lines:
            imgui.text_disabled("还没有操作。点击文件或知识卡后会出现在这里。")
        else:
            for line in reversed(state.audit_lines):
                imgui.text_wrapped(line)
    finally:
        imgui.end_child()

def _gate_panel_content(state: AppState, fields: dict[str, Any]) -> None:
    from imgui_bundle import imgui

    imgui.text_wrapped("这里只有两件事：通用 MCP 连接说明（占位符，不绑厂商），以及检测 MCP 是否在工作。Skill 全文在 MCP 里；检测会连 Git hook 一起看。")
    if imgui.button("检测 MCP"):
        from ag2c.mcp_server import install_mcp_clients, mcp_health

        try:
            install_mcp_clients()
        except OSError:
            pass
        health = mcp_health(handshake=True, cwd=str(fields.get("path") or "") or None)
        with state.lock:
            panel = state.panel_fields.setdefault("gate", {})
            panel["mcp_health"] = health
            panel["status"] = str(health.get("label") or "")
            panel["prompt"] = mcp_entry_text()
            state.status = str(health.get("label") or "MCP")
        audit(state, "检测 MCP", "MCP 链接", str(health.get("status") or ""))
    imgui.same_line()
    if imgui.button("复制连接说明"):
        copied = _copy_mcp_entry()
        with state.lock:
            state.panel_fields.setdefault("gate", {})["prompt"] = copied
            state.status = "连接说明已复制"
        audit(state, "复制连接说明", "MCP 链接", "")
    health = fields.get("mcp_health") if isinstance(fields.get("mcp_health"), dict) else {}
    if health:
        detail = str(health.get("label") or "")
        if health.get("error"):
            detail += " · " + str(health["error"])
        elif health.get("ok"):
            detail += f" · 工具 {health.get('tool_count') or 0} · Skill 已内化"
            configured = int(health.get("configured") or 0)
            if configured:
                detail += f" · 本机已写入 {configured} 处配置"
        imgui.text_disabled(detail)
    else:
        imgui.text_disabled("点「检测 MCP」做一次握手。连接说明只用占位符，不含本机路径。")
    prompt = str(fields.get("prompt") or "")
    if prompt:
        imgui.separator()
        imgui.text_wrapped(prompt)

def _records_panel_content(state: AppState, fields: dict[str, Any]) -> None:
    from imgui_bundle import imgui

    completed = int(fields.get("completed_tasks") or 0)
    imgui.text_disabled(f"{completed} 次入库" if completed else "还没有入库任务")
    product = fields.get("product")
    product_key = str(product.get("status") or product) if isinstance(product, dict) else str(product or "")
    if product_key:
        imgui.same_line()
        imgui.text_disabled(PRODUCT_LABELS.get(product_key, product_key))
    imgui.separator()
    versions = [item for item in (fields.get("journal") or []) if isinstance(item, dict)]
    if not versions:
        imgui.text_disabled("还没有历史记录")
        return
    imgui.begin_child("##records-body", imgui.ImVec2(0.0, 0.0), 1)
    try:
        for item in versions:
            header = f"v{item.get('version') or '?'} · {_short_time(str(item.get('marked_at') or ''))}"
            commit = str(item.get("commit") or "")[:7]
            if commit:
                header += f" · {commit}"
            imgui.text_disabled(header)
            goal = str(item.get("goal") or "")
            if goal:
                imgui.text_wrapped(goal)
            outcome = str(item.get("outcome") or "")
            if outcome and outcome != goal:
                imgui.push_style_color(imgui.Col_.text, (0.62, 0.68, 0.76, 1.0))
                imgui.text_wrapped(outcome)
                imgui.pop_style_color()
            imgui.separator()
    finally:
        imgui.end_child()

def _work_panel_content(state: AppState, fields: dict[str, Any]) -> None:
    from imgui_bundle import imgui

    rows = [item for item in (fields.get("worktrees") or []) if isinstance(item, dict)]
    open_rows = [item for item in rows if str(item.get("state") or "") in {"active", "verified"}]
    if not open_rows:
        imgui.text_wrapped("没有进行中的施工")
        return
    for item in open_rows:
        life = str((item.get("worktree") or {}).get("lifecycle") or "")
        label = WORKTREE_LIFE_LABELS.get(life) or WORKTREE_LIFE_LABELS.get(str(item.get("state") or ""), str(item.get("state") or ""))
        goal = str(item.get("goal") or item.get("id") or "")
        warn = life in {"diverged", "missing", "verified-unmerged", "verified-stale"} or str(item.get("state") or "") == "verified"
        if warn:
            imgui.text_colored(_WARN_COLOR, f"{label}  ·  {goal}")
        else:
            imgui.text(f"{label}  ·  {goal}")

def _gui_ops(state: AppState) -> None:
    """运维 drawer: one dockable window, four tabs — no more floating windows."""
    from imgui_bundle import imgui

    if not imgui.begin_tab_bar("##ops-tabs"):
        return
    try:
        for kind, title in _OPS_TABS:
            flags = 0
            if state.ops_tab == kind:
                flags |= int(imgui.TabItemFlags_.set_selected)
                state.ops_tab = ""
            selected, _ = imgui.begin_tab_item(title, None, flags)
            if selected:
                state.ops_active = kind
                try:
                    if kind == "audit":
                        _audit_body(state)
                    else:
                        with state.lock:
                            fields = dict(state.panel_fields.get(kind) or {})
                        if not fields:
                            imgui.text_disabled("点项目栏的门状态行刷新这里的内容")
                        elif kind == "gate":
                            _gate_panel_content(state, fields)
                        elif kind == "records":
                            _records_panel_content(state, fields)
                        elif kind == "worktrees":
                            _work_panel_content(state, fields)
                finally:
                    imgui.end_tab_item()
    finally:
        imgui.end_tab_bar()

def _gui_inspector(state: AppState) -> None:
    """检查器 drawer: 详情 + 知识卡片 as tabs of one dockable window."""
    from imgui_bundle import imgui

    if not imgui.begin_tab_bar("##inspector-tabs"):
        return
    try:
        selected, _ = imgui.begin_tab_item("详情", None, 0)
        if selected:
            try:
                _gui_inspect(state)
            finally:
                imgui.end_tab_item()
        selected, _ = imgui.begin_tab_item("知识卡片", None, 0)
        if selected:
            try:
                _gui_cards(state)
            finally:
                imgui.end_tab_item()
    finally:
        imgui.end_tab_bar()

def _gui_project_bar(state: AppState) -> None:
    from imgui_bundle import imgui

    with state.lock:
        rows = list(state.projects)
        selected = state.selected_root
        busy = state.busy
        loading = state.loading
    labels = [f"{text(row, 'name')}  ·  {state_label(text(row, 'state'))}" for row in rows]
    current = next((index for index, row in enumerate(rows) if text(row, "root") == selected), 0)
    avail = float(imgui.get_content_region_avail().x)
    imgui.set_next_item_width(max(80.0, avail - 148.0))
    preview = labels[current] if labels else "选择项目"
    if imgui.begin_combo("##project", preview):
        try:
            for index, label in enumerate(labels):
                root = text(rows[index], "root")
                picked = _selectable(widget_id(label, root), index == current)
                if imgui.is_item_hovered():
                    imgui.set_tooltip(root)
                if picked and root != selected:
                    audit(state, "切换项目", "项目栏", root)
                    with state.lock:
                        state.selected_root = root
                        state.digest = ""
                        state.clear_focus()
                    state.run_job(lambda path=root: _load_details(state, path))
                    selected = root
        finally:
            imgui.end_combo()
    imgui.same_line()
    if imgui.button("添加") and not state._dialog_lock:
        audit(state, "添加项目", "项目栏", "")
        _choose_project(state)
    imgui.same_line()
    if imgui.button("刷新") and not busy:
        audit(state, "刷新", "项目栏", selected or "")
        state.run_job(lambda: _refresh(state))
    project = next((row for row in rows if text(row, "root") == selected), None)
    if project is not None:
        imgui.text_disabled(state_label(text(project, "state")))
        issues = string_list(project, "issues")
        if issues:
            imgui.text_wrapped("！  " + "；".join(issue_label(item) for item in issues[:2]))
        governance = text(project, "governance")
        if imgui.small_button("打开文件夹") and not state._dialog_lock:
            audit(state, "打开文件夹", "项目栏", text(project, "root"))
            _open_folder(state, text(project, "root"))
        imgui.same_line()
        if imgui.small_button("重新检查"):
            audit(state, "重新检查", "项目栏", text(project, "root"))
            state.run_job(lambda: _post(state, "api/projects/check", text(project, "root")))
        imgui.same_line()
        if governance != "stopped":
            if imgui.small_button("停止治理"):
                audit(state, "停止治理", "项目栏", text(project, "root"))
                state.run_job(lambda: _post(state, "api/projects/remove", text(project, "root")))
        else:
            if imgui.small_button("恢复治理"):
                audit(state, "恢复治理", "项目栏", text(project, "root"))
                state.run_job(lambda: _post(state, "api/projects/resume", text(project, "root")))
        imgui.same_line()
        if imgui.small_button("卸载"):
            audit(state, "卸载", "项目栏", text(project, "root"))
            state.run_job(lambda: _post(state, "api/projects/uninstall", text(project, "root")))
        _gui_gate_strip(state, project)
    imgui.separator()

def _gui_gate_strip(state: AppState, project: dict[str, Any]) -> None:
    """Always-visible operator pulse. Each row focuses one tab of the 运维 drawer."""
    from imgui_bundle import imgui

    with state.lock:
        details = state.details
    rows = project_gate_rows(project, details)
    if not rows:
        return
    imgui.spacing()
    for row in rows:
        label = str(row.get("label") or "")
        value = str(row.get("value") or "")
        kind = str(row.get("id") or "")
        warn = bool(row.get("warn"))
        name = GATE_BUTTON_LABELS.get(kind, label)
        shown = f"{name} · {value}"
        active = state.dock_visible("运维") and state.ops_active == kind
        pushed = 0
        if warn:
            imgui.push_style_color(imgui.Col_.text, _WARN_COLOR)
            pushed += 1
        clicked = _selectable(widget_id(shown, "gate:" + kind), active)
        if pushed:
            imgui.pop_style_color(pushed)
        if clicked:
            if active:
                state.set_dock_visible("运维", False)
                audit(state, "关闭运维", "项目栏", value)
            else:
                audit(state, "打开运维·" + name, "项目栏", value)
                state.open_ops(kind)
                _refresh_panel(state, kind, project, details)

_ROOT_FILE_DUMP_LIMIT = 16


def _auto_open_root_dir(nested: list) -> bool:
    """Top-level dirs auto-open unless they are a large file-only dump (tests/)."""
    return any(kind == "dir" for _name, kind, _prefix, _node in nested) or len(nested) <= _ROOT_FILE_DUMP_LIMIT


def _gui_tree(state: AppState) -> None:
    from imgui_bundle import imgui

    _gui_project_bar(state)
    imgui.set_next_item_width(-1)
    changed, value = imgui.input_text_with_hint("##search", "frontend、css、文件名或知识卡", state.search)
    if changed:
        state.search = value
    labels = [label for _, label in FILTERS]
    changed, state.filter_index = imgui.combo("##filter", state.filter_index, labels)
    if changed:
        audit(state, "筛选", "文件树", labels[state.filter_index] if 0 <= state.filter_index < len(labels) else "")
    with state.lock:
        details = state.details
        search = state.search
        selected_file = state.selected_file
        inspect_key = state.inspect_key
        highlight = set(state.highlight_paths)
        force_open = set(state.force_open)
        scroll_file = state.scroll_file_key
        scroll_frames = state.scroll_file_frames
        loading = state.loading
        flag = FILTERS[state.filter_index][0] if 0 <= state.filter_index < len(FILTERS) else ""
    all_files, _all_cards = _cached_all_rows(state, details)
    files, _cards = _cached_coverage(state, details, search, flag)
    if details is None:
        imgui.text_disabled("选择一个项目后，这里显示谁管理文件、是不是开工或黑盒。")
        return
    if not all_files:
        imgui.text_disabled("启动中 · 正在刷新" if loading else "这个项目还没有可对照的代码文件")
        return
    tree = _cached_tree(state, files)
    scrolled = False

    def draw(parent: str, depth: int = 0) -> None:
        nonlocal scrolled
        for name, kind, prefix, node in tree.get(parent, []):
            nested = tree.get(prefix, [])
            key = node_key(node, prefix)
            flags = imgui.TreeNodeFlags_.span_avail_width
            if kind == "file" or not nested:
                flags |= imgui.TreeNodeFlags_.leaf
            kin = kind == "file" and prefix in highlight and prefix != selected_file
            selected = (kind == "file" and prefix == selected_file) or (kind != "file" and inspect_key == key)
            if selected or kin:
                flags |= imgui.TreeNodeFlags_.selected
            if kind == "dir" and nested:
                if force_open and prefix in force_open:
                    imgui.set_next_item_open(True)
                elif depth == 0 and _auto_open_root_dir(nested):
                    imgui.set_next_item_open(True, imgui.Cond_.once)
            claim = claim_label(node) if kind == "file" else ""
            visible = f"{name}  {claim}" if claim else name
            pushed = 0
            if kin:
                imgui.push_style_color(imgui.Col_.header, (0.28, 0.50, 0.78, 0.32))
                imgui.push_style_color(imgui.Col_.header_hovered, (0.28, 0.50, 0.78, 0.40))
                pushed += 2
            if selected:
                imgui.push_style_color(imgui.Col_.header_hovered, _SELECTED_HOVER_COLOR)
                imgui.push_style_color(imgui.Col_.header_active, _SELECTED_ACTIVE_COLOR)
                pushed += 2
            if claim == "未认领":
                imgui.push_style_color(imgui.Col_.text, (0.90, 0.55, 0.38, 1.0))
                pushed += 1
            elif claim == "重复认领":
                imgui.push_style_color(imgui.Col_.text, _WARN_COLOR)
                pushed += 1
            opened = imgui.tree_node_ex(widget_id(visible, prefix), flags)
            if pushed:
                imgui.pop_style_color(pushed)
            if (scroll_file or scroll_frames) and prefix == scroll_file and not scrolled:
                item_y = float(imgui.get_item_rect_min().y)
                win_y = float(imgui.get_window_pos().y)
                imgui.set_scroll_y(max(0.0, float(imgui.get_scroll_y()) + (item_y - win_y)))
                imgui.set_scroll_here_y(0.0)
                scrolled = True
            if imgui.is_item_clicked():
                if kind == "file":
                    _focus_path(state, prefix)
                else:
                    audit(state, "点击目录", "文件树", prefix)
                    with state.lock:
                        state.clear_focus()
                        state.inspect = inspect_fields(node)
                        state.inspect_key = key
            if opened:
                if nested:
                    draw(prefix, depth + 1)
                imgui.tree_pop()

    imgui.begin_child(
        "##file-tree-body",
        imgui.ImVec2(0.0, 0.0),
        0,
        imgui.WindowFlags_.horizontal_scrollbar,
    )
    try:
        draw("")
    finally:
        imgui.end_child()
    if scroll_file or scroll_frames:
        with state.lock:
            if state.scroll_file_frames > 0:
                state.scroll_file_frames -= 1
            if state.scroll_file_frames <= 0:
                state.scroll_file_key = ""
                state.scroll_file_frames = 0

def _gui_cards(state: AppState) -> None:
    from imgui_bundle import imgui

    with state.lock:
        details = state.details
        search = state.search
        selected_card = state.selected_card_key
        highlight_cards = set(state.highlight_card_keys)
        scroll_card = state.scroll_card_key
        flag = FILTERS[state.filter_index][0] if 0 <= state.filter_index < len(FILTERS) else ""
    all_files, all_cards = _cached_all_rows(state, details)
    _files, cards = _cached_coverage(state, details, search, flag)
    if details is not None and not all_cards:
        imgui.text_disabled("还没有知识卡")
        return
    imgui.text_disabled("序号按层写：1、1-2、1-1-1。卡名就是摘要（最多20字）。左侧搜索可按卡名查找。")
    imgui.push_style_var(imgui.StyleVar_.item_spacing, imgui.ImVec2(4.0, 1.0))
    imgui.push_text_wrap_pos(-1.0)
    children_of: dict[str, list[dict[str, Any]]] = {}
    roots: list[dict[str, Any]] = []
    for node in cards:
        parent_id = text(node, "parentCard")
        if parent_id:
            children_of.setdefault(parent_id, []).append(node)
        else:
            roots.append(node)

    def _draw_card_row(node: dict[str, Any], *, indent: bool, ordinal_label: str) -> None:
        title = text(node, "title") or text(node, "id")
        key = node_key(node, title)
        count = state.card_file_counts.get(key)
        if count is None:
            count = len(files_for_card(all_files, node))
        short = _clip_label(title, 188.0 if indent else 208.0)
        label = card_list_label(short, node, count, ordinal_label=ordinal_label)
        marked = selected_card == key or key in highlight_cards
        if indent:
            imgui.indent(16.0)
        if _selectable(widget_id(label, key), marked):
            node["ordinal_label"] = ordinal_label
            _focus_card(state, node)
        if indent:
            imgui.unindent(16.0)
        if scroll_card and key == scroll_card:
            imgui.set_scroll_here_y(0.25)
            with state.lock:
                state.scroll_card_key = ""

    for index, node in enumerate(roots, 1):
        _draw_card_row(node, indent=False, ordinal_label=str(index))
        kids = children_of.get(text(node, "id"), [])
        for child_index, child in enumerate(kids, 1):
            _draw_card_row(child, indent=True, ordinal_label=f"{index}-{child_index}")
    imgui.pop_text_wrap_pos()
    imgui.pop_style_var()

def _gui_inspect(state: AppState) -> None:
    from imgui_bundle import imgui

    with state.lock:
        fields = dict(state.inspect)
        error = state.error
        busy = state.busy or state.loading
    if error:
        imgui.push_style_color(imgui.Col_.text, (0.86, 0.2, 0.2, 1.0))
        imgui.text_wrapped(error)
        imgui.pop_style_color()
    mode = str(fields.get("mode") or "empty")
    imgui.text_wrapped(str(fields.get("title") or "点文件树或知识卡"))
    if fields.get("path") and mode in {"file", "module"}:
        imgui.text_disabled(str(fields.get("path")))
    if fields.get("status") and str(fields["status"]) not in {"", "在册"}:
        status = str(fields["status"])
        if status == "占位":
            imgui.text_colored(_WARN_COLOR, status)
        else:
            imgui.text_disabled(status)
    if mode == "project":
        if fields.get("summary"):
            imgui.separator()
            imgui.text_disabled("宪章")
            imgui.text_wrapped(str(fields.get("summary")))
        return
    if mode == "module":
        if fields.get("summary"):
            imgui.separator()
            imgui.text_disabled("设计思路")
            imgui.text_wrapped(str(fields.get("summary")))
        related = fields.get("cards") if isinstance(fields.get("cards"), list) else []
        imgui.separator()
        imgui.text_disabled(f"知识卡 {len(related)} 张")
        if not related:
            imgui.text_wrapped(str(fields.get("message") or "还没有知识卡"))
        for item in related:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or item.get("id") or "")
            key = str(item.get("id") or title)
            if _selectable(widget_id(title, "lineage-mod:" + key)):
                _activate_owner(state, title, where="详情")
        return
    if mode == "file":
        imgui.separator()
        imgui.text_disabled("认领")
        imgui.text_wrapped(str(fields.get("claim") or "未认领"))
        if fields.get("summary"):
            imgui.separator()
            imgui.text_disabled("设计思路")
            imgui.text_wrapped(str(fields.get("summary")))
        related = fields.get("cards") if isinstance(fields.get("cards"), list) else []
        if related:
            imgui.separator()
            imgui.text_disabled(f"归属知识卡 {len(related)} 张")
            for item in related:
                if not isinstance(item, dict):
                    continue
                title = str(item.get("title") or item.get("id") or "")
                key = str(item.get("id") or title)
                if _selectable(widget_id(title, key)):
                    _activate_owner(state, title, where="详情")
        peers = [str(item) for item in fields.get("peers") or [] if str(item)]
        if peers:
            imgui.separator()
            imgui.text_disabled(f"同类 {len(peers)} 个文件")
            for rel in peers:
                if _selectable(widget_id(rel, rel), rel == text(fields, "path")):
                    _focus_path(state, rel, where="详情")
        elif str(fields.get("claim") or "") == "未认领":
            imgui.separator()
            imgui.text_disabled("同类")
            imgui.text_wrapped("未认领")
        return
    if mode == "card":
        span = fields.get("span")
        if span is not None:
            imgui.separator()
            imgui.text_disabled("覆盖")
            imgui.text(str(fields.get("span_label") or "未打标"))
        detail = str(fields.get("detail") or fields.get("summary") or "")
        if detail:
            imgui.separator()
            imgui.text_disabled("详细设计")
            imgui.text_wrapped(detail)
        if fields.get("message"):
            imgui.separator()
            imgui.text_wrapped(str(fields.get("message")))
        governed = [str(item) for item in fields.get("files") or [] if str(item)]
        imgui.separator()
        if governed:
            imgui.text_disabled(f"治理文件 {len(governed)} 个")
            for rel in governed:
                if _selectable(widget_id(rel, "gov:" + rel)):
                    _focus_path(state, rel, where="详情")
        elif not fields.get("message"):
            imgui.text_wrapped("这张卡还没有落到文件树上的代码文件")
        return
    if fields.get("summary"):
        imgui.text_wrapped(str(fields.get("summary")))
    for key, label in (
        ("who", "谁管理"),
        ("floors", "属于哪几个楼层"),
        ("when", "最近一次提交"),
        ("role", "现在是不是多余的"),
        ("path", "路径"),
    ):
        if not fields.get(key) or fields.get(key) == "—":
            continue
        imgui.separator()
        imgui.text_disabled(label)
        imgui.text_wrapped(str(fields.get(key) or "—"))
