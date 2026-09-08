"""Dear ImGui / Hello ImGui tray. Uses the MIT docking shell, never 3D add-ons."""

from __future__ import annotations

import faulthandler
import os
import sys
import threading
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from .dashboard import dashboard_model, draw_dashboard
from .tray_host import (
    FILTERS,
    PRODUCT_LABELS,
    WORKTREE_LIFE_LABELS,
    DesktopApi,
    acquire_mutex,
    ancestor_prefixes,
    app_directory,
    card_for_owner,
    card_list_label,
    claim_label,
    coverage_rows,
    empty_inspect,
    file_tree_children,
    files_for_card,
    focus_card,
    focus_file,
    inspect_fields,
    preferred_project_root,
    is_portable,
    issue_label,
    mcp_entry_text,
    mcp_health_snapshot,
    portable_env,
    project_gate_rows,
    register_app,
    row_key,
    runtime_command,
    session_token,
    start_desktop_server,
    state_label,
    stop_desktop_server,
    string_list,
    text,
    wait_for_status,
    free_port,
)
from .tray_caption_win32 import _apply_dark_caption

# 3D / vision add-ons are not imported.

_CRASH_LOG: Any = None


def _crash_log_path() -> Path:
    """Crash log lives under the AG2C data root (portable-aware) or temp dir.

    pythonw has no console, so without this file a tray crash leaves zero
    evidence behind.
    """
    data = os.environ.get("AG2C_DATA_ROOT", "").strip()
    base = Path(data) if data else Path(os.environ.get("TEMP", "."))
    return base / "logs" / "tray-crash.log"


def _log_crash(heading: str) -> None:
    if _CRASH_LOG is None:
        return
    try:
        _CRASH_LOG.write(f"\n=== {heading} {datetime.now().isoformat(timespec='seconds')} ===\n")
        traceback.print_exc(file=_CRASH_LOG)
        _CRASH_LOG.flush()
    except Exception:
        pass


def _logged(label: str, fn: Callable[[], None]) -> Callable[[], None]:
    """Wrap a frame callback so a crash names the callback before dying."""

    def wrapper() -> None:
        try:
            fn()
        except BaseException:
            _log_crash(f"frame callback: {label}")
            raise

    return wrapper


