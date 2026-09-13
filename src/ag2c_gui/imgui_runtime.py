"""Extracted by flatten-split."""
from __future__ import annotations
import sys
import time
from pathlib import Path
from .tray_host import DesktopApi, acquire_mutex, preferred_project_root, portable_env, register_app, runtime_command, start_desktop_server, stop_desktop_server, text, wait_for_status, free_port
from .imgui_tray import AUTO_REFRESH_INTERVAL_S, AppState, _before_frame, _gui_overlays, _install_crash_logging, _load_details, _load_fonts, _logged, _post_init, _refresh, _setup_theme, _splits, _status_bar, _windows, audit

def main(argv: list[str] | None = None) -> int:
    _install_crash_logging()
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
    # Native Windows caption: custom-drawn chrome could not match it (tiny hit
    # targets, no snap/system menu). DWM dark-mode keeps the caption on-theme.
    runner.app_window_params.borderless = False
    runner.app_window_params.window_geometry.size = (1280, 860)
    runner.app_window_params.window_geometry.size_auto = False
    runner.app_window_params.window_geometry.window_size_state = hello_imgui.WindowSizeState.standard
    runner.ini_folder_type = hello_imgui.IniFolderType.app_user_config_folder
    runner.ini_filename = "AutoGovern2Code/tray-v16.ini"
    runner.fps_idling.enable_idling = False
    runner.fps_idling.remember_enable_idling = False
    runner.fps_idling.fps_idle = 60.0
    runner.fps_idling.vsync_to_monitor = True
    runner.imgui_window_params.default_imgui_window_type = (
        hello_imgui.DefaultImGuiWindowType.provide_full_screen_dock_space
    )
    # The menu bar only held the custom caption; the native caption replaces it.
    runner.imgui_window_params.show_menu_bar = False
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
    gl_opts = runner.renderer_backend_options.open_gl_options
    gl_opts.anti_aliasing_samples = 4
    runner.renderer_backend_options.open_gl_options = gl_opts
    runner.callbacks.setup_imgui_style = _logged("setup_imgui_style", _setup_theme)
    runner.callbacks.load_additional_fonts = _logged("load_additional_fonts", _load_fonts)
    runner.callbacks.show_status = _logged("show_status", lambda: _status_bar(state))
    runner.callbacks.post_render_dockable_windows = _logged("overlays", lambda: _gui_overlays(state))
    runner.callbacks.post_init = _logged("post_init", lambda: _post_init(state))
    runner.callbacks.before_imgui_render = _logged("before_frame", lambda: _before_frame(state))
    runner.callbacks.before_exit = _logged("before_exit", lambda: _shutdown(state))
    runner.docking_params.layout_condition = hello_imgui.DockingLayoutCondition.application_start
    runner.docking_params.layout_name = "tray-v16"
    runner.docking_params.main_dock_space_node_flags = imgui.DockNodeFlags_.no_undocking
    runner.docking_params.docking_splits = _splits()
    runner.docking_params.dockable_windows = _windows(state)
    # Align/details can take many seconds. Do that off the UI thread so GLFW
    # can show the window immediately instead of waiting for post_init.
    state.run_job(lambda: _start_backend(state))
    hello_imgui.run(runner)
    return 0

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
        state.status = "已连接"
    _load_projects(state)
    with state.lock:
        selected = state.selected_root
        stopping = state.stopping
    if selected:
        _load_details(state, selected, refresh=False)
    if stopping or state.api is None:
        return
    try:
        aligned = state.api.request("POST", "api/projects/align", {})
        migrations = aligned.get("migrations") if isinstance(aligned, dict) else None
        if migrations:
            _load_projects(state)
            with state.lock:
                selected = state.selected_root
            if selected:
                _load_details(state, selected, refresh=False)
    except Exception as exc:
        with state.lock:
            if not state.error:
                state.error = str(exc)
    with state.lock:
        state.loading = False

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
        roots = {text(row, "root") for row in projects}
        if not state.selected_root or state.selected_root not in roots:
            state.selected_root = preferred_project_root(projects)

def _maybe_auto_refresh(state: AppState) -> None:
    """Poll a cheap project digest every few seconds; reload when it changes."""
    if state.api is None or state.stopping:
        return
    now = time.monotonic()
    with state.lock:
        if state.loading or state.busy or now < state.next_poll_at:
            return
        state.next_poll_at = now + AUTO_REFRESH_INTERVAL_S
        root = state.selected_root
    if not root:
        return
    state.run_job(lambda: _poll_digest(state, root))

def _poll_digest(state: AppState, root: str) -> None:
    if state.api is None:
        return
    payload = state.api.request("POST", "api/project/digest", {"path": root})
    digest = str(payload.get("digest") or "")
    guard = payload.get("guard") if isinstance(payload.get("guard"), dict) else {}
    dirty = bool(guard.get("canonicalDirty")) and not guard.get("error")
    open_tasks = int(guard.get("openTasks") or 0)
    if dirty and open_tasks == 0:
        warning = "⚠ canonical 在非任务窗口被修改——可能有改动绕开了治理流程"
    else:
        warning = ""
    with state.lock:
        known = state.digest
        if warning and warning != state.guard_warning:
            audit(state, "看门狗报警", "项目栏", root)
        state.guard_warning = warning
        state.guard = dict(guard)
    if known and digest and digest != known:
        audit(state, "自动刷新", "项目栏", root)
        _load_projects(state)
        _load_details(state, root, refresh=True)
        with state.lock:
            if not state.stopping:
                state.status = "检测到项目变更，已自动刷新"
    with state.lock:
        state.digest = digest
    _poll_notifications(state, root)

def _poll_notifications(state: AppState, root: str) -> None:
    """Check the notification queue for gate blocks and push toasts."""
    try:
        from ag2c.notify import pending_notifications
        from ag2c.config import discover_manifest, load_manifest
        manifest = load_manifest(discover_manifest(Path(root)), project_root=Path(root))
        project_id = manifest.project_id
    except Exception:
        return
    with state.lock:
        state._notify_project_id = project_id
    try:
        items = pending_notifications(project_id)
    except Exception:
        return
    new_items = [item for item in items if item.get("id") not in state._notified_ids]
    if not new_items:
        return
    with state.lock:
        for item in new_items:
            nid = str(item.get("id") or "")
            state._notified_ids.add(nid)
            state.toasts.append({
                "id": nid,
                "kind": str(item.get("kind") or ""),
                "title": str(item.get("title") or ""),
                "detail": str(item.get("detail") or ""),
                "born": time.monotonic(),
                "task_id": str(item.get("task_id") or ""),
                "room_id": str(item.get("room_id") or ""),
            })
        # Cap visible toasts.
        while len(state.toasts) > 5:
            state.toasts.pop(0)
    for item in new_items:
        audit(state, "通知", str(item.get("kind") or ""), str(item.get("title") or ""))

def _add_project(state: AppState, path: str) -> None:
    if state.api is None:
        return
    state.api.request("POST", "api/projects/add", {"path": path})
    _refresh(state)

def _shutdown(state: AppState) -> None:
    with state.lock:
        state.stopping = True
        api = state.api
        process = state.process
    if api is not None or process is not None:
        stop_desktop_server(api, process)
