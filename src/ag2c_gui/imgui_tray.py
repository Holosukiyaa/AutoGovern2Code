"""Dear ImGui / Hello ImGui tray. Uses the MIT docking shell, never 3D add-ons."""

from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable

from .graph import (
    LINEAGE_CARD_W,
    LINEAGE_PROJECT_ID,
    build_lineage,
    layout_lineage_view,
    lineage_heading,
    lineage_related_ids,
    lineage_uid,
)
from .tray_host import (
    FILTERS,
    PRODUCT_LABELS,
    WORKTREE_LIFE_LABELS,
    DesktopApi,
    acquire_mutex,
    ancestor_prefixes,
    app_directory,
    apply_startup,
    card_for_owner,
    card_list_label,
    card_matching_lineage,
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
    lineage_subtitle,
    mcp_entry_text,
    mcp_health_snapshot,
    portable_env,
    project_gate_rows,
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
        self.highlight_card_keys: set[str] = set()
        self.highlight_paths: set[str] = set()
        self.force_open: set[str] = set()
        self.scroll_card_key = ""
        self.scroll_file_key = ""
        self.scroll_file_frames = 0
        self.search = ""
        self.filter_index = 0
        self.busy = False
        self._worker: threading.Thread | None = None
        self.really_exit = False
        self._dialog_lock = False
        self.stopping = False
        self.lineage_editor = None
        self.lineage_fit = True
        self.lineage_fit_frames = 24
        self.lineage_nav_id = ""
        self.lineage_nav_ids: list[str] = []
        self.lineage_cache: dict[str, Any] | None = None
        self.lineage_cache_from: object | None = None
        self.lineage_placed = False
        self.lineage_view: list[dict[str, Any]] | None = None
        self.lineage_layout_key: frozenset[str] | None = None
        self.lineage_expanded: set[str] = {LINEAGE_PROJECT_ID}
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
        self.audit_open = False

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
        nav_ids = [str(item) for item in focused.get("lineage_nav_ids") or [] if str(item)]
        nav_id = str(focused.get("lineage_nav_id") or focused.get("selected_card_key") or "")
        if not nav_ids and nav_id:
            nav_ids = [nav_id]
        self.lineage_nav_ids = nav_ids
        self.lineage_nav_id = nav_ids[0] if nav_ids else ""

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
    runner.app_window_params.borderless = True
    runner.app_window_params.borderless_movable = False
    runner.app_window_params.borderless_resizable = True
    runner.app_window_params.borderless_closable = False
    runner.app_window_params.borderless_highlight_color = (0.13, 0.14, 0.16, 1.0)
    runner.app_window_params.window_geometry.size = (1280, 860)
    runner.app_window_params.window_geometry.size_auto = False
    runner.app_window_params.window_geometry.window_size_state = hello_imgui.WindowSizeState.standard
    runner.ini_folder_type = hello_imgui.IniFolderType.app_user_config_folder
    runner.ini_filename = "AutoGovern2Code/tray-v14.ini"
    runner.fps_idling.enable_idling = False
    runner.fps_idling.remember_enable_idling = False
    runner.fps_idling.fps_idle = 60.0
    runner.fps_idling.vsync_to_monitor = True
    runner.imgui_window_params.default_imgui_window_type = (
        hello_imgui.DefaultImGuiWindowType.provide_full_screen_dock_space
    )
    runner.imgui_window_params.show_menu_bar = True
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
    runner.callbacks.setup_imgui_style = _setup_theme
    runner.callbacks.load_additional_fonts = _load_fonts
    runner.callbacks.show_menus = lambda: _guarded(state, "菜单", lambda: _menus(state))
    runner.callbacks.show_status = lambda: _status_bar(state)
    runner.callbacks.post_render_dockable_windows = lambda: _gui_audit(state)
    runner.callbacks.post_init = lambda: _post_init(state)
    runner.callbacks.before_imgui_render = lambda: _before_frame(state)
    runner.callbacks.before_exit = lambda: _shutdown(state)
    runner.docking_params.layout_condition = hello_imgui.DockingLayoutCondition.application_start
    runner.docking_params.layout_name = "tray-v14"
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


def _post_init(state: AppState) -> None:
    _apply_dark_caption()
    try:
        _ensure_lineage_editor(state)
    except Exception as exc:
        with state.lock:
            state.error = f"谱系: {exc}"


def _ensure_lineage_editor(state: AppState) -> None:
    if state.lineage_editor is not None:
        return
    from imgui_bundle import imgui_node_editor as ed

    from imgui_bundle import imgui

    config = ed.Config()
    config.settings_file = ""
    config.enable_smooth_zoom = False
    config.canvas_size_mode = ed.CanvasSizeMode.center_only
    config.drag_button_index = 2
    config.select_button_index = 2
    state.lineage_editor = ed.create_editor(config)
    try:
        ed.set_current_editor(state.lineage_editor)
        style = ed.get_style()
        style.node_padding = imgui.ImVec4(6.0, 5.0, 6.0, 5.0)
        style.node_rounding = 6.0
        style.node_border_width = 1.25
        style.selected_node_border_width = 0.0
    except Exception:
        pass


def _destroy_lineage_editor(state: AppState) -> None:
    if state.lineage_editor is None:
        return
    from imgui_bundle import imgui_node_editor as ed

    ed.destroy_editor(state.lineage_editor)
    state.lineage_editor = None


_CAPTION_HWND = 0
_CAPTION_API = None
_GLFW_DLL = None


def _caption_api():
    """Win32 handles must be pointer-sized; ctypes defaults truncate HWND on x64."""
    global _CAPTION_API
    if _CAPTION_API is not None:
        return _CAPTION_API
    import ctypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    dwmapi = ctypes.WinDLL("dwmapi", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    user32.FindWindowW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
    user32.FindWindowW.restype = ctypes.c_void_p
    user32.GetActiveWindow.restype = ctypes.c_void_p
    user32.GetWindowTextW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
    user32.GetWindowTextW.restype = ctypes.c_int
    user32.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
    user32.GetWindowThreadProcessId.restype = ctypes.c_ulong
    user32.IsWindowVisible.argtypes = [ctypes.c_void_p]
    user32.IsWindowVisible.restype = ctypes.c_int
    user32.IsWindow.argtypes = [ctypes.c_void_p]
    user32.IsWindow.restype = ctypes.c_int
    user32.SetWindowPos.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_uint,
    ]
    user32.SetWindowPos.restype = ctypes.c_int
    user32.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
    user32.ShowWindow.restype = ctypes.c_int
    user32.IsZoomed.argtypes = [ctypes.c_void_p]
    user32.IsZoomed.restype = ctypes.c_int
    user32.ReleaseCapture.restype = ctypes.c_int
    user32.SendMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_size_t]
    user32.SendMessageW.restype = ctypes.c_ssize_t
    dwmapi.DwmSetWindowAttribute.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_uint]
    dwmapi.DwmSetWindowAttribute.restype = ctypes.c_long
    kernel32.GetCurrentProcessId.restype = ctypes.c_ulong
    _CAPTION_API = (ctypes, user32, dwmapi, kernel32)
    return _CAPTION_API


