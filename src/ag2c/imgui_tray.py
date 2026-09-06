"""Dear ImGui / Hello ImGui tray. Uses the MIT docking shell, never 3D add-ons."""

from __future__ import annotations

import os
import sys
import threading
from pathlib import Path
from typing import Any, Callable

from .tray_host import (
    FILTERS,
    DesktopApi,
    acquire_mutex,
    app_directory,
    apply_startup,
    card_for_owner,
    claim_label,
    coverage_rows,
    empty_inspect,
    file_tree_children,
    files_for_card,
    first_flag_label,
    focus_card,
    focus_file,
    inspect_fields,
    is_portable,
    portable_env,
    register_app,
    runtime_command,
    session_token,
    start_desktop_server,
    state_label,
    stop_desktop_server,
    startup_enabled,
    string_list,
    text,
    wait_for_status,
    free_port,
)

# 3D / vision add-ons are not imported.


class AppState:
    def __init__(self, args: list[str]) -> None:
        self.args = args
        self.app_dir = app_directory()
        self.portable = is_portable(args, self.app_dir)
        self.frozen = getattr(sys, "frozen", False)
        self.token = session_token()
        self.api: DesktopApi | None = None
        self.process = None
        self.lock = threading.Lock()
        self.status = "正在启动"
        self.loading = True
        self.error = ""
        self.projects: list[dict[str, Any]] = []
        self.selected_root = ""
        self.details: dict[str, Any] | None = None
        self.inspect: dict[str, Any] = empty_inspect()
        self.inspect_key = ""
        self.selected_file = ""
        self.selected_card_key = ""
        self.highlight_paths: set[str] = set()
        self.force_open: set[str] = set()
        self.scroll_card_key = ""
        self.scroll_file_key = ""
        self.search = ""
        self.filter_index = 0
        self.busy = False
        self._worker: threading.Thread | None = None
        self.really_exit = False
        self._dialog_lock = False
        self.stopping = False

    def clear_focus(self) -> None:
        self.inspect = empty_inspect()
        self.inspect_key = ""
        self.selected_file = ""
        self.selected_card_key = ""
        self.highlight_paths = set()
        self.force_open = set()
        self.scroll_card_key = ""
        self.scroll_file_key = ""

    def apply_focus(self, focused: dict[str, Any]) -> None:
        self.inspect = focused["inspect"]
        self.inspect_key = str(focused["inspect_key"])
        self.selected_file = str(focused["selected_file"])
        self.selected_card_key = str(focused["selected_card_key"])
        self.highlight_paths = set(focused["highlight_paths"])
        self.force_open = set(focused["force_open"])
        self.scroll_card_key = str(focused["scroll_card_key"])
        self.scroll_file_key = str(focused["scroll_file_key"])

    def run_job(self, fn: Callable[[], None]) -> None:
        with self.lock:
            if self._worker is not None and self._worker.is_alive():
                return
            self.busy = True
            self._worker = threading.Thread(target=self._wrap(fn), daemon=True)
            self._worker.start()

    def _wrap(self, fn: Callable[[], None]) -> Callable[[], None]:
        def inner() -> None:
            try:
                fn()
            except Exception as exc:
                with self.lock:
                    self.error = str(exc)
                    self.status = str(exc)
            finally:
                with self.lock:
                    self.busy = False

        return inner


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if any(arg.lower() == "--unregister" for arg in args):
        from .tray_host import unregister_app

        unregister_app()
        return 0
    try:
        from imgui_bundle import hello_imgui, imgui
    except ImportError:
        sys.stderr.write("imgui-bundle is required for the AutoGovern2Code tray. pip install imgui-bundle\n")
        return 2
    mutex = acquire_mutex()
    if mutex is None:
        return 0
    state = AppState(args)
    if not state.portable and state.frozen:
        register_app(sys.executable)

    runner = hello_imgui.RunnerParams()
    runner.app_window_params.window_title = "AutoGovern2Code"
    runner.app_window_params.resizable = True
    runner.app_window_params.restore_previous_geometry = False
    runner.app_window_params.window_geometry.size = (1280, 860)
    runner.app_window_params.window_geometry.size_auto = False
    runner.app_window_params.window_geometry.window_size_state = hello_imgui.WindowSizeState.standard
    runner.ini_folder_type = hello_imgui.IniFolderType.app_user_config_folder
    runner.ini_filename = "AutoGovern2Code/tray.ini"
    runner.fps_idling.enable_idling = False
    runner.fps_idling.remember_enable_idling = False
    runner.fps_idling.vsync_to_monitor = True
    runner.imgui_window_params.default_imgui_window_type = (
        hello_imgui.DefaultImGuiWindowType.provide_full_screen_dock_space
    )
    runner.imgui_window_params.show_menu_bar = True
    runner.imgui_window_params.show_menu_app = False
    runner.imgui_window_params.show_menu_view = False
    runner.imgui_window_params.show_menu_view_themes = False
    runner.imgui_window_params.show_status_bar = True
    runner.imgui_window_params.show_status_fps = False
    runner.imgui_window_params.enable_viewports = False
    runner.imgui_window_params.remember_theme = False
    runner.imgui_window_params.background_color = (0.13, 0.14, 0.16, 1.0)
    runner.imgui_window_params.tweaked_theme.theme = hello_imgui.ImGuiTheme_.photoshop_style
    runner.imgui_window_params.tweaked_theme.tweaks.rounding = 6.0
    runner.callbacks.setup_imgui_style = _setup_theme
    runner.callbacks.load_additional_fonts = _load_fonts
    runner.callbacks.show_menus = lambda: _menus(state)
    runner.callbacks.show_status = lambda: _status_bar(state)
    runner.callbacks.before_imgui_render = _hide_nav_cursor
    runner.callbacks.before_exit = lambda: _shutdown(state)
    runner.docking_params.layout_condition = hello_imgui.DockingLayoutCondition.first_use_ever
    runner.docking_params.docking_splits = _splits()
    runner.docking_params.dockable_windows = _windows(state)
    # Align/details can take many seconds. Do that off the UI thread so GLFW
    # can show the window immediately instead of waiting for post_init.
    state.run_job(lambda: _start_backend(state))
    hello_imgui.run(runner)
    return 0