def _install_crash_logging() -> Path:
    """faulthandler + excepthooks into a persistent log file."""
    global _CRASH_LOG
    path = _crash_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    log = open(path, "a", encoding="utf-8", buffering=1)
    from ag2c import __version__

    log.write(
        f"\n=== tray start {datetime.now().isoformat(timespec='seconds')} "
        f"ag2c {__version__} pid {os.getpid()} ===\n"
    )
    log.flush()
    faulthandler.enable(file=log)

    def excepthook(exc_type: Any, exc: BaseException, tb: Any) -> None:
        if _CRASH_LOG is not None:
            try:
                _CRASH_LOG.write(f"\n=== UNCAUGHT {datetime.now().isoformat(timespec='seconds')} ===\n")
                traceback.print_exception(exc_type, exc, tb, file=_CRASH_LOG)
                _CRASH_LOG.flush()
            except Exception:
                pass
        if sys.__excepthook__ is not None and sys.stderr is not None:
            sys.__excepthook__(exc_type, exc, tb)

    def thread_hook(args: threading.ExceptHookArgs) -> None:
        if _CRASH_LOG is not None:
            try:
                _CRASH_LOG.write(f"\n=== THREAD CRASH {datetime.now().isoformat(timespec='seconds')} ===\n")
                traceback.print_exception(args.exc_type, args.exc_value, args.traceback, file=_CRASH_LOG)
                _CRASH_LOG.flush()
            except Exception:
                pass

    sys.excepthook = excepthook
    threading.excepthook = thread_hook
    _CRASH_LOG = log
    return path


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
        self.highlight_card_keys: set[str] = set()
        self.highlight_paths: set[str] = set()
        self.force_open: set[str] = set()
        self.scroll_card_key = ""
        self.scroll_file_key = ""
        self.scroll_file_frames = 0
        self.search = ""
        self.filter_index = 0
        self.busy = False
        self.digest = ""
        self.guard: dict[str, Any] = {}
        self.guard_warning = ""
        self.next_poll_at = 0.0
        self._worker: threading.Thread | None = None
        self._dialog_lock = False
        self.stopping = False
        self.frame_ms: dict[str, float] = {}
        self.rows_from: object | None = None
        self.all_files: list[tuple[str, dict[str, Any]]] = []
        self.all_cards: list[dict[str, Any]] = []
        self.card_file_counts: dict[str, int] = {}
        self.cov_key: tuple[int, str, str] | None = None
        self.cov_files: list[tuple[str, dict[str, Any]]] = []
        self.cov_cards: list[dict[str, Any]] = []
        self.file_tree: dict[str, list[tuple[str, str, str, dict[str, Any]]]] | None = None
        self.tree_files: object | None = None
        self.audit_lines: list[str] = []
        # Drawer visibility lives on the DockableWindow objects (registered in
        # dock_windows by _windows); ops_tab requests which 运维 tab gets focus.
        self.dock_windows: dict[str, Any] = {}
        self.ops_tab = ""
        self.ops_active = ""
        self.panel_fields: dict[str, dict[str, Any]] = {}
        self.toasts: list[dict[str, Any]] = []
        self._notified_ids: set[str] = set()
        self._notify_project_id = ""

    def _live_dock_window(self, label: str) -> Any | None:
        """The C++-side DockableWindow, not the Python original.

        Assigning runner.docking_params.dockable_windows COPIES the structs
        into C++; mutating the registered Python originals at runtime changes
        nothing on screen. get_runner_params() + dockable_window_of_name()
        return the live object (pointer semantics). Falls back to the Python
        original before the runner exists (pre-run calls stay harmless).
        """
        try:
            from imgui_bundle import hello_imgui

            params = hello_imgui.get_runner_params()
            if params is not None:
                window = params.docking_params.dockable_window_of_name(label)
                if window is not None:
                    return window
        except Exception:
            pass
        return self.dock_windows.get(label)

    def dock_visible(self, label: str) -> bool:
        window = self._live_dock_window(label)
        return bool(window is not None and window.is_visible)

    def set_dock_visible(self, label: str, visible: bool) -> None:
        window = self._live_dock_window(label)
        if window is not None:
            window.is_visible = visible

    def toggle_dock(self, label: str) -> bool:
        window = self._live_dock_window(label)
        if window is None:
            return False
        window.is_visible = not window.is_visible
        return bool(window.is_visible)

    def open_ops(self, tab: str) -> None:
        """Open the 运维 drawer focused on one tab (audit / worktrees / records / gate)."""
        self.ops_tab = tab
        self.set_dock_visible("运维", True)

    def clear_focus(self) -> None:
        self.inspect = empty_inspect()
        self.inspect_key = ""
        self.selected_file = ""
        self.selected_card_key = ""
        self.highlight_card_keys = set()
        self.highlight_paths = set()
        self.force_open = set()
        self.scroll_card_key = ""
        self.scroll_file_key = ""
        self.scroll_file_frames = 0
        self.lineage_nav_id = ""
        self.lineage_nav_ids = []

    def apply_focus(self, focused: dict[str, Any]) -> None:
        self.inspect = focused["inspect"]
        self.inspect_key = str(focused["inspect_key"])
        self.selected_file = str(focused["selected_file"])
        self.selected_card_key = str(focused["selected_card_key"])
        self.highlight_card_keys = {str(item) for item in focused.get("highlight_card_keys") or [] if str(item)}
        if not self.highlight_card_keys and self.selected_card_key:
            self.highlight_card_keys = {self.selected_card_key}
        self.highlight_paths = set(focused["highlight_paths"])
        self.force_open = set(focused["force_open"])
        self.scroll_card_key = str(focused["scroll_card_key"])
        self.scroll_file_key = str(focused["scroll_file_key"])
        self.scroll_file_frames = 24 if self.scroll_file_key else 0

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
                    self.error = issue_label(str(exc))
                    self.status = self.error
            finally:
                with self.lock:
                    self.busy = False

        return inner