def _glfw_dll(ctypes_mod):
    global _GLFW_DLL
    if _GLFW_DLL is not None:
        return _GLFW_DLL
    import imgui_bundle

    dll = ctypes_mod.WinDLL(str(Path(imgui_bundle.__file__).resolve().parent / "glfw3.dll"))
    dll.glfwGetWin32Window.argtypes = [ctypes_mod.c_void_p]
    dll.glfwGetWin32Window.restype = ctypes_mod.c_void_p
    dll.glfwMaximizeWindow.argtypes = [ctypes_mod.c_void_p]
    dll.glfwRestoreWindow.argtypes = [ctypes_mod.c_void_p]
    dll.glfwGetWindowAttrib.argtypes = [ctypes_mod.c_void_p, ctypes_mod.c_int]
    dll.glfwGetWindowAttrib.restype = ctypes_mod.c_int
    _GLFW_DLL = dll
    return dll


def _glfw_hwnd(ctypes_mod) -> int:
    """HWND of the running Hello ImGui GLFW window, if the backend is up."""
    try:
        from imgui_bundle import hello_imgui

        addr = int(hello_imgui.get_glfw_window_address() or 0)
        if not addr:
            return 0
        return int(_glfw_dll(ctypes_mod).glfwGetWin32Window(addr) or 0)
    except Exception:
        return 0


def _enum_tray_hwnd(ctypes_mod, user32, kernel32) -> int:
    pid = int(kernel32.GetCurrentProcessId())
    found = ctypes_mod.c_void_p(0)
    enum_proc = ctypes_mod.WINFUNCTYPE(ctypes_mod.c_int, ctypes_mod.c_void_p, ctypes_mod.c_void_p)

    def callback(hwnd, _lparam):
        proc = ctypes_mod.c_ulong(0)
        user32.GetWindowThreadProcessId(hwnd, ctypes_mod.byref(proc))
        if int(proc.value) != pid or not user32.IsWindowVisible(hwnd):
            return 1
        buf = ctypes_mod.create_unicode_buffer(512)
        user32.GetWindowTextW(hwnd, buf, 512)
        if buf.value == "AutoGovern2Code":
            found.value = hwnd
            return 0
        return 1

    user32.EnumWindows.argtypes = [enum_proc, ctypes_mod.c_void_p]
    user32.EnumWindows.restype = ctypes_mod.c_int
    user32.EnumWindows(enum_proc(callback), None)
    return int(found.value or 0)


def _tray_hwnd(ctypes_mod, user32, kernel32) -> int:
    global _CAPTION_HWND
    if _CAPTION_HWND and user32.IsWindow(_CAPTION_HWND):
        return int(_CAPTION_HWND)
    hwnd = _glfw_hwnd(ctypes_mod)
    if hwnd:
        return hwnd
    active = int(user32.GetActiveWindow() or 0)
    if active:
        buf = ctypes_mod.create_unicode_buffer(512)
        user32.GetWindowTextW(active, buf, 512)
        if buf.value == "AutoGovern2Code":
            return active
    hwnd = int(user32.FindWindowW("GLFW30", "AutoGovern2Code") or 0)
    if hwnd:
        return hwnd
    hwnd = int(user32.FindWindowW(None, "AutoGovern2Code") or 0)
    if hwnd:
        return hwnd
    return _enum_tray_hwnd(ctypes_mod, user32, kernel32)


def _apply_dark_caption() -> None:
    """Paint the native caption the same dark as the tray, not the Windows accent green."""
    if os.name != "nt":
        return
    try:
        ctypes_mod, user32, dwmapi, kernel32 = _caption_api()
        hwnd = _tray_hwnd(ctypes_mod, user32, kernel32)
        if not hwnd:
            return
        global _CAPTION_HWND
        if hwnd == _CAPTION_HWND:
            return
        dark = ctypes_mod.c_int(1)
        none_backdrop = ctypes_mod.c_int(1)
        for attr in (20, 19):
            dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes_mod.byref(dark), ctypes_mod.sizeof(dark))
        dwmapi.DwmSetWindowAttribute(hwnd, 38, ctypes_mod.byref(none_backdrop), ctypes_mod.sizeof(none_backdrop))
        # COLORREF 0x00BBGGRR. 0x00000000 is treated as "use accent" on some Win11 builds.
        caption = ctypes_mod.c_uint(0x00292421)
        text_color = ctypes_mod.c_uint(0x00E6E4E1)
        dwmapi.DwmSetWindowAttribute(hwnd, 35, ctypes_mod.byref(caption), ctypes_mod.sizeof(caption))
        dwmapi.DwmSetWindowAttribute(hwnd, 34, ctypes_mod.byref(caption), ctypes_mod.sizeof(caption))
        dwmapi.DwmSetWindowAttribute(hwnd, 36, ctypes_mod.byref(text_color), ctypes_mod.sizeof(text_color))
        if hwnd != _CAPTION_HWND:
            user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, 0x0037)
            _CAPTION_HWND = hwnd
    except OSError:
        return


def widget_id(label: str, key: str) -> str:
    """ImGui ids must stay unique when two rows share a visible title."""
    return f"{label}##{key}"


def _selectable(label: str, selected: bool = False) -> bool:
    from imgui_bundle import imgui

    clicked, _checked = imgui.selectable(label, selected)
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
    tree_lock = lock
    extra = getattr(imgui.DockNodeFlags_, "no_docking_split", None)
    if extra is not None:
        try:
            tree_lock = lock | extra
        except Exception:
            tree_lock = lock

    def split(initial: str, name: str, direction, ratio: float, flags=lock) -> hello_imgui.DockingSplit:
        item = hello_imgui.DockingSplit()
        item.initial_dock = initial
        item.new_dock = name
        item.direction = direction
        item.ratio = ratio
        item.node_flags = flags
        return item

    return [
        split("MainDockSpace", "FileTreeSpace", imgui.Dir.left, 0.26, tree_lock),
        split("MainDockSpace", "InspectorSpace", imgui.Dir.right, 0.38),
        split("InspectorSpace", "CardSpace", imgui.Dir.down, 0.50),
    ]


def _windows(state: AppState):
    from imgui_bundle import hello_imgui, imgui

    def window(label: str, space: str, gui) -> hello_imgui.DockableWindow:
        item = hello_imgui.DockableWindow()
        item.label = label
        item.dock_space_name = space
        item.can_be_closed = False
        item.remember_is_visible = False
        item.is_visible = True
        item.imgui_window_flags = imgui.WindowFlags_.no_collapse
        item.gui_function = gui
        return item

    return [
        window("文件树", "FileTreeSpace", lambda: _guarded(state, "文件树", lambda: _gui_tree(state))),
        window("谱系", "MainDockSpace", lambda: _guarded(state, "谱系", lambda: _gui_lineage(state))),
        window("详情", "InspectorSpace", lambda: _guarded(state, "详情", lambda: _gui_inspect(state))),
        window("知识卡片", "CardSpace", lambda: _guarded(state, "知识卡片", lambda: _gui_cards(state))),
    ]


def _menu_item(label: str, selected: bool = False, enabled: bool = True) -> tuple[bool, bool]:
    from imgui_bundle import imgui

    clicked, checked = imgui.menu_item(label, "", selected, enabled)
    return bool(clicked), bool(checked)


FILETREE_MIN_W = 320.0


def _caption_place(item_h: float) -> None:
    """Menu-bar layout ignores SetCursorPosY; pin the item to the bar's vertical center in screen space."""
    from imgui_bundle import imgui

    wp = imgui.get_window_pos()
    wh = float(imgui.get_window_size().y)
    cur = imgui.get_cursor_screen_pos()
    imgui.set_cursor_screen_pos(imgui.ImVec2(float(cur.x), float(wp.y) + max(1.0, (wh - item_h) * 0.5)))