def _setup_theme() -> None:
    from imgui_bundle import imgui

    # Theme is set on RunnerParams before the first frame. Only patch selection
    # colors here so Hello ImGui does not flash its default style first.
    style = imgui.get_style()
    style.set_color_(int(imgui.Col_.header), (0.28, 0.50, 0.78, 0.55))
    style.set_color_(int(imgui.Col_.header_hovered), (0.0, 0.0, 0.0, 0.0))
    style.set_color_(int(imgui.Col_.header_active), (0.28, 0.50, 0.78, 0.70))
    style.set_color_(int(imgui.Col_.nav_cursor), (0.0, 0.0, 0.0, 0.0))
    io = imgui.get_io()
    io.config_nav_cursor_visible_always = False
    io.config_nav_cursor_visible_auto = False


def _hide_nav_cursor() -> None:
    from imgui_bundle import imgui

    imgui.set_nav_cursor_visible(False)


def widget_id(label: str, key: str) -> str:
    """ImGui ids must stay unique when two rows share a visible title."""
    return f"{label}##{key}"


def node_key(node: dict[str, Any], fallback: str = "") -> str:
    return text(node, "id") or text(node, "path") or fallback


def cjk_font_path() -> Path | None:
    """Windows CJK font used as the Hello ImGui default. Latin-only defaults show tofu."""
    fonts = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    for name in ("msyh.ttc", "msyh.ttf", "msyhbd.ttc", "simhei.ttf", "simsun.ttc"):
        candidate = fonts / name
        if candidate.is_file():
            return candidate
    return None


_FONTS_LOADED = False


