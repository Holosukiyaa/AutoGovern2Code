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
    coverage_rows,
    first_flag_label,
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
        self.inspect: dict[str, str] = {}
        self.search = ""
        self.filter_index = 0
        self.busy = False
        self._worker: threading.Thread | None = None
        self.really_exit = False

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
    runner.app_window_params.window_geometry.size = (1280, 860)
    runner.app_window_params.restore_previous_geometry = True
    runner.ini_folder_type = hello_imgui.IniFolderType.app_user_config_folder
    runner.ini_filename = "AutoGovern2Code/imgui.ini"
    runner.fps_idling.enable_idling = True
    runner.imgui_window_params.default_imgui_window_type = (
        hello_imgui.DefaultImGuiWindowType.provide_full_screen_dock_space
    )
    runner.imgui_window_params.show_menu_bar = True
    runner.imgui_window_params.show_menu_app = False
    runner.imgui_window_params.show_menu_view = True
    runner.imgui_window_params.show_status_bar = True
    runner.imgui_window_params.enable_viewports = False
    runner.callbacks.setup_imgui_style = _setup_theme
    runner.callbacks.load_additional_fonts = _load_fonts
    runner.callbacks.show_menus = lambda: _menus(state)
    runner.callbacks.show_status = lambda: _status_bar(state)
    runner.callbacks.post_init = lambda: state.run_job(lambda: _start_backend(state))
    runner.callbacks.before_exit = lambda: _shutdown(state)
    runner.docking_params.layout_condition = hello_imgui.DockingLayoutCondition.application_start
    runner.docking_params.docking_splits = _splits()
    runner.docking_params.dockable_windows = _windows(state)
    hello_imgui.run(runner)
    return 0


def _setup_theme() -> None:
    from imgui_bundle import hello_imgui

    hello_imgui.imgui_default_settings.setup_default_imgui_style()
    theme = hello_imgui.ImGuiTweakedTheme()
    theme.theme = hello_imgui.ImGuiTheme_.photoshop_style
    theme.tweaks.rounding = 6.0
    hello_imgui.apply_tweaked_theme(theme)


def cjk_font_path() -> Path | None:
    """Windows CJK font used as the Hello ImGui default. Latin-only defaults show tofu."""
    fonts = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    for name in ("msyh.ttc", "msyh.ttf", "msyhbd.ttc", "simhei.ttf", "simsun.ttc"):
        candidate = fonts / name
        if candidate.is_file():
            return candidate
    return None


def _load_fonts() -> None:
    from imgui_bundle import hello_imgui

    # Hello ImGui's bundled DroidSans/Roboto have no CJK. Load YaHei (or SimSun) first so
    # it becomes fonts[0]. FontLoadingParams.inside_assets defaults True and would look
    # for msyh.ttc inside the demo assets, not C:\Windows\Fonts.
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
    hello_imgui.show_view_menu(hello_imgui.get_runner_params())


def _status_bar(state: AppState) -> None:
    from imgui_bundle import imgui

    with state.lock:
        status = state.status
        busy = state.busy
        loading = state.loading
    imgui.text(("工作中 · " if busy else "") + ("启动中 · " if loading else "") + status)


def _gui_projects(state: AppState) -> None:
    from imgui_bundle import imgui

    if imgui.button("添加项目"):
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
        clicked, _ = imgui.selectable(label, selected == root)
        if imgui.is_item_hovered():
            imgui.set_tooltip(root)
        if clicked and root != selected:
            with state.lock:
                state.selected_root = root
            state.run_job(lambda path=root: _load_details(state, path))


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
        flag = FILTERS[state.filter_index][0] if 0 <= state.filter_index < len(FILTERS) else ""
    files, _cards, _headline = coverage_rows(details, search, flag)
    folders: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    tops: dict[str, dict[str, Any]] = {}
    for rel, node in files:
        parts = rel.split("/")
        tops.setdefault(parts[0], node if len(parts) == 1 else {"title": parts[0], "path": parts[0]})
        if len(parts) > 1:
            parent = "/".join(parts[:-1])
            folders.setdefault(parent, []).append((rel, node))

    def draw(prefix: str, node: dict[str, Any], name: str) -> None:
        children = folders.get(prefix, [])
        flags = imgui.TreeNodeFlags_.leaf if not children else imgui.TreeNodeFlags_.open_on_arrow
        opened = imgui.tree_node_ex(f"{name}##{prefix}", flags)
        if imgui.is_item_clicked():
            with state.lock:
                state.inspect = inspect_fields(node)
        if opened:
            for child_rel, child in children:
                draw(child_rel, child, child_rel.rsplit("/", 1)[-1])
            imgui.tree_pop()

    for name, node in tops.items():
        draw(name, node, name)