def _menus(state: AppState) -> None:
    from imgui_bundle import imgui

    imgui.push_style_var(imgui.StyleVar_.item_spacing, imgui.ImVec2(8.0, 4.0))
    imgui.push_style_var(imgui.StyleVar_.frame_padding, imgui.ImVec2(6.0, 3.0))
    try:
        label = "AutoGovern2Code"
        ts = imgui.calc_text_size(label)
        wp = imgui.get_window_pos()
        wh = float(imgui.get_window_size().y)
        tx = float(wp.x) + 12.0
        ty = float(wp.y) + max(0.0, (wh - float(ts.y)) * 0.5)
        imgui.set_cursor_screen_pos(imgui.ImVec2(tx, ty))
        imgui.invisible_button("##title-hit", imgui.ImVec2(float(ts.x) + 8.0, float(ts.y)))
        _caption_hit(state)
        imgui.get_window_draw_list().add_text(
            imgui.ImVec2(tx, ty),
            imgui.get_color_u32(imgui.ImVec4(0.90, 0.93, 0.97, 1.0)),
            label,
        )
        _title_bar_buttons(state, wh)
    finally:
        imgui.pop_style_var(2)


def _chrome_button(kind: str, size: float, *, close: bool = False, restore: bool = False) -> bool:
    """Vector caption icon, centered in a square hit target. Never uses missing Unicode glyphs."""
    from imgui_bundle import imgui

    pos = imgui.get_cursor_screen_pos()
    clicked = imgui.invisible_button(widget_id(kind, "winchrome"), imgui.ImVec2(size, size))
    hovered = imgui.is_item_hovered()
    active = imgui.is_item_active()
    dl = imgui.get_window_draw_list()
    x0, y0 = float(pos.x), float(pos.y)
    x1, y1 = x0 + size, y0 + size
    if close and (hovered or active):
        fill = imgui.get_color_u32(imgui.ImVec4(0.72, 0.22, 0.22, 1.0 if active else 0.92))
        dl.add_rect_filled(imgui.ImVec2(x0, y0), imgui.ImVec2(x1, y1), fill)
    elif hovered or active:
        fill = imgui.get_color_u32(imgui.ImVec4(1.0, 1.0, 1.0, 0.14 if active else 0.10))
        dl.add_rect_filled(imgui.ImVec2(x0, y0), imgui.ImVec2(x1, y1), fill)
    ink = imgui.get_color_u32(imgui.ImVec4(0.92, 0.93, 0.95, 1.0))
    cx = x0 + size * 0.5
    cy = y0 + size * 0.5
    pad = size * 0.28
    thick = 1.4
    if kind == "min":
        dl.add_line(imgui.ImVec2(cx - pad, cy), imgui.ImVec2(cx + pad, cy), ink, thick)
    elif kind == "max" and restore:
        inner = pad * 0.55
        dl.add_rect(
            imgui.ImVec2(cx - pad + inner, cy - pad),
            imgui.ImVec2(cx + pad, cy + pad - inner),
            ink,
            0.0,
            thick,
        )
        dl.add_rect(
            imgui.ImVec2(cx - pad, cy - pad + inner),
            imgui.ImVec2(cx + pad - inner, cy + pad),
            ink,
            0.0,
            thick,
        )
    elif kind == "max":
        dl.add_rect(
            imgui.ImVec2(cx - pad, cy - pad),
            imgui.ImVec2(cx + pad, cy + pad),
            ink,
            0.0,
            thick,
        )
    else:
        dl.add_line(imgui.ImVec2(cx - pad, cy - pad), imgui.ImVec2(cx + pad, cy + pad), ink, thick)
        dl.add_line(imgui.ImVec2(cx + pad, cy - pad), imgui.ImVec2(cx - pad, cy + pad), ink, thick)
    return bool(clicked)


def _title_bar_buttons(state: AppState, bar_h: float) -> None:
    """Min/max/close on the dark menu bar. Native caption is off so Windows accent cannot paint it."""
    from imgui_bundle import hello_imgui, imgui

    win_h = float(imgui.get_window_size().y) or bar_h
    size = max(12.0, min(14.0, win_h - 10.0))
    spacing = float(imgui.get_style().item_spacing.x)
    need = 3.0 * size + 2.0 * spacing
    remain = float(imgui.get_content_region_avail().x)
    imgui.push_style_color(imgui.Col_.button, (0.0, 0.0, 0.0, 0.0))
    imgui.push_style_color(imgui.Col_.button_hovered, (0.0, 0.0, 0.0, 0.0))
    imgui.push_style_color(imgui.Col_.button_active, (0.0, 0.0, 0.0, 0.0))
    _caption_place(size)
    imgui.invisible_button("##caption-drag", imgui.ImVec2(max(8.0, remain - need - spacing), size))
    imgui.pop_style_color(3)
    _caption_hit(state)
    hwnd, user32 = _window_chrome()
    zoomed = _window_is_maximized(hwnd, user32)
    _caption_place(size)
    if _chrome_button("min", size) and hwnd and user32 is not None:
        audit(state, "最小化", "标题栏", "")
        user32.ShowWindow(hwnd, 6)
    _caption_place(size)
    if _chrome_button("max", size, restore=zoomed):
        audit(state, "还原" if zoomed else "最大化", "标题栏", "按钮")
        _caption_press(double=True)
    _caption_place(size)
    if _chrome_button("close", size, close=True):
        audit(state, "关闭", "标题栏", "")
        hello_imgui.get_runner_params().app_shall_exit = True


def _window_chrome():
    if os.name != "nt":
        return 0, None
    try:
        ctypes_mod, user32, _dwmapi, kernel32 = _caption_api()
        return _tray_hwnd(ctypes_mod, user32, kernel32), user32
    except OSError:
        return 0, None


def _caption_hit(state: AppState) -> None:
    """Title/blank caption: drag only after move, double-click maximize. Click must not start a drag."""
    from imgui_bundle import imgui

    if not imgui.is_item_hovered():
        return
    if imgui.is_mouse_double_clicked(0):
        audit(state, "最大化/还原", "标题栏", "双击")
        _caption_press(double=True)
    elif imgui.is_mouse_dragging(0, 6.0):
        _caption_press(double=False)


def _window_is_maximized(hwnd: int, user32) -> bool:
    if hwnd and user32 is not None and user32.IsZoomed(hwnd):
        return True
    try:
        from imgui_bundle import hello_imgui

        ctypes_mod, _u, _d, _k = _caption_api()
        addr = int(hello_imgui.get_glfw_window_address() or 0)
        if addr:
            return bool(_glfw_dll(ctypes_mod).glfwGetWindowAttrib(addr, 0x00020008))
    except Exception:
        pass
    return False


def _caption_press(*, double: bool) -> None:
    proof = os.environ.get("AG2C_CAPTION_PROOF") or str(Path(os.environ.get("TEMP", ".")) / "ag2c-caption-proof.txt")
    try:
        Path(proof).write_text("double" if double else "drag", encoding="utf-8")
    except OSError:
        pass
    hwnd, user32 = _window_chrome()
    if not hwnd or user32 is None:
        return
    if double:
        try:
            from imgui_bundle import hello_imgui

            ctypes_mod, _user32, _dwmapi, _kernel32 = _caption_api()
            addr = int(hello_imgui.get_glfw_window_address() or 0)
            dll = _glfw_dll(ctypes_mod)
            maximized = bool(addr and dll.glfwGetWindowAttrib(addr, 0x00020008)) or bool(user32.IsZoomed(hwnd))
            if addr:
                if maximized:
                    dll.glfwRestoreWindow(addr)
                else:
                    dll.glfwMaximizeWindow(addr)
            else:
                user32.ShowWindow(hwnd, 9 if maximized else 3)
        except Exception:
            user32.ShowWindow(hwnd, 9 if user32.IsZoomed(hwnd) else 3)
        return
    user32.ReleaseCapture()
    user32.SendMessageW(hwnd, 0x00A1, 2, 0)