def _load_fonts() -> None:
    global _FONTS_LOADED
    from imgui_bundle import hello_imgui

    # Mark loaded before load_font: that call can rebuild the GLFW window and re-enter.
    if _FONTS_LOADED:
        return
    _FONTS_LOADED = True
    cjk = cjk_font_path()
    if cjk is not None:
        params = hello_imgui.FontLoadingParams()
        params.inside_assets = False
        hello_imgui.load_font(str(cjk), 16.0, params)
        try:
            icons = hello_imgui.FontLoadingParams()
            icons.merge_to_last_font = True
            hello_imgui.load_font("fonts/fontawesome-webfont.ttf", 16.0, icons)
        except Exception:
            pass
        return
    hello_imgui.imgui_default_settings.load_default_font_with_font_awesome_icons()


def _splits():
    from imgui_bundle import hello_imgui, imgui

    inspector = hello_imgui.DockingSplit()
    inspector.initial_dock = "MainDockSpace"
    inspector.new_dock = "InspectorSpace"
    inspector.direction = imgui.Dir.right
    inspector.ratio = 0.28
    projects = hello_imgui.DockingSplit()
    projects.initial_dock = "MainDockSpace"
    projects.new_dock = "ProjectSpace"
    projects.direction = imgui.Dir.left
    projects.ratio = 0.22
    cards = hello_imgui.DockingSplit()
    cards.initial_dock = "MainDockSpace"
    cards.new_dock = "CardSpace"
    cards.direction = imgui.Dir.right
    cards.ratio = 0.42
    return [inspector, projects, cards]


def _windows(state: AppState):
    from imgui_bundle import hello_imgui

    def window(label: str, space: str, gui) -> hello_imgui.DockableWindow:
        item = hello_imgui.DockableWindow()
        item.label = label
        item.dock_space_name = space
        item.can_be_closed = False
        item.gui_function = gui
        return item

    return [
        window("项目", "ProjectSpace", lambda: _gui_projects(state)),
        window("文件树", "MainDockSpace", lambda: _gui_tree(state)),
        window("知识卡片", "CardSpace", lambda: _gui_cards(state)),
        window("详情", "InspectorSpace", lambda: _gui_inspect(state)),
    ]


def _menus(state: AppState) -> None:
    from imgui_bundle import hello_imgui, imgui

    if imgui.begin_menu("项目"):
        if imgui.menu_item("添加项目", None, False)[0]:
            _choose_project(state)
        if imgui.menu_item("刷新", None, False, enabled=not state.busy)[0]:
            state.run_job(lambda: _refresh(state))
        imgui.separator()
        if not state.portable and state.frozen:
            enabled = startup_enabled()
            clicked, checked = imgui.menu_item("登录 Windows 后启动", None, enabled)
            if clicked:
                apply_startup(checked, sys.executable)
        if imgui.menu_item("退出", None, False)[0]:
            hello_imgui.get_runner_params().app_shall_exit = True
        imgui.end_menu()


def _status_bar(state: AppState) -> None:
    from imgui_bundle import imgui

    with state.lock:
        status = state.status
        busy = state.busy
        loading = state.loading
    imgui.text(("工作中 · " if busy else "") + ("启动中 · " if loading else "") + status)


def _gui_projects(state: AppState) -> None:
    from imgui_bundle import imgui

    if imgui.button("添加项目") and not state._dialog_lock:
        _choose_project(state)
    imgui.same_line()
    if imgui.button("刷新") and not state.busy:
        state.run_job(lambda: _refresh(state))
    imgui.separator()
    with state.lock:
        rows = list(state.projects)
        selected = state.selected_root
    for row in rows:
        root = text(row, "root")
        label = f"{text(row, 'name')}  ·  {state_label(text(row, 'state'))}"
        clicked, _ = imgui.selectable(widget_id(label, root), selected == root)
        if imgui.is_item_hovered():
            imgui.set_tooltip(root)
        if clicked and root != selected:
            with state.lock:
                state.selected_root = root
                state.clear_focus()
            state.run_job(lambda path=root: _load_details(state, path))