AUDIT_LIMIT = 800
AUTO_REFRESH_INTERVAL_S = 5.0

# Shared warning amber for gate strips, tree claims, lineage status, and inspect notes.
_WARN_COLOR = (0.92, 0.78, 0.35, 1.0)

# The theme paints header_hovered fully transparent, and ImGui ranks hovered above
# selected when picking a row's frame color — so a selected row under the cursor
# would lose its blue. Selected rows override hover/active to stay visibly blue.
_SELECTED_HOVER_COLOR = (0.28, 0.50, 0.78, 0.62)
_SELECTED_ACTIVE_COLOR = (0.28, 0.50, 0.78, 0.70)


def _audit_log_path() -> Path:
    override = os.environ.get("AG2C_AUDIT_LOG", "").strip()
    if override:
        return Path(override)
    return Path(os.environ.get("TEMP", ".") or ".") / "ag2c-audit.log"


def audit(state: AppState, action: str, where: str, detail: str = "") -> None:
    """Record a user action for debugging. Never called from the per-frame path."""
    frac = time.time()
    stamp = time.strftime("%H:%M:%S", time.localtime(frac)) + f".{int(frac * 1000) % 1000:03d}"
    detail = " ".join(str(detail or "").split())
    if len(detail) > 400:
        detail = detail[:397] + "..."
    line = f"{stamp}  {action}  {where}"
    if detail:
        line += f"  {detail}"
    lines = state.audit_lines
    lines.append(line)
    extra = len(lines) - AUDIT_LIMIT
    if extra > 0:
        del lines[:extra]
    try:
        with _audit_log_path().open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except OSError:
        pass


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
    runner.imgui_window_params.show_status_fps = True
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


def _setup_theme() -> None:
    from imgui_bundle import imgui

    # Theme is set on RunnerParams before the first frame. Only patch selection
    # colors here so Hello ImGui does not flash its default style first.
    style = imgui.get_style()
    style.set_color_(int(imgui.Col_.header), (0.28, 0.50, 0.78, 0.55))
    style.set_color_(int(imgui.Col_.header_hovered), (0.0, 0.0, 0.0, 0.0))
    style.set_color_(int(imgui.Col_.header_active), (0.28, 0.50, 0.78, 0.70))
    style.set_color_(int(imgui.Col_.nav_cursor), (0.0, 0.0, 0.0, 0.0))
    chrome = (0.13, 0.14, 0.16, 1.0)
    style.set_color_(int(imgui.Col_.menu_bar_bg), chrome)
    style.set_color_(int(imgui.Col_.title_bg), chrome)
    style.set_color_(int(imgui.Col_.title_bg_active), chrome)
    style.set_color_(int(imgui.Col_.title_bg_collapsed), chrome)
    style.anti_aliased_lines = True
    style.anti_aliased_fill = True
    # Texture-based 1px AA looks blocky once the node editor zooms the canvas.
    style.anti_aliased_lines_use_tex = False
    style.circle_tessellation_max_error = 0.1
    style.curve_tessellation_tol = 0.25
    io = imgui.get_io()
    if hasattr(io, "config_dpi_scale_fonts"):
        io.config_dpi_scale_fonts = True
    io.config_nav_cursor_visible_always = False
    io.config_nav_cursor_visible_auto = False


def _hide_nav_cursor() -> None:
    from imgui_bundle import imgui

    imgui.set_nav_cursor_visible(False)


def _before_frame(state: AppState) -> None:
    _hide_nav_cursor()
    t0 = time.perf_counter()
    _apply_dark_caption()
    state.frame_ms["DWM"] = (time.perf_counter() - t0) * 1000.0
    _maybe_auto_refresh(state)