def _scan_overlay(message: str) -> None:
    from imgui_bundle import imgui

    imgui.spacing()
    imgui.text_disabled(message)
    width = imgui.get_content_region_avail()[0]
    imgui.progress_bar(-0.35 * imgui.get_time(), (max(width, 8.0), 8.0), "")


def _status_bar(state: AppState) -> None:
    from imgui_bundle import imgui

    with state.lock:
        status = state.status
        busy = state.busy
        loading = state.loading
    prefix = ""
    if loading or busy:
        spin = "|/-\\"[int(imgui.get_time() * 8) % 4]
        prefix = f"{spin} 扫描中 · "
    imgui.text(prefix + status)
    io = imgui.get_io()
    fps = float(getattr(io, "framerate", 0.0) or 0.0)
    dt = float(getattr(io, "delta_time", 0.0) or 0.0) * 1000.0
    parts = []
    for key in ("文件树", "谱系", "详情", "知识卡片", "菜单", "DWM"):
        ms = state.frame_ms.get(key)
        if ms is not None:
            parts.append(f"{key} {ms:.1f}")
    meter = f"{fps:.0f} fps  {dt:.1f} ms"
    if parts:
        meter += "  ·  " + "  ".join(parts)
    btn_w = float(imgui.calc_text_size("审计").x) + 18.0
    meter_w = float(imgui.calc_text_size(meter).x)
    width = float(imgui.get_window_width())
    avail_meter = width - meter_w - 16.0
    avail_btn = avail_meter - btn_w - 10.0
    if avail_btn > float(imgui.get_cursor_pos_x()) + 24.0:
        imgui.same_line(avail_btn)
    else:
        imgui.same_line()
    if state.audit_open:
        imgui.push_style_color(imgui.Col_.button, (0.28, 0.50, 0.78, 0.70))
        imgui.push_style_color(imgui.Col_.button_hovered, (0.32, 0.56, 0.84, 0.85))
    clicked = imgui.small_button("审计")
    if state.audit_open:
        imgui.pop_style_color(2)
    if clicked:
        state.audit_open = not state.audit_open
        audit(state, "打开审计" if state.audit_open else "关闭审计", "状态栏", "")
    if avail_meter > float(imgui.get_cursor_pos_x()) + 8.0:
        imgui.same_line(avail_meter)
    else:
        imgui.same_line()
    imgui.text_disabled(meter)


def _gui_audit(state: AppState) -> None:
    """Floating debug log. Not a dock pane; drawn after the four windows."""
    from imgui_bundle import imgui

    if not state.audit_open:
        return
    flags = imgui.WindowFlags_.no_docking | imgui.WindowFlags_.no_saved_settings
    imgui.set_next_window_size(imgui.ImVec2(560.0, 420.0), imgui.Cond_.first_use_ever)
    imgui.set_next_window_pos(imgui.ImVec2(72.0, 72.0), imgui.Cond_.first_use_ever)
    visible, opened = imgui.begin("审计日志", True, flags)
    try:
        if opened is False:
            state.audit_open = False
            audit(state, "关闭审计", "审计日志", "窗口")
            return
        if not visible:
            return
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
                imgui.text_disabled("还没有操作。点击文件、知识卡或谱系节点后会出现在这里。")
            else:
                for line in reversed(state.audit_lines):
                    imgui.text_wrapped(line)
        finally:
            imgui.end_child()
    finally:
        imgui.end()


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
    if busy or loading:
        _scan_overlay("正在重新扫描项目…")
    imgui.separator()


def _gui_gate_strip(state: AppState, project: dict[str, Any]) -> None:
    """Always-visible operator pulse: entry, delivery, records, construction."""
    from imgui_bundle import imgui

    with state.lock:
        details = state.details
        inspect_mode = str(state.inspect.get("mode") or "")
    rows = project_gate_rows(project, details)
    if not rows:
        return
    imgui.spacing()
    for row in rows:
        label = str(row.get("label") or "")
        value = str(row.get("value") or "")
        kind = str(row.get("id") or "")
        warn = bool(row.get("warn"))
        shown = f"{label}    {value}"
        pushed = 0
        if warn:
            imgui.push_style_color(imgui.Col_.text, (0.92, 0.78, 0.35, 1.0))
            pushed += 1
        picked = _selectable(widget_id(shown, "gate:" + kind), inspect_mode == kind)
        if pushed:
            imgui.pop_style_color(pushed)
        if picked:
            audit(state, "查看" + label, "项目栏", value)
            copied = ""
            health = None
            if kind == "gate":
                health = mcp_health_snapshot(
                    handshake=False,
                    cwd=text(project, "root") or None,
                    managed=bool(project.get("delivery_enforced")) if "delivery_enforced" in project else None,
                )
                copied = mcp_entry_text()
            _inspect_gate(state, kind, project, details, prompt=copied, health=health)


def _copy_mcp_entry() -> str:
    from imgui_bundle import imgui

    prompt = mcp_entry_text()
    try:
        imgui.set_clipboard_text(prompt)
    except Exception:
        pass
    return prompt


def _inspect_gate(
    state: AppState,
    kind: str,
    project: dict[str, Any],
    details: dict[str, Any] | None,
    prompt: str = "",
    health: dict[str, Any] | None = None,
) -> None:
    agents = [item for item in (project.get("agents") or []) if isinstance(item, dict)]
    last = project.get("last_task") if isinstance(project.get("last_task"), dict) else None
    worktrees = [item for item in ((details or {}).get("worktrees") or []) if isinstance(item, dict)]
    titles = {"gate": "AI 入口", "records": "实际记录", "worktrees": "施工"}
    with state.lock:
        state.inspect = {
            "mode": kind,
            "title": titles.get(kind, kind),
            "status": str((health or {}).get("label") or "") if kind == "gate" else "",
            "summary": "",
            "claim": "",
            "path": text(project, "root"),
            "peers": [],
            "files": [],
            "cards": [],
            "message": "",
            "prompt": prompt or (mcp_entry_text() if kind == "gate" else ""),
            "mcp_health": health or {},
            "agents": agents,
            "entry_ready": bool(project.get("entry_ready")),
            "delivery_enforced": bool(project.get("delivery_enforced")),
            "completed_tasks": int(project.get("completed_tasks") or 0),
            "last_task": last,
            "product": project.get("product"),
            "worktrees": worktrees,
            "open_tasks": int(project.get("open_tasks") or 0),
        }
        state.inspect_key = "gate:" + kind


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


def _cached_uid(node: dict[str, Any]) -> int:
    uid = node.get("_uid")
    if uid is None:
        uid = lineage_uid("node", str(node.get("visual_id") or node["id"]))
        node["_uid"] = uid
    return int(uid)