def _all_rows(details: dict[str, Any] | None) -> tuple[list[tuple[str, dict[str, Any]]], list[dict[str, Any]]]:
    files, cards, _headline = coverage_rows(details, "", "")
    return files, cards


def _focus_path(state: AppState, rel: str) -> None:
    with state.lock:
        files, cards = _all_rows(state.details)
        focused = focus_file(files, cards, rel)
        if focused is not None:
            state.apply_focus(focused)


def _focus_card(state: AppState, card: dict[str, Any]) -> None:
    with state.lock:
        files, _cards = _all_rows(state.details)
        state.apply_focus(focus_card(files, card))


def _activate_owner(state: AppState, owner: str) -> None:
    with state.lock:
        files, cards = _all_rows(state.details)
        card = card_for_owner(cards, owner)
        if card is not None:
            state.apply_focus(focus_card(files, card))


def _gui_tree(state: AppState) -> None:
    from imgui_bundle import imgui

    imgui.set_next_item_width(-1)
    changed, value = imgui.input_text_with_hint("##search", "frontend、css、文件名或知识卡", state.search)
    if changed:
        state.search = value
    labels = [label for _, label in FILTERS]
    changed, state.filter_index = imgui.combo("##filter", state.filter_index, labels)
    with state.lock:
        details = state.details
        search = state.search
        selected_file = state.selected_file
        inspect_key = state.inspect_key
        highlight = set(state.highlight_paths)
        force_open = set(state.force_open)
        scroll_file = state.scroll_file_key
        loading = state.loading
        flag = FILTERS[state.filter_index][0] if 0 <= state.filter_index < len(FILTERS) else ""
    all_files, _all_cards = _all_rows(details)
    files, _cards, _headline = coverage_rows(details, search, flag)
    if details is None:
        imgui.text_disabled("选择一个项目后，这里显示谁管理文件、是不是开工或黑盒。")
        return
    if not all_files:
        imgui.text_disabled("启动中 · 正在刷新" if loading else "这个项目还没有可对照的代码文件")
        return
    tree = file_tree_children(files)

    def draw(parent: str, depth: int = 0) -> None:
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
            if kind == "dir" and nested and prefix in force_open:
                imgui.set_next_item_open(True)
            elif kind == "dir" and nested and depth == 0 and not force_open:
                imgui.set_next_item_open(True, imgui.Cond_.once)
            claim = claim_label(node) if kind == "file" else ""
            visible = f"{name}  {claim}" if claim else name
            pushed = 0
            if kin:
                imgui.push_style_color(imgui.Col_.header, (0.28, 0.50, 0.78, 0.32))
                imgui.push_style_color(imgui.Col_.header_hovered, (0.28, 0.50, 0.78, 0.40))
                pushed += 2
            if claim == "未认领":
                imgui.push_style_color(imgui.Col_.text, (0.90, 0.55, 0.38, 1.0))
                pushed += 1
            elif claim == "重复认领":
                imgui.push_style_color(imgui.Col_.text, (0.92, 0.78, 0.35, 1.0))
                pushed += 1
            opened = imgui.tree_node_ex(widget_id(visible, prefix), flags)
            if pushed:
                imgui.pop_style_color(pushed)
            if scroll_file and prefix == scroll_file:
                imgui.set_scroll_here_y(0.25)
                with state.lock:
                    state.scroll_file_key = ""
            if imgui.is_item_clicked():
                if kind == "file":
                    _focus_path(state, prefix)
                else:
                    with state.lock:
                        state.clear_focus()
                        state.inspect = inspect_fields(node)
                        state.inspect_key = key
            if opened:
                if nested:
                    draw(prefix, depth + 1)
                imgui.tree_pop()

    draw("")