def _post_init(state: AppState) -> None:
    _apply_dark_caption()


def widget_id(label: str, key: str) -> str:
    """ImGui ids must stay unique when two rows share a visible title."""
    return f"{label}##{key}"


def _selectable(label: str, selected: bool = False) -> bool:
    from imgui_bundle import imgui

    if not selected:
        clicked, _checked = imgui.selectable(label, selected)
        return bool(clicked)
    imgui.push_style_color(imgui.Col_.header_hovered, _SELECTED_HOVER_COLOR)
    imgui.push_style_color(imgui.Col_.header_active, _SELECTED_ACTIVE_COLOR)
    try:
        clicked, _checked = imgui.selectable(label, selected)
    finally:
        imgui.pop_style_color(2)
    return bool(clicked)


def _guarded(state: AppState, label: str, fn: Callable[[], None]) -> None:
    t0 = time.perf_counter()
    try:
        fn()
    except Exception as exc:
        with state.lock:
            state.error = f"{label}: {exc}"
    finally:
        state.frame_ms[label] = (time.perf_counter() - t0) * 1000.0


node_key = row_key  # Backward-compatible alias; the canonical helper lives in tray_host.


def cjk_font_path() -> Path | None:
    """Windows CJK font used as the Hello ImGui default. Latin-only defaults show tofu."""
    fonts = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    for name in ("msyh.ttc", "msyh.ttf", "msyhbd.ttc", "simhei.ttf", "simsun.ttc"):
        candidate = fonts / name
        if candidate.is_file():
            return candidate
    return None


_FONTS_LOADED = False


def _font_raster_density() -> float:
    """Rasterize glyphs denser than 1x so node-editor zoom stays readable."""
    from imgui_bundle import hello_imgui, imgui

    density = 2.0
    try:
        scale = float(imgui.get_io().display_framebuffer_scale.x or 1.0)
        density = max(density, scale)
    except Exception:
        pass
    try:
        dpi = float(hello_imgui.dpi_window_size_factor() or 0.0)
        if dpi > 1.0:
            density = max(density, dpi)
    except Exception:
        pass
    return min(2.5, density)


def _load_fonts() -> None:
    global _FONTS_LOADED
    from imgui_bundle import hello_imgui

    # Mark loaded before load_font: that call can rebuild the GLFW window and re-enter.
    if _FONTS_LOADED:
        return
    _FONTS_LOADED = True
    cjk = cjk_font_path()
    density = _font_raster_density()
    if cjk is not None:
        params = hello_imgui.FontLoadingParams()
        params.inside_assets = False
        cfg = getattr(params, "font_config", None)
        if cfg is not None:
            cfg.rasterizer_density = density
            cfg.oversample_h = 2
            cfg.oversample_v = 1
        hello_imgui.load_font(str(cjk), 16.0, params)
        try:
            icons = hello_imgui.FontLoadingParams()
            icons.merge_to_last_font = True
            icon_cfg = getattr(icons, "font_config", None)
            if icon_cfg is not None:
                icon_cfg.rasterizer_density = density
            hello_imgui.load_font("fonts/fontawesome-webfont.ttf", 16.0, icons)
        except Exception:
            pass
        return
    hello_imgui.imgui_default_settings.load_default_font_with_font_awesome_icons()


def _splits():
    from imgui_bundle import hello_imgui, imgui

    lock = imgui.DockNodeFlags_.no_undocking
    def split(initial: str, name: str, direction, ratio: float, flags=lock) -> hello_imgui.DockingSplit:
        item = hello_imgui.DockingSplit()
        item.initial_dock = initial
        item.new_dock = name
        item.direction = direction
        item.ratio = ratio
        item.node_flags = flags
        return item

    return [
        split("MainDockSpace", "FileTreeSpace", imgui.Dir.left, 0.42),
        split("MainDockSpace", "InspectorSpace", imgui.Dir.right, 0.32),
        split("MainDockSpace", "OpsSpace", imgui.Dir.down, 0.30),
    ]