def _lineage_is_marked(node: dict[str, Any], selected: str, highlight: set[str], inspect_key: str) -> bool:
    """True when this lineage node is the current card (or one of several owners)."""
    vid = text(node, "visual_id") or text(node, "id")
    nid = text(node, "id")
    title = text(node, "title")
    keys = {vid, nid, title}
    if selected and selected in keys:
        return True
    if inspect_key and inspect_key in keys:
        return True
    for key in highlight:
        if not key:
            continue
        if key in keys or vid.startswith(key + "@") or nid.startswith(key + "@"):
            return True
    return False


def _lineage_card_colors(marked: bool) -> tuple[tuple[float, float, float, float], tuple[float, float, float, float]]:
    if marked:
        return (0.16, 0.28, 0.42, 0.98), (0.45, 0.72, 0.98, 1.00)
    return (0.11, 0.12, 0.15, 0.98), (0.48, 0.52, 0.60, 0.95)


def _reveal_lineage_owners(state: AppState) -> None:
    details = state.details
    if details is None:
        return
    snapshot = _lineage_snapshot(state, details)
    want = {str(item) for item in state.lineage_nav_ids if str(item)}
    want.update(state.highlight_card_keys)
    if state.selected_card_key:
        want.add(state.selected_card_key)
    if not want:
        return
    state.lineage_expanded.add(LINEAGE_PROJECT_ID)
    visual: list[str] = []
    for node in snapshot["nodes"]:
        if not isinstance(node, dict):
            continue
        nid = text(node, "id")
        vid = text(node, "visual_id") or nid
        title = text(node, "title")
        if nid not in want and vid not in want and title not in want:
            continue
        kind = text(node, "kind")
        if kind == "knowledge":
            parent = text(node, "parent")
            while parent:
                state.lineage_expanded.add(parent)
                parent_node = next(
                    (item for item in snapshot["nodes"] if isinstance(item, dict) and (text(item, "visual_id") or text(item, "id")) == parent),
                    None,
                )
                parent = text(parent_node, "parent") if parent_node else ""
            if vid:
                visual.append(vid)
        elif kind == "module" and vid:
            visual.append(vid)
    if visual:
        state.lineage_nav_ids = list(dict.fromkeys([*visual, *state.lineage_nav_ids]))
        state.lineage_nav_id = state.lineage_nav_ids[0]


def _focus_path(state: AppState, rel: str, *, where: str = "文件树") -> None:
    audit(state, "点击文件", where, rel)
    with state.lock:
        files, cards = _all_rows(state.details)
        focused = focus_file(files, cards, rel)
        if focused is not None:
            state.apply_focus(focused)
            _reveal_lineage_owners(state)
        else:
            audit(state, "未命中文件", where, rel)


def _focus_card(state: AppState, card: dict[str, Any], *, pan_lineage: bool = True, where: str = "知识卡片") -> None:
    title = text(card, "title") or text(card, "id")
    audit(state, "点击知识卡", where, title)
    with state.lock:
        files, _cards = _all_rows(state.details)
        state.apply_focus(focus_card(files, card))
        _reveal_lineage_owners(state)
        if not pan_lineage:
            state.lineage_nav_id = ""
            state.lineage_nav_ids = []


def _activate_owner(state: AppState, owner: str, *, where: str = "详情") -> None:
    audit(state, "点击知识卡", where, owner)
    with state.lock:
        files, cards = _all_rows(state.details)
        card = card_for_owner(cards, owner)
        if card is not None:
            state.apply_focus(focus_card(files, card))
            _reveal_lineage_owners(state)
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
    if state.busy or state.loading:
        _scan_overlay("正在重新扫描文件树…")
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
            if claim == "未认领":
                imgui.push_style_color(imgui.Col_.text, (0.90, 0.55, 0.38, 1.0))
                pushed += 1
            elif claim == "重复认领":
                imgui.push_style_color(imgui.Col_.text, (0.92, 0.78, 0.35, 1.0))
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
        short = _lineage_label(title, 188.0 if indent else 208.0)
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


def _focus_lineage_node(state: AppState, node: dict[str, Any]) -> None:
    kind = text(node, "kind")
    visual_id = text(node, "visual_id") or text(node, "id")
    files, cards = _all_rows(state.details)
    if kind == "knowledge":
        match = card_matching_lineage(cards, node)
        if match is not None:
            match["ordinal_label"] = text(node, "ordinal_label")
            match["ordinal_path"] = list(node.get("ordinal_path") or [])
            _focus_card(state, match, pan_lineage=False, where="谱系")
            return
    module_path = text(node, "path")
    prefixes: set[str] = set()
    if kind == "module" and module_path:
        prefixes.add(module_path)
        prefixes.update(ancestor_prefixes(module_path))
    summary = text(node, "summary")
    if kind == "project" and not summary:
        summary = "点这里看本项目宪章。下面按模块挂知识卡。"
    elif kind == "module" and not summary:
        summary = "这是项目里的一个模块。盒子里的知识卡说明这块代码为什么这样写。"
    module_cards = node.get("cards") if isinstance(node.get("cards"), list) else []
    related = [
        {
            "id": str(item.get("id") or ""),
            "title": lineage_heading(item) or str(item.get("title") or item.get("id") or ""),
        }
        for item in module_cards
        if isinstance(item, dict)
    ]
    inspect_mode = "project" if kind == "project" else ("module" if kind == "module" else "card")
    with state.lock:
        state.inspect = {
            "mode": inspect_mode,
            "title": lineage_heading(node) or text(node, "title") or visual_id,
            "status": text(node, "status"),
            "summary": summary,
            "claim": text(node, "kindLabel"),
            "path": module_path,
            "peers": [],
            "files": [],
            "cards": related,
            "message": "还没有知识卡" if kind == "module" and node.get("empty") else "",
        }
        state.inspect_key = visual_id
        state.selected_card_key = text(node, "id") if kind == "knowledge" else visual_id
        state.selected_file = ""
        state.highlight_paths = set()
        state.force_open = prefixes
        state.lineage_nav_id = ""
        state.lineage_nav_ids = []
        state.scroll_card_key = ""


def _lineage_snapshot(state: AppState, details: dict[str, Any]) -> dict[str, Any]:
    if state.lineage_cache is not None and state.lineage_cache_from is details:
        return state.lineage_cache
    project = details.get("project") if isinstance(details.get("project"), dict) else {}
    snapshot = build_lineage(details, project_name=text(project, "name"))
    state.lineage_cache = snapshot
    state.lineage_cache_from = details
    state.lineage_placed = False
    state.lineage_view = None
    state.lineage_layout_key = None
    state.lineage_expanded = {LINEAGE_PROJECT_ID}
    return snapshot


def _lineage_label(value: str, max_px: float) -> str:
    text_value = str(value or "").replace("\n", " ")
    width = 0.0
    out: list[str] = []
    for char in text_value:
        width += 16.0 if ord(char) > 127 else 8.5
        if width > max_px:
            return "".join(out) + "…"
        out.append(char)
    return text_value


def _cubic_arrow(dl: Any, imgui: Any, x0: float, y0: float, x1: float, y1: float, color: int) -> None:
    mid_x = (x0 + x1) * 0.5
    dl.add_bezier_cubic(
        imgui.ImVec2(x0, y0),
        imgui.ImVec2(mid_x, y0),
        imgui.ImVec2(mid_x, y1),
        imgui.ImVec2(x1, y1),
        color,
        2.0,
        16,
    )
    dl.add_triangle_filled(
        imgui.ImVec2(x1, y1),
        imgui.ImVec2(x1 - 8.0, y1 - 4.5),
        imgui.ImVec2(x1 - 8.0, y1 + 4.5),
        color,
    )