def _gui_cards(state: AppState) -> None:
    from imgui_bundle import imgui

    with state.lock:
        details = state.details
        search = state.search
        selected_card = state.selected_card_key
        scroll_card = state.scroll_card_key
        flag = FILTERS[state.filter_index][0] if 0 <= state.filter_index < len(FILTERS) else ""
    all_files, all_cards = _all_rows(details)
    _files, cards, _headline = coverage_rows(details, search, flag)
    if details is not None and not all_cards:
        imgui.text_disabled("还没有知识卡")
        return
    for node in cards:
        title = text(node, "title") or text(node, "id")
        status = first_flag_label(node)
        count = len(files_for_card(all_files, node))
        label = f"{title}  ·  {status} · {count} 个文件" if status else f"{title}  ·  {count} 个文件"
        key = node_key(node, title)
        if imgui.selectable(widget_id(label, key), selected_card == key)[0]:
            _focus_card(state, node)
        if scroll_card and key == scroll_card:
            imgui.set_scroll_here_y(0.25)
            with state.lock:
                state.scroll_card_key = ""


def _gui_inspect(state: AppState) -> None:
    from imgui_bundle import imgui

    with state.lock:
        fields = dict(state.inspect)
        project = next((row for row in state.projects if text(row, "root") == state.selected_root), None)
        error = state.error
    if error:
        imgui.text_colored((0.86, 0.2, 0.2, 1.0), error)
    if project:
        imgui.text_wrapped(text(project, "name"))
        imgui.text_disabled(text(project, "root"))
        imgui.text(state_label(text(project, "state")))
        issues = string_list(project, "issues")
        if issues:
            imgui.text_wrapped("！  " + "；".join(issues))
        governance = text(project, "governance")
        if imgui.button("打开文件夹") and not state._dialog_lock:
            _open_folder(state, text(project, "root"))
        imgui.same_line()
        if imgui.button("重新检查"):
            state.run_job(lambda: _post(state, "api/projects/check", text(project, "root")))
        if governance != "stopped":
            imgui.same_line()
            if imgui.button("停止治理"):
                state.run_job(lambda: _post(state, "api/projects/remove", text(project, "root")))
        else:
            imgui.same_line()
            if imgui.button("恢复治理"):
                state.run_job(lambda: _post(state, "api/projects/resume", text(project, "root")))
        if imgui.button("卸载项目"):
            state.run_job(lambda: _post(state, "api/projects/uninstall", text(project, "root")))
        imgui.separator()
    mode = str(fields.get("mode") or "empty")
    imgui.text_wrapped(str(fields.get("title") or "点文件树或知识卡"))
    if fields.get("path") and mode == "file":
        imgui.text_disabled(str(fields.get("path")))
    if fields.get("status"):
        imgui.text_disabled(str(fields["status"]))
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
            imgui.text_disabled("重复认领")
            for item in related:
                if not isinstance(item, dict):
                    continue
                title = str(item.get("title") or item.get("id") or "")
                if imgui.selectable(widget_id(title, str(item.get("id") or title)))[0]:
                    _activate_owner(state, title)
        peers = [str(item) for item in fields.get("peers") or [] if str(item)]
        if peers:
            imgui.separator()
            imgui.text_disabled(f"同类 {len(peers)} 个文件")
            for rel in peers:
                if imgui.selectable(widget_id(rel, rel), rel == text(fields, "path"))[0]:
                    _focus_path(state, rel)
        elif str(fields.get("claim") or "") == "未认领":
            imgui.separator()
            imgui.text_disabled("同类")
            imgui.text_wrapped("未认领")
        return
    if mode == "card":
        if fields.get("summary"):
            imgui.separator()
            imgui.text_disabled("设计思路")
            imgui.text_wrapped(str(fields.get("summary")))
        governed = [str(item) for item in fields.get("files") or [] if str(item)]
        imgui.separator()
        if governed:
            imgui.text_disabled(f"治理文件 {len(governed)} 个")
            for rel in governed:
                if imgui.selectable(widget_id(rel, "gov:" + rel))[0]:
                    _focus_path(state, rel)
        else:
            imgui.text_wrapped(str(fields.get("message") or "这张卡还没有落到文件树上的代码文件"))
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