def _windows(state: AppState):
    """Dashboard-first orchestration: 首页 owns the stage; 文件树 is a same-space tab, drawers hidden."""
    from imgui_bundle import hello_imgui, imgui

    def window(label: str, space: str, gui, *, closable: bool) -> hello_imgui.DockableWindow:
        item = hello_imgui.DockableWindow()
        item.label = label
        item.dock_space_name = space
        item.can_be_closed = closable
        item.remember_is_visible = closable
        item.is_visible = not closable
        item.imgui_window_flags = imgui.WindowFlags_.no_collapse
        item.gui_function = gui
        state.dock_windows[label] = item
        return item

    return [
        window("首页", "MainDockSpace", lambda: _guarded(state, "首页", lambda: _gui_dashboard(state)), closable=False),
        window("文件树", "FileTreeSpace", lambda: _guarded(state, "文件树", lambda: _gui_tree(state)), closable=True),
        window("检查器", "InspectorSpace", lambda: _guarded(state, "检查器", lambda: _gui_inspector(state)), closable=True),
        window("运维", "OpsSpace", lambda: _guarded(state, "运维", lambda: _gui_ops(state)), closable=True),
    ]


def _gui_dashboard(state: AppState) -> None:
    """模式一·首页：当前任务 + 异常清单 + 健康度。装配在 dashboard.py（纯函数）。"""
    with state.lock:
        details = state.details
        guard = dict(state.guard)
    model = dashboard_model(details, guard)
    draw_dashboard(model)
    _gui_audit_pending(state, model)


def _gui_audit_pending(state: AppState, model: dict[str, Any]) -> None:
    """随机抽查待办：条目只出现在这个用户侧界面；确认走桌面端，不经 MCP。"""
    from imgui_bundle import imgui

    audit_info = model.get("audit") if isinstance(model.get("audit"), dict) else {}
    pending = audit_info.get("pending") or []
    if not pending:
        return
    imgui.separator()
    imgui.text_colored((1.0, 0.6, 0.2, 1.0), "随机抽查（人工核对后确认）")
    for item in pending:
        imgui.bullet_text(f"{text(item, 'id')} — {text(item, 'question')}")
    if imgui.small_button("已抽查"):
        with state.lock:
            project = state.details.get("project") if isinstance(state.details, dict) else {}
        audit(state, "已抽查", "首页", text(project, "root"))
        state.run_job(lambda: _post(state, "api/project/audit-ack", text(project, "root")))
        _refresh(state)


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
    io = imgui.get_io()
    fps = float(getattr(io, "framerate", 0.0) or 0.0)
    dt = float(getattr(io, "delta_time", 0.0) or 0.0) * 1000.0
    parts = []
    for key in ("首页", "文件树", "详情", "知识卡片", "DWM"):
        ms = state.frame_ms.get(key)
        if ms is not None:
            parts.append(f"{key} {ms:.1f}")
    meter = f"{fps:.0f} fps  {dt:.1f} ms"
    if parts:
        meter += "  ·  " + "  ".join(parts)
    drawer_labels = ("文件树", "检查器", "运维")
    btn_w = sum(float(imgui.calc_text_size(label).x) + 18.0 for label in drawer_labels) + 8.0 * (len(drawer_labels) - 1)
    meter_w = float(imgui.calc_text_size(meter).x)
    width = float(imgui.get_window_width())
    avail_meter = width - meter_w - 16.0
    avail_btn = avail_meter - btn_w - 10.0
    if avail_btn > float(imgui.get_cursor_pos_x()) + 24.0:
        imgui.same_line(avail_btn)
    else:
        imgui.same_line()
    for label in drawer_labels:
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
        imgui.same_line()
    if avail_meter > float(imgui.get_cursor_pos_x()) + 8.0:
        imgui.same_line(avail_meter)
    else:
        imgui.same_line()
    imgui.text_disabled(meter)