def _lineage_status_color(tag: str, imgui: Any) -> Any:
    if tag == "placeholder":
        return imgui.ImVec4(0.92, 0.78, 0.35, 1.0)
    if tag == "opaque":
        return imgui.ImVec4(0.90, 0.55, 0.38, 1.0)
    if tag == "writing":
        return imgui.ImVec4(0.45, 0.72, 0.98, 1.0)
    return imgui.ImVec4(0.70, 0.74, 0.80, 1.0)


def _combo_marker_hit(hx: float, hy: float) -> tuple[float, float, float, float]:
    return (hx + 4.0, hy + 6.0, 22.0, 22.0)


def _point_in_rect(px: float, py: float, x: float, y: float, w: float, h: float) -> bool:
    return x <= px <= x + w and y <= py <= y + h


def _lineage_view_pads(nodes: list[dict[str, Any]]) -> tuple[float, float, float, float] | None:
    """Padded canvas corners: extra left slack so the cluster sits right and is not full-pane wide."""
    box: list[float] | None = None
    for node in nodes:
        rects = [(float(node.get("x") or 0), float(node.get("y") or 0), float(node.get("width") or 0), float(node.get("height") or 0))]
        hull = node.get("outward_hull") if isinstance(node.get("outward_hull"), dict) else None
        if hull is not None:
            rects.append(
                (
                    float(hull.get("x") or 0),
                    float(hull.get("y") or 0),
                    float(hull.get("width") or 0),
                    float(hull.get("height") or 0),
                )
            )
        for x, y, w, h in rects:
            if box is None:
                box = [x, y, x + w, y + h]
            else:
                box[0] = min(box[0], x)
                box[1] = min(box[1], y)
                box[2] = max(box[2], x + w)
                box[3] = max(box[3], y + h)
    if box is None:
        return None
    gw = max(1.0, box[2] - box[0])
    gh = max(1.0, box[3] - box[1])
    return (box[0] - gw * 0.12, box[1] - gh * 0.04, box[2] + gw * 0.05, box[3] + gh * 0.04)


def _view_pad_node(ed: Any, imgui: Any, x: float, y: float, key: str) -> None:
    nid = ed.NodeId(lineage_uid("node", key))
    ed.set_node_position(nid, imgui.ImVec2(x, y))
    ed.push_style_color(ed.StyleColor.node_bg, imgui.ImVec4(0.0, 0.0, 0.0, 0.0))
    ed.push_style_color(ed.StyleColor.node_border, imgui.ImVec4(0.0, 0.0, 0.0, 0.0))
    ed.begin_node(nid)
    imgui.dummy((8.0, 8.0))
    ed.end_node()
    ed.pop_style_color(2)