def _gui_cards(state: AppState) -> None:
    from imgui_bundle import imgui

    with state.lock:
        details = state.details
        search = state.search
        flag = FILTERS[state.filter_index][0] if 0 <= state.filter_index < len(FILTERS) else ""
    _files, cards, _headline = coverage_rows(details, search, flag)
    for node in cards:
        title = text(node, "title") or text(node, "id")
        status = first_flag_label(node)
        label = title if not status else f"{title}  ·  {status}"
        if imgui.selectable(label, False)[0]:
            with state.lock:
                state.inspect = inspect_fields(node)


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
        if imgui.button("打开文件夹"):
            _open_folder(text(project, "root"))
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
    imgui.text_wrapped(fields.get("title") or "点文件树或知识卡")
    if fields.get("status"):
        imgui.text_disabled(fields["status"])
    if fields.get("summary"):
        imgui.text_wrapped(fields["summary"])
    for key, label in (
        ("who", "谁管理"),
        ("floors", "属于哪几个楼层"),
        ("when", "最近一次提交"),
        ("role", "现在是不是多余的"),
        ("path", "路径"),
    ):
        imgui.separator()
        imgui.text_disabled(label)
        imgui.text_wrapped(fields.get(key) or "—")


def _choose_project(state: AppState) -> None:
    try:
        from imgui_bundle import portable_file_dialogs as pfd
    except Exception:
        return
    picker = pfd.select_folder("选择要纳入 AutoGovern2Code 治理的 Git 项目")
    if picker is None:
        return
    path = picker.result()
    if not path or state.api is None:
        return
    state.run_job(lambda: _add_project(state, path))


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
    state.process = start_desktop_server(command, port, state.token, extra)
    state.api = DesktopApi(f"http://127.0.0.1:{port}/", state.token)
    if not wait_for_status(state.api):
        with state.lock:
            state.error = "AG2C 本地服务启动超时。"
            state.status = state.error
            state.loading = False
        return
    with state.lock:
        state.loading = False
        state.status = "已连接"
    _refresh(state)


def _refresh(state: AppState) -> None:
    if state.api is None:
        return
    with state.lock:
        state.status = "正在刷新"
    state.api.request("POST", "api/projects/align", {})
    payload = state.api.request("GET", "api/projects")
    rows = payload.get("projects") if isinstance(payload.get("projects"), list) else []
    projects = [row for row in rows if isinstance(row, dict)]
    with state.lock:
        state.projects = projects
        state.status = "还没有治理项目" if not projects else f"已接入 {len(projects)} 个项目"
        if not state.selected_root and projects:
            state.selected_root = text(projects[0], "root")
        selected = state.selected_root
    if selected:
        _load_details(state, selected)


def _load_details(state: AppState, root: str) -> None:
    if state.api is None:
        return
    payload = state.api.request("POST", "api/project/details", {"path": root})
    with state.lock:
        state.details = payload
        graph = payload.get("graph") if isinstance(payload.get("graph"), dict) else {}
        headline = graph.get("headline")
        state.inspect = {
            "title": "点文件树或知识卡",
            "status": str(headline) if headline else "点文件树或知识卡查看归属。",
            "summary": "",
            "who": "—",
            "floors": "—",
            "when": "—",
            "role": "—",
            "path": "—",
        }


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


def _open_folder(root: str) -> None:
    if os.name == "nt" and root and Path(root).is_dir():
        os.startfile(root)  # noqa: S606


def _shutdown(state: AppState) -> None:
    if state.api is not None:
        stop_desktop_server(state.api, state.process)