def _gui_overlays(state: AppState) -> None:
    """Splash + toast notifications float above the dock layout."""
    _gui_splash(state)
    _gui_toasts(state)


_TOAST_TTL_S = 8.0
_TOAST_WIDTH = 360.0


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


_OPS_TABS = (("audit", "操作日志"), ("worktrees", "施工"), ("records", "实际记录"), ("gate", "AI 入口"))


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


GATE_BUTTON_LABELS = {"gate": "MCP 链接", "records": "实际记录", "worktrees": "施工"}


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


def _copy_mcp_entry() -> str:
    from imgui_bundle import imgui

    prompt = mcp_entry_text()
    try:
        imgui.set_clipboard_text(prompt)
    except Exception:
        pass
    return prompt


PANEL_TITLES = {"gate": "MCP 链接", "records": "实际记录", "worktrees": "施工"}


def _refresh_panel(
    state: AppState,
    kind: str,
    project: dict[str, Any],
    details: dict[str, Any] | None,
) -> None:
    """Rebuild a floating panel's fields from the current project row and details."""
    agents = [item for item in (project.get("agents") or []) if isinstance(item, dict)]
    last = project.get("last_task") if isinstance(project.get("last_task"), dict) else None
    worktrees = [item for item in ((details or {}).get("worktrees") or []) if isinstance(item, dict)]
    health = None
    prompt = ""
    if kind == "gate":
        health = mcp_health_snapshot(
            handshake=False,
            cwd=text(project, "root") or None,
            managed=bool(project.get("delivery_enforced")) if "delivery_enforced" in project else None,
        )
        prompt = mcp_entry_text()
    journal: list[dict[str, Any]] = []
    if kind == "records":
        try:
            from ag2c.journal import list_journals

            journal = [item for item in reversed(list_journals(Path(text(project, "root")))) if isinstance(item, dict)]
        except Exception:
            journal = []
    with state.lock:
        state.panel_fields[kind] = {
            "title": PANEL_TITLES.get(kind, kind),
            "status": str((health or {}).get("label") or "") if kind == "gate" else "",
            "path": text(project, "root"),
            "prompt": prompt,
            "mcp_health": health or {},
            "agents": agents,
            "entry_ready": bool(project.get("entry_ready")),
            "delivery_enforced": bool(project.get("delivery_enforced")),
            "completed_tasks": int(project.get("completed_tasks") or 0),
            "last_task": last,
            "product": project.get("product"),
            "worktrees": worktrees,
            "open_tasks": int(project.get("open_tasks") or 0),
            "journal": journal,
        }


def _refresh_open_panels(state: AppState) -> None:
    """Keep the 运维 drawer's tabs in sync after a details reload."""
    if not state.dock_visible("运维"):
        return
    with state.lock:
        root = state.selected_root
        details = state.details
        project = next((row for row in state.projects if text(row, "root") == root), None)
    if project is None:
        return
    for kind, _title in _OPS_TABS:
        if kind == "audit":
            continue
        _refresh_panel(state, kind, project, details)


def _all_rows(details: dict[str, Any] | None) -> tuple[list[tuple[str, dict[str, Any]]], list[dict[str, Any]]]:
    files, cards, _headline = coverage_rows(details, "", "")
    return files, cards


def _cached_all_rows(state: AppState, details: dict[str, Any] | None) -> tuple[list[tuple[str, dict[str, Any]]], list[dict[str, Any]]]:
    if details is None:
        state.rows_from = None
        return [], []
    if state.rows_from is details:
        return state.all_files, state.all_cards
    files, cards = _all_rows(details)
    counts: dict[str, int] = {}
    for card in cards:
        key = node_key(card, text(card, "title"))
        counts[key] = len(files_for_card(files, card))
    state.rows_from = details
    state.all_files = files
    state.all_cards = cards
    state.card_file_counts = counts
    state.cov_key = None
    state.file_tree = None
    return files, cards