def _gui_lineage(state: AppState) -> None:
    from imgui_bundle import imgui
    from imgui_bundle import imgui_node_editor as ed

    _ensure_lineage_editor(state)
    if state.lineage_editor is None:
        imgui.text_disabled("谱系画布未就绪")
        return
    with state.lock:
        details = state.details
        selected = state.selected_card_key
        highlight = set(state.highlight_card_keys)
        inspect_key = state.inspect_key
        loading = state.loading
        busy = state.busy
        fit = state.lineage_fit
        nav_id = state.lineage_nav_id
        nav_ids = list(state.lineage_nav_ids)
        placed = state.lineage_placed
    if details is None:
        imgui.text_disabled("选择一个项目后，这里显示知识卡谱系。")
        return
    if loading or busy:
        _scan_overlay("正在重新扫描谱系…")
    lineage = _lineage_snapshot(state, details)
    if not lineage["nodes"]:
        imgui.text_disabled("还没有可画的知识卡谱系")
        return
    imgui.text_disabled("点 + / − 展开或收起。每一层向右一列；点文件树哪一层就映射哪一层。")
    avail = imgui.get_content_region_avail()
    if float(getattr(avail, "x", 0) or 0) < 40.0 or float(getattr(avail, "y", 0) or 0) < 40.0:
        return
    with state.lock:
        expanded = set(state.lineage_expanded)
        layout_key = frozenset(expanded)
        if state.lineage_view is None or state.lineage_layout_key != layout_key:
            view = [dict(node) for node in lineage["nodes"]]
            layout_lineage_view(view, expanded)
            state.lineage_view = view
            state.lineage_layout_key = layout_key
            state.lineage_placed = False
        else:
            view = state.lineage_view
        placed = state.lineage_placed
    visible = [node for node in view if not node.get("hidden")]
    project = next((node for node in visible if node.get("kind") == "project"), None)
    modules = [node for node in visible if node.get("kind") == "module"]
    cards = [node for node in visible if node.get("kind") == "knowledge"]
    has_modules = any(node.get("kind") == "module" for node in lineage["nodes"])
    toggles: list[str] = []
    pending_click = 0
    canvas_nodes = visible

    def _place(node: dict[str, Any]) -> None:
        ed.set_node_position(
            ed.NodeId(_cached_uid(node)),
            imgui.ImVec2(float(node.get("x") or 0), float(node.get("y") or 0)),
        )

    def _toggle(visual_id: str, opened: bool) -> None:
        mark = "-" if opened else "+"
        if imgui.small_button(widget_id(mark, "exp:" + visual_id)):
            toggles.append(visual_id)
        imgui.same_line()

    ed.set_current_editor(state.lineage_editor)
    ed.begin("谱系", imgui.ImVec2(0.0, 0.0))
    try:
        dl = imgui.get_window_draw_list()
        hull_fill = imgui.get_color_u32(imgui.ImVec4(0.18, 0.22, 0.28, 0.82))
        hull_line = imgui.get_color_u32(imgui.ImVec4(0.50, 0.64, 0.84, 1.00))
        title_col = imgui.get_color_u32(imgui.ImVec4(0.90, 0.93, 0.97, 1.00))
        link_color = imgui.get_color_u32(imgui.ImVec4(0.46, 0.62, 0.88, 0.90))
        marker_hits: list[tuple[str, float, float, float, float]] = []
        for node in modules:
            visual_id = str(node.get("visual_id") or node["id"])
            if visual_id not in expanded:
                continue
            hx = float(node.get("x") or 0)
            hy = float(node.get("y") or 0)
            hw = float(node.get("width") or 200)
            hh = float(node.get("height") or 48)
            dl.add_rect_filled(imgui.ImVec2(hx, hy), imgui.ImVec2(hx + hw, hy + hh), hull_fill, 8.0)
            # imgui-bundle: rounding, thickness, flags (not Dear ImGui's rounding, flags, thickness).
            dl.add_rect(
                imgui.ImVec2(hx, hy),
                imgui.ImVec2(hx + hw, hy + hh),
                hull_line,
                8.0,
                2.0,
            )
            if bool(node.get("cards")) and not node.get("empty"):
                mx, my, mw, mh = _combo_marker_hit(hx, hy)
                marker_hits.append((visual_id, mx, my, mw, mh))
            tag = str(node.get("status") or "")
            tag_w = float(imgui.calc_text_size(tag).x) if tag and tag != "还没有知识卡" else 0.0
            label = _lineage_label(lineage_heading(node), max(48.0, hw - 44.0 - tag_w))
            dl.add_text(imgui.ImVec2(hx + 28.0, hy + 10.0), title_col, label)
            if tag_w:
                tag_col = imgui.get_color_u32(_lineage_status_color(str(node.get("statusTag") or ""), imgui))
                dl.add_text(imgui.ImVec2(hx + hw - tag_w - 10.0, hy + 10.0), tag_col, tag)
        for node in cards:
            hull = node.get("outward_hull") if isinstance(node.get("outward_hull"), dict) else None
            if hull is None or node.get("hidden"):
                continue
            hx = float(hull.get("x") or 0)
            hy = float(hull.get("y") or 0)
            hw = float(hull.get("width") or 200)
            hh = float(hull.get("height") or 48)
            dl.add_rect_filled(imgui.ImVec2(hx, hy), imgui.ImVec2(hx + hw, hy + hh), hull_fill, 8.0)
            dl.add_rect(
                imgui.ImVec2(hx, hy),
                imgui.ImVec2(hx + hw, hy + hh),
                hull_line,
                8.0,
                2.0,
            )
            tag = str(hull.get("status") or "")
            tag_w = float(imgui.calc_text_size(tag).x) if tag and tag != "还没有知识卡" else 0.0
            label = _lineage_label(str(hull.get("title") or node.get("title") or ""), max(48.0, hw - 20.0 - tag_w))
            dl.add_text(imgui.ImVec2(hx + 12.0, hy + 10.0), title_col, label)
            if tag_w:
                tag_col = imgui.get_color_u32(_lineage_status_color(str(node.get("statusTag") or ""), imgui))
                dl.add_text(imgui.ImVec2(hx + hw - tag_w - 10.0, hy + 10.0), tag_col, tag)
        if project is not None and str(project.get("visual_id") or project["id"]) in expanded:
            px = float(project.get("x") or 0)
            py = float(project.get("y") or 0)
            pw = float(project.get("width") or 200)
            ph = float(project.get("height") or 48)
            x0, y0 = px + pw, py + ph * 0.5
            cards_by_parent: dict[str, list[dict[str, Any]]] = {}
            for child in cards:
                cards_by_parent.setdefault(str(child.get("parent") or ""), []).append(child)
            for node in modules:
                mid = str(node.get("visual_id") or node["id"])
                kids = cards_by_parent.get(mid, [])
                if kids:
                    for child in kids:
                        cx = float(child.get("x") or 0)
                        cy = float(child.get("y") or 0) + float(child.get("height") or 40) * 0.5
                        _cubic_arrow(dl, imgui, x0, y0, cx, cy, link_color)
                else:
                    mx = float(node.get("x") or 0)
                    my = float(node.get("y") or 0) + float(node.get("height") or 48) * 0.5
                    _cubic_arrow(dl, imgui, x0, y0, mx, my, link_color)
            by_visual = {str(item.get("visual_id") or item.get("id") or ""): item for item in visible}
            for child in cards:
                parent = by_visual.get(str(child.get("parent") or ""))
                if parent is None or parent.get("kind") != "knowledge":
                    continue
                px1 = float(parent.get("x") or 0) + float(parent.get("width") or 0)
                py1 = float(parent.get("y") or 0) + float(parent.get("height") or 40) * 0.5
                cx = float(child.get("x") or 0)
                cy = float(child.get("y") or 0) + float(child.get("height") or 40) * 0.5
                _cubic_arrow(dl, imgui, px1, py1, cx, cy, link_color)
        imgui.push_style_var(imgui.StyleVar_.item_spacing, imgui.ImVec2(4.0, 1.0))
        try:
            for node in modules:
                visual_id = str(node.get("visual_id") or node["id"])
                opened = visual_id in expanded
                can_expand = bool(node.get("cards")) and not node.get("empty")
                if opened:
                    nid = ed.NodeId(_cached_uid(node))
                    ed.set_node_position(
                        nid,
                        imgui.ImVec2(float(node.get("x") or 0) + 4.0, float(node.get("y") or 0) + 6.0),
                    )
                    ed.push_style_color(ed.StyleColor.node_bg, imgui.ImVec4(0.18, 0.22, 0.28, 0.0))
                    ed.push_style_color(ed.StyleColor.node_border, imgui.ImVec4(0.50, 0.64, 0.84, 0.0))
                    ed.begin_node(nid)
                    if can_expand:
                        _toggle(visual_id, True)
                    ed.end_node()
                    ed.pop_style_color(2)
                    continue
                _place(node)
                content_w = max(80.0, float(node.get("width") or 200) - 12.0)
                ed.push_style_color(ed.StyleColor.node_bg, imgui.ImVec4(0.16, 0.18, 0.22, 0.96))
                ed.push_style_color(ed.StyleColor.node_border, imgui.ImVec4(0.38, 0.48, 0.62, 0.90))
                ed.begin_node(ed.NodeId(_cached_uid(node)))
                imgui.dummy((content_w, 1.0))
                if can_expand:
                    _toggle(visual_id, opened)
                imgui.text(_lineage_label(lineage_heading(node) or str(visual_id), content_w - 28))
                imgui.text_disabled(str(node.get("status") or "还没有知识卡"))
                ed.end_node()
                ed.pop_style_color(2)
            for node in cards:
                visual_id = str(node.get("visual_id") or node["id"])
                _place(node)
                card_w = max(80.0, float(node.get("width") or LINEAGE_CARD_W) - 12.0)
                bg, border = _lineage_card_colors(_lineage_is_marked(node, selected, highlight, inspect_key))
                ed.push_style_color(ed.StyleColor.node_bg, imgui.ImVec4(*bg))
                ed.push_style_color(ed.StyleColor.node_border, imgui.ImVec4(*border))
                ed.begin_node(ed.NodeId(_cached_uid(node)))
                imgui.dummy((card_w, 1.0))
                if node.get("nested") and node.get("cards"):
                    _toggle(visual_id, visual_id in expanded)
                heading = lineage_heading(node) or str(visual_id)
                imgui.text(_lineage_label(heading, card_w - (28.0 if node.get("nested") else 8.0)))
                extra = lineage_subtitle(node)
                if extra:
                    line = _lineage_label(extra, card_w - 8.0)
                    tag = str(node.get("statusTag") or "")
                    if node.get("replaced_by"):
                        imgui.text_disabled(line)
                    elif tag == "placeholder":
                        imgui.text_colored((0.92, 0.78, 0.35, 1.0), line)
                    elif tag == "opaque":
                        imgui.text_colored((0.90, 0.55, 0.38, 1.0), line)
                    else:
                        imgui.text_disabled(line)
                ed.end_node()
                ed.pop_style_color(2)
            if project is not None:
                _place(project)
                visual_id = str(project.get("visual_id") or project["id"])
                content_w = max(80.0, float(project.get("width") or 200) - 12.0)
                ed.push_style_color(ed.StyleColor.node_bg, imgui.ImVec4(0.16, 0.18, 0.22, 0.96))
                ed.push_style_color(ed.StyleColor.node_border, imgui.ImVec4(0.38, 0.48, 0.62, 0.90))
                ed.begin_node(ed.NodeId(_cached_uid(project)))
                imgui.dummy((content_w, 1.0))
                if has_modules:
                    _toggle(visual_id, visual_id in expanded)
                imgui.text(_lineage_label(str(project.get("title") or visual_id), content_w - 28))
                ed.end_node()
                ed.pop_style_color(2)
            pads = _lineage_view_pads(visible)
            if pads is not None:
                _view_pad_node(ed, imgui, pads[0], pads[1], "viewpad:tl")
                _view_pad_node(ed, imgui, pads[2], pads[3], "viewpad:br")
        finally:
            imgui.pop_style_var()
        hovered = ed.get_hovered_node()
        hovered_uid = hovered.id() if hovered is not None else 0
        dragging = False
        try:
            dragging = bool(imgui.is_mouse_dragging(0, 4.0))
        except Exception:
            dragging = False
        if not toggles and imgui.is_mouse_released(0) and not dragging:
            mouse = ed.screen_to_canvas(imgui.get_mouse_pos())
            mx, my = float(mouse.x), float(mouse.y)
            for visual_id, x, y, w, h in marker_hits:
                if _point_in_rect(mx, my, x, y, w, h):
                    toggles.append(visual_id)
                    break
            if not toggles:
                pad_uids = {lineage_uid("node", "viewpad:tl"), lineage_uid("node", "viewpad:br")}
                if hovered_uid and hovered_uid not in pad_uids:
                    pending_click = hovered_uid
                else:
                    for node in reversed(cards):
                        hull = node.get("outward_hull") if isinstance(node.get("outward_hull"), dict) else None
                        if hull is None or node.get("hidden"):
                            continue
                        if _point_in_rect(
                            mx,
                            my,
                            float(hull.get("x") or 0),
                            float(hull.get("y") or 0),
                            float(hull.get("width") or 0),
                            float(hull.get("height") or 0),
                        ):
                            pending_click = lineage_uid("node", str(node.get("visual_id") or node["id"]))
                            break
                    if not pending_click:
                        for node in reversed(modules):
                            x = float(node.get("x") or 0)
                            y = float(node.get("y") or 0)
                            w = float(node.get("width") or 0)
                            h = float(node.get("height") or 0)
                            if _point_in_rect(mx, my, x, y, w, h):
                                pending_click = lineage_uid("node", str(node.get("visual_id") or node["id"]))
                                break
    finally:
        ed.end()
    if not placed:
        with state.lock:
            state.lineage_placed = True
    if toggles:
        with state.lock:
            for visual_id in toggles:
                opening = visual_id not in state.lineage_expanded
                if opening:
                    state.lineage_expanded.add(visual_id)
                else:
                    state.lineage_expanded.discard(visual_id)
                audit(state, "展开" if opening else "收起", "谱系", visual_id)
    elif pending_click:
        for node in canvas_nodes:
            visual_id = str(node.get("visual_id") or node["id"])
            if lineage_uid("node", visual_id) != pending_click:
                continue
            kind = text(node, "kind")
            title = text(node, "title") or visual_id
            audit(state, "点击谱系节点", "谱系", f"{kind} {title}")
            if visual_id != selected and str(node.get("id") or "") != selected:
                _focus_lineage_node(state, node)
            break
    submitted = {str(node.get("visual_id") or node["id"]) for node in canvas_nodes}
    seek = [str(item) for item in nav_ids if str(item)]
    if nav_id and nav_id not in seek:
        seek.append(str(nav_id))
    if seek:
        related: list[str] = []
        for nid in seek:
            related.extend(lineage_related_ids(lineage, nid))
        related = [rid for rid in dict.fromkeys(related) if rid in submitted]
        if not related:
            for node in lineage["nodes"]:
                visual_id = str(node.get("visual_id") or node["id"])
                node_id = str(node.get("id") or "")
                parent = str(node.get("parent") or "")
                if node_id in seek or visual_id in seek:
                    if visual_id in submitted:
                        related.append(visual_id)
                    elif parent in submitted:
                        related.append(parent)
        if related:
            try:
                ed.clear_selection()
                append = False
                focus_id = ""
                for rid in dict.fromkeys(related):
                    if rid not in submitted:
                        continue
                    ed.select_node(ed.NodeId(lineage_uid("node", rid)), append)
                    append = True
                    if not focus_id or "@" in rid:
                        focus_id = rid
                if focus_id:
                    # CenterNodeOnScreen moves the node, which yanks cards out of combo hulls.
                    ed.navigate_to_selection(False, 0.0)
                    ed.clear_selection()
            except Exception:
                pass
            with state.lock:
                state.lineage_nav_id = ""
                state.lineage_nav_ids = []
                state.lineage_fit = False
                state.lineage_fit_frames = 0
    elif canvas_nodes and (fit or state.lineage_fit_frames > 0):
        try:
            ed.navigate_to_content(0.0)
        except Exception:
            pass
        with state.lock:
            if state.lineage_fit_frames > 0:
                state.lineage_fit_frames -= 1
            if state.lineage_fit_frames <= 0:
                state.lineage_fit = False
                state.lineage_fit_frames = 0


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
            imgui.text_colored((0.92, 0.78, 0.35, 1.0), status)
        else:
            imgui.text_disabled(status)
    if mode == "gate":
        imgui.separator()
        imgui.text_wrapped("AI 入口只有两件事：通用 MCP 连接说明（占位符，不绑厂商），以及检测 MCP 是否在工作。Skill 全文在 MCP 里；检测会连 Git hook 一起看。")
        if imgui.button("检测 MCP"):
            from ag2c.mcp_server import install_mcp_clients, mcp_health

            try:
                install_mcp_clients()
            except OSError:
                pass
            health = mcp_health(handshake=True, cwd=str(fields.get("path") or "") or None)
            with state.lock:
                state.inspect["mcp_health"] = health
                state.inspect["status"] = str(health.get("label") or "")
                state.inspect["prompt"] = mcp_entry_text()
                state.status = str(health.get("label") or "MCP")
            audit(state, "检测 MCP", "详情", str(health.get("status") or ""))
        imgui.same_line()
        if imgui.button("复制连接说明"):
            copied = _copy_mcp_entry()
            with state.lock:
                state.inspect["prompt"] = copied
                state.status = "连接说明已复制"
            audit(state, "复制连接说明", "详情", "")
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
        return
    if mode == "records":
        imgui.separator()
        completed = int(fields.get("completed_tasks") or 0)
        imgui.text_disabled(f"{completed} 次入库" if completed else "还没有入库任务")
        last = fields.get("last_task") if isinstance(fields.get("last_task"), dict) else None
        if last:
            delivery = last.get("delivery") if isinstance(last.get("delivery"), dict) else {}
            imgui.spacing()
            imgui.text_wrapped(str(delivery.get("request") or last.get("goal") or "最近一次任务"))
            if delivery.get("outcome"):
                imgui.text_wrapped(str(delivery.get("outcome")))
        product = fields.get("product")
        product_key = str(product.get("status") or product) if isinstance(product, dict) else str(product or "")
        if product_key:
            imgui.separator()
            imgui.text_disabled(PRODUCT_LABELS.get(product_key, product_key))
        return
    if mode == "worktrees":
        imgui.separator()
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
                imgui.text_colored((0.92, 0.78, 0.35, 1.0), f"{label}  ·  {goal}")
            else:
                imgui.text(f"{label}  ·  {goal}")
        return
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
        state.loading = False
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
        state.lineage_fit = True
        state.lineage_fit_frames = 24
        state.lineage_cache = None
        state.lineage_cache_from = None
        state.lineage_placed = False


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


def _set_span(state: AppState, card_id: str, tag: str) -> None:
    if state.api is None or not card_id:
        return
    root = ""
    with state.lock:
        root = state.selected_root
    if not root:
        return
    state.api.request("POST", "api/household/span", {"path": root, "id": card_id, "tag": tag})
    _load_details(state, root, refresh=True)


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
    _destroy_lineage_editor(state)