def _choose_project(state: AppState) -> None:
    if state._dialog_lock:
        return
    try:
        from imgui_bundle import portable_file_dialogs as pfd
    except Exception:
        return
    state._dialog_lock = True
    try:
        picker = pfd.select_folder("选择要纳入 AutoGovern2Code 治理的 Git 项目")
        if picker is None:
            return
        path = picker.result()
        if not path or state.api is None:
            return
        state.run_job(lambda: _add_project(state, path))
    finally:
        state._dialog_lock = False


def _start_backend(state: AppState) -> None:
    command = runtime_command(state.args, state.app_dir)
    runtime = Path(command[0])
    if runtime.suffix.lower() == ".exe" and not runtime.is_file():
        with state.lock:
            state.error = "找不到 AG2C 治理核心：" + str(runtime)
            state.status = state.error
            state.loading = False
        return
    port = free_port()
    extra = portable_env(state.app_dir) if state.portable else None
    process = start_desktop_server(command, port, state.token, extra)
    api = DesktopApi(f"http://127.0.0.1:{port}/", state.token)
    with state.lock:
        state.process = process
        state.api = api
        stopping = state.stopping
    if stopping:
        return
    if not wait_for_status(api, cancelled=lambda: state.stopping):
        with state.lock:
            if state.stopping:
                return
            state.error = "AG2C 本地服务启动超时。"
            state.status = state.error
            state.loading = False
        return
    with state.lock:
        if state.stopping:
            return
        state.loading = False
        state.status = "已连接"
    _load_projects(state)
    _refresh(state)


def _load_projects(state: AppState) -> None:
    if state.api is None:
        return
    payload = state.api.request("GET", "api/projects")
    rows = payload.get("projects") if isinstance(payload.get("projects"), list) else []
    projects = [row for row in rows if isinstance(row, dict)]
    with state.lock:
        state.projects = projects
        if not state.busy:
            state.status = "还没有治理项目" if not projects else f"已接入 {len(projects)} 个项目"
        elif projects and state.status in {"正在启动", "已连接"}:
            state.status = f"已接入 {len(projects)} 个项目"
        if not state.selected_root and projects:
            state.selected_root = text(projects[0], "root")


def _refresh(state: AppState) -> None:
    if state.api is None:
        return
    with state.lock:
        state.status = "正在刷新"
    state.api.request("POST", "api/projects/align", {})
    _load_projects(state)
    with state.lock:
        selected = state.selected_root
        if not state.stopping:
            state.status = "还没有治理项目" if not state.projects else f"已接入 {len(state.projects)} 个项目"
    if selected:
        _load_details(state, selected)


def _load_details(state: AppState, root: str) -> None:
    if state.api is None:
        return
    payload = state.api.request("POST", "api/project/details", {"path": root})
    with state.lock:
        state.details = payload
        state.clear_focus()
        graph = payload.get("graph") if isinstance(payload.get("graph"), dict) else {}
        headline = graph.get("headline")
        state.inspect = empty_inspect(str(headline) if headline else "")


def _add_project(state: AppState, path: str) -> None:
    if state.api is None:
        return
    state.api.request("POST", "api/projects/add", {"path": path})
    _refresh(state)


def _post(state: AppState, route: str, root: str) -> None:
    if state.api is None:
        return
    state.api.request("POST", route, {"path": root})
    _refresh(state)


def _open_folder(state: AppState, root: str) -> None:
    if state._dialog_lock or not root:
        return
    state._dialog_lock = True
    try:
        if os.name == "nt" and Path(root).is_dir():
            os.startfile(root)  # noqa: S606
    finally:
        state._dialog_lock = False


def _shutdown(state: AppState) -> None:
    with state.lock:
        state.stopping = True
        api = state.api
        process = state.process
    if api is not None or process is not None:
        stop_desktop_server(api, process)