def _cached_coverage(
    state: AppState, details: dict[str, Any] | None, search: str, flag: str
) -> tuple[list[tuple[str, dict[str, Any]]], list[dict[str, Any]]]:
    files, cards = _cached_all_rows(state, details)
    if not search and not flag:
        return files, cards
    key = (id(details), search, flag)
    if state.cov_key == key:
        return state.cov_files, state.cov_cards
    cov_files, cov_cards, _headline = coverage_rows(details, search, flag)
    state.cov_key = key
    state.cov_files = cov_files
    state.cov_cards = cov_cards
    state.file_tree = None
    return cov_files, cov_cards


def _cached_tree(state: AppState, files: list[tuple[str, dict[str, Any]]]):
    if state.file_tree is not None and state.tree_files is files:
        return state.file_tree
    state.file_tree = file_tree_children(files)
    state.tree_files = files
    return state.file_tree


def _focus_path(state: AppState, rel: str, *, where: str = "文件树") -> None:
    audit(state, "点击文件", where, rel)
    with state.lock:
        files, cards = _all_rows(state.details)
        focused = focus_file(files, cards, rel)
        if focused is not None:
            state.apply_focus(focused)
        else:
            audit(state, "未命中文件", where, rel)


def _focus_card(state: AppState, card: dict[str, Any], *, where: str = "知识卡片") -> None:
    title = text(card, "title") or text(card, "id")
    audit(state, "点击知识卡", where, title)
    with state.lock:
        previous_key = state.selected_card_key
        files, _cards = _all_rows(state.details)
        state.apply_focus(focus_card(files, card))
        # Selecting a card summons the inspector drawer; a repeated click on the
        # same card does not reopen it after the user closed it.
        if state.selected_card_key and state.selected_card_key != previous_key:
            state.set_dock_visible("检查器", True)


def _activate_owner(state: AppState, owner: str, *, where: str = "详情") -> None:
    audit(state, "点击知识卡", where, owner)
    with state.lock:
        files, cards = _all_rows(state.details)
        card = card_for_owner(cards, owner)
        if card is not None:
            state.apply_focus(focus_card(files, card))
        else:
            audit(state, "未命中知识卡", where, owner)


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
                elif depth == 0:
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


def _clip_label(value: str, max_px: float) -> str:
    text_value = str(value or "").replace("\n", " ")

    def width(text: str) -> float:
        return sum(16.0 if ord(char) > 127 else 8.5 for char in text)

    if width(text_value) <= max_px:
        return text_value
    out = ""
    for char in text_value:
        if width(out + char) > max_px:
            return out + "…"
        out += char
    return text_value


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


def _combo_marker_hit(hx: float, hy: float) -> tuple[float, float, float, float]:
    return (hx + 4.0, hy + 6.0, 22.0, 22.0)


def _point_in_rect(px: float, py: float, x: float, y: float, w: float, h: float) -> bool:
    return x <= px <= x + w and y <= py <= y + h


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
        audit(state, "选定项目", "项目栏", path)
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


def _refresh(state: AppState) -> None:
    if state.api is None:
        return
    with state.lock:
        state.loading = True
        state.status = "正在重新扫描…"
    try:
        state.api.request("POST", "api/projects/align", {})
        _load_projects(state)
        with state.lock:
            selected = state.selected_root
        if selected:
            _load_details(state, selected, refresh=True)
        with state.lock:
            if not state.stopping:
                state.status = "还没有治理项目" if not state.projects else f"已接入 {len(state.projects)} 个项目"
    finally:
        with state.lock:
            state.loading = False


def _load_details(state: AppState, root: str, *, refresh: bool = False) -> None:
    if state.api is None:
        return
    payload = state.api.request("POST", "api/project/details", {"path": root, "refresh": refresh})
    with state.lock:
        state.details = payload
        state.error = ""
        state.clear_focus()
        graph = payload.get("graph") if isinstance(payload.get("graph"), dict) else {}
        headline = graph.get("headline")
        state.inspect = empty_inspect(str(headline) if headline else "")
    _refresh_open_panels(state)


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
