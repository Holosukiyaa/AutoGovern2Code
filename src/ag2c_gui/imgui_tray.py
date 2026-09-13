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
    focus_card,
    focus_file,
    build_row_cache,
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
        self.row_cache: dict[str, Any] = {}
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
        self.custody_open = False

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


_TOAST_TTL_S = 8.0
_TOAST_WIDTH = 360.0



_OPS_TABS = (("audit", "操作日志"), ("worktrees", "施工"), ("records", "实际记录"), ("gate", "AI 入口"))


GATE_BUTTON_LABELS = {"gate": "MCP 链接", "records": "实际记录", "worktrees": "施工"}


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


def _apply_row_cache(state: AppState, details: dict[str, Any], files, cards, cache: dict[str, Any]) -> None:
    cache["details"] = details
    state.row_cache = cache
    state.rows_from = details
    state.all_files = files
    state.all_cards = cards
    state.card_file_counts = dict(cache.get("counts") or {})
    state.cov_key = None
    state.file_tree = None


def _cached_all_rows(state: AppState, details: dict[str, Any] | None) -> tuple[list[tuple[str, dict[str, Any]]], list[dict[str, Any]]]:
    if details is None:
        state.rows_from = None
        state.row_cache = {}
        return [], []
    if state.rows_from is details:
        return state.all_files, state.all_cards
    files, cards = _all_rows(details)
    cache = state.row_cache if state.row_cache.get("details") is details else build_row_cache(files, cards)
    _apply_row_cache(state, details, files, cards, cache)
    return files, cards


def _cached_coverage(state: AppState, details: dict[str, Any] | None, search: str, flag: str) -> tuple[list[tuple[str, dict[str, Any]]], list[dict[str, Any]]]:
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


def _focus_action(state: AppState, target: str, *, where: str, verb: str, miss: str, locate) -> None:
    """audit → lock → locate(files, cards) → apply_focus / 未命中。"""
    audit(state, verb, where, target)
    with state.lock:
        files, cards = _cached_all_rows(state, state.details)
        focused = locate(files, cards)
        if focused is not None:
            state.apply_focus(focused)
        else:
            audit(state, miss, where, target)


def _focus_path(state: AppState, rel: str, *, where: str = "文件树") -> None:
    _focus_action(state, rel, where=where, verb="点击文件", miss="未命中文件",
                  locate=lambda files, cards: (state.row_cache.get("file") or {}).get(rel) or focus_file(files, cards, rel))


def _activate_owner(state: AppState, owner: str, *, where: str = "详情") -> None:
    def _locate(files, cards):
        card = card_for_owner(cards, owner)
        if card is None:
            return None
        return (state.row_cache.get("card") or {}).get(row_key(card, text(card, "title"))) or focus_card(files, card)

    _focus_action(state, owner, where=where, verb="点击知识卡", miss="未命中知识卡", locate=_locate)


def _focus_card(state: AppState, card: dict[str, Any], *, where: str = "知识卡片") -> None:
    title = text(card, "title") or text(card, "id")
    audit(state, "点击知识卡", where, title)
    key = row_key(card, title)
    with state.lock:
        previous_key = state.selected_card_key
        focused = (state.row_cache.get("card") or {}).get(key)
        if focused is None:
            files, _cards = _cached_all_rows(state, state.details)
            focused = focus_card(files, card)
        state.apply_focus(focused)
        if state.selected_card_key and state.selected_card_key != previous_key:
            state.set_dock_visible("检查器", True)


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


def _combo_marker_hit(hx: float, hy: float) -> tuple[float, float, float, float]:
    return (hx + 4.0, hy + 6.0, 22.0, 22.0)


def _point_in_rect(px: float, py: float, x: float, y: float, w: float, h: float) -> bool:
    return x <= px <= x + w and y <= py <= y + h


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
    files, cards = _all_rows(payload)
    cache = build_row_cache(files, cards)
    with state.lock:
        state.details = payload
        _apply_row_cache(state, payload, files, cards, cache)
        state.error = ""
        state.clear_focus()
        graph = payload.get("graph") if isinstance(payload.get("graph"), dict) else {}
        headline = graph.get("headline")
        state.inspect = empty_inspect(str(headline) if headline else "")
    _refresh_open_panels(state)


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

from .imgui_panels import _gui_dashboard, _gui_audit_pending, _gui_splash, _status_bar, _gui_overlays, _gui_toasts, _audit_body, _gate_panel_content, _records_panel_content, _work_panel_content, _gui_ops, _gui_inspector, _gui_project_bar, _gui_gate_strip, _gui_tree, _gui_cards, _gui_inspect
from .imgui_runtime import main, _start_backend, _load_projects, _maybe_auto_refresh, _poll_digest, _poll_notifications, _add_project, _shutdown
