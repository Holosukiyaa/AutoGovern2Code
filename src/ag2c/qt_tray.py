"""Qt tray window built from stock PySide6 widgets."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from .tray_host import (
    DesktopApi,
    FILTERS,
    acquire_mutex,
    app_directory,
    apply_startup,
    coverage_rows,
    first_flag_label,
    inspect_fields,
    is_portable,
    mark_tray_hint_shown,
    portable_env,
    register_app,
    runtime_command,
    session_token,
    start_desktop_server,
    state_label,
    stop_desktop_server,
    startup_enabled,
    text,
    tray_hint_shown,
    unregister_app,
    wait_for_status,
    free_port,
    string_list,
)

STYLE = """
QMainWindow, QWidget#root, QWidget#loading {
  background: #f3f4f6;
  color: #1f2937;
  font-family: "Segoe UI", "Microsoft YaHei UI";
  font-size: 13px;
}
QFrame#bar, QFrame#detail {
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 10px;
}
QPushButton {
  min-height: 32px;
  padding: 0 12px;
  border: 1px solid #d1d5db;
  border-radius: 8px;
  background: #fff;
  color: #374151;
  font-weight: 600;
}
QPushButton[primary="true"] {
  border: 1px solid #2563eb;
  background: #eff6ff;
  color: #1d4ed8;
}
QPushButton[danger="true"] {
  border: 1px solid #fecaca;
  color: #dc2626;
}
QLineEdit, QComboBox, QListWidget, QTreeWidget, QTextEdit {
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  padding: 4px 8px;
}
QTreeWidget { background: #fff; }
QListWidget#cards { background: #f8faf9; }
QLabel#mark {
  background: #2563eb;
  color: #fff;
  border-radius: 8px;
  font-weight: 700;
  qproperty-alignment: AlignCenter;
}
QLabel#mute { color: #6b7280; }
QLabel#title { color: #111827; font-size: 15px; font-weight: 700; }
QLabel#issues {
  background: #fff7ed;
  color: #9a3412;
  border-radius: 6px;
  padding: 8px;
}
"""


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if any(arg.lower() == "--unregister" for arg in args):
        unregister_app()
        return 0
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:
        sys.stderr.write("PySide6 is required for the AutoGovern2Code tray. Install the gui extra.\n")
        return 2
    mutex = acquire_mutex()
    if mutex is None:
        return 0
    app = QApplication(sys.argv)
    app.setApplicationName("AutoGovern2Code")
    app.setQuitOnLastWindowClosed(False)
    window = TrayWindow(args)
    window.show()
    return app.exec()


class TrayWindow:
    def __init__(self, args: list[str]) -> None:
        from PySide6.QtCore import Qt, QTimer
        from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap
        from PySide6.QtWidgets import (
            QComboBox,
            QFileDialog,
            QFormLayout,
            QFrame,
            QHBoxLayout,
            QLabel,
            QLineEdit,
            QListWidget,
            QListWidgetItem,
            QMainWindow,
            QMenu,
            QMessageBox,
            QPushButton,
            QSplitter,
            QStackedWidget,
            QSystemTrayIcon,
            QTreeWidget,
            QTreeWidgetItem,
            QVBoxLayout,
            QWidget,
        )

        self._Qt = Qt
        self._QTimer = QTimer
        self._QFileDialog = QFileDialog
        self._QListWidgetItem = QListWidgetItem
        self._QMessageBox = QMessageBox
        self._QTreeWidgetItem = QTreeWidgetItem
        self._args = args
        self._app_dir = app_directory()
        self._portable = is_portable(args, self._app_dir)
        self._token = session_token()
        self._api: DesktopApi | None = None
        self._process = None
        self._details: dict[str, Any] | None = None
        self._really_exit = False
        self._busy = False
        self._frozen = getattr(sys, "frozen", False)
        if not self._portable and self._frozen:
            register_app(sys.executable)

        icon = _app_icon(QPixmap, QPainter, QColor, QIcon, Qt)

        class _Window(QMainWindow):
            def closeEvent(inner_self, event) -> None:
                self._close_event(event)

        self.window = _Window()
        self.window.setWindowTitle("AutoGovern2Code")
        self.window.setWindowIcon(icon)
        self.window.resize(1280, 860)
        self.window.setMinimumSize(960, 640)
        self.window.setStyleSheet(STYLE)

        root = QWidget()
        root.setObjectName("root")
        stack = QStackedWidget()
        self._stack = stack
        layout = QVBoxLayout(root)
        layout.setContentsMargins(24, 20, 24, 24)
        layout.addWidget(stack)
        self.window.setCentralWidget(root)

        loading = QWidget()
        loading.setObjectName("loading")
        load_layout = QVBoxLayout(loading)
        load_layout.addStretch()
        mark = QLabel("AG")
        mark.setObjectName("mark")
        mark.setFixedSize(74, 74)
        load_text = QLabel("正在检查治理项目...")
        load_text.setObjectName("mute")
        load_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._loading_text = load_text
        load_layout.addWidget(mark, alignment=Qt.AlignmentFlag.AlignHCenter)
        load_layout.addWidget(load_text)
        load_layout.addStretch()

        main = QWidget()
        main_layout = QVBoxLayout(main)
        main_layout.setSpacing(12)
        bar = QFrame()
        bar.setObjectName("bar")
        bar.setFixedHeight(52)
        bar_row = QHBoxLayout(bar)
        identity = QLabel("AG")
        identity.setObjectName("mark")
        identity.setFixedSize(32, 32)
        title = QLabel("AutoGovern2Code")
        title.setObjectName("title")
        self._status = QLabel("正在检查项目")
        self._status.setObjectName("mute")
        refresh = QPushButton("刷新")
        add = QPushButton("添加项目")
        add.setProperty("primary", True)
        refresh.clicked.connect(self.refresh_projects)
        add.clicked.connect(self.choose_project)
        bar_row.addWidget(identity)
        bar_row.addWidget(title)
        bar_row.addWidget(self._status, 1)
        bar_row.addWidget(refresh)
        bar_row.addWidget(add)

        self._projects = QListWidget()
        self._projects.setMinimumHeight(88)
        self._projects.setMaximumHeight(120)
        self._projects.currentItemChanged.connect(lambda *_: self.load_selected())

        detail = QFrame()
        detail.setObjectName("detail")
        detail_layout = QVBoxLayout(detail)
        head = QHBoxLayout()
        self._detail_name = QLabel("选择一个项目")
        self._detail_name.setObjectName("title")
        self._open_folder = QPushButton("打开文件夹")
        self._check = QPushButton("重新检查")
        self._stop = QPushButton("停止治理")
        self._stop.setProperty("danger", True)
        self._resume = QPushButton("恢复治理")
        self._uninstall = QPushButton("卸载项目")
        self._open_folder.clicked.connect(self.open_folder)
        self._check.clicked.connect(lambda: self.post_project("api/projects/check"))
        self._stop.clicked.connect(lambda: self.confirm_post("停止治理后，这个仓库不再被 AG2C 拦截提交。证据还在。", "api/projects/remove"))
        self._resume.clicked.connect(lambda: self.post_project("api/projects/resume"))
        self._uninstall.clicked.connect(lambda: self.confirm_post("卸载项目会删除这份治理档案，不能恢复。仓库源码不会被删。", "api/projects/uninstall"))
        head.addWidget(self._detail_name, 1)
        for button in (self._open_folder, self._check, self._stop, self._resume, self._uninstall):
            head.addWidget(button)
        self._detail_path = QLabel()
        self._detail_path.setObjectName("mute")
        self._detail_health = QLabel("尚未加载")
        self._issues = QLabel()
        self._issues.setObjectName("issues")
        self._issues.hide()

        tools = QHBoxLayout()
        tools.addWidget(QLabel("找文件"))
        self._search = QLineEdit()
        self._search.setPlaceholderText("frontend、css、文件名或知识卡")
        self._search.textChanged.connect(self.render_coverage)
        self._filter = QComboBox()
        for flag, label in FILTERS:
            self._filter.addItem(label, flag)
        self._filter.currentIndexChanged.connect(self.render_coverage)
        expand = QPushButton("展开全部")
        expand.clicked.connect(lambda: self._tree.expandAll())
        tools.addWidget(self._search, 1)
        tools.addWidget(self._filter)
        tools.addWidget(expand)

        split = QSplitter()
        self._tree = QTreeWidget()
        self._tree.setHeaderLabel("项目文件树")
        self._tree.itemSelectionChanged.connect(self.inspect_tree)
        self._cards = QListWidget()
        self._cards.setObjectName("cards")
        self._cards.currentItemChanged.connect(lambda *_: self.inspect_card())
        inspector = QWidget()
        form = QFormLayout(inspector)
        self._inspect_title = QLabel("点文件树或右边的知识卡")
        self._inspect_status = QLabel()
        self._inspect_status.setObjectName("mute")
        self._inspect_summary = QLabel()
        self._inspect_summary.setWordWrap(True)
        self._inspect_who = QLabel("—")
        self._inspect_floors = QLabel("—")
        self._inspect_when = QLabel("—")
        self._inspect_role = QLabel("—")
        self._inspect_path = QLabel("—")
        self._inspect_path.setWordWrap(True)
        form.addRow(self._inspect_title)
        form.addRow(self._inspect_status)
        form.addRow(self._inspect_summary)
        form.addRow("谁管理", self._inspect_who)
        form.addRow("属于哪几个楼层", self._inspect_floors)
        form.addRow("最近一次提交", self._inspect_when)
        form.addRow("现在是不是多余的", self._inspect_role)
        form.addRow("路径", self._inspect_path)
        cards_wrap = QWidget()
        cards_layout = QVBoxLayout(cards_wrap)
        cards_layout.setContentsMargins(0, 0, 0, 0)
        cards_layout.addWidget(QLabel("知识卡片"))
        cards_layout.addWidget(self._cards)
        split.addWidget(self._tree)
        split.addWidget(cards_wrap)
        split.addWidget(inspector)
        split.setStretchFactor(0, 4)
        split.setStretchFactor(1, 3)
        split.setStretchFactor(2, 3)

        detail_layout.addLayout(head)
        detail_layout.addWidget(self._detail_path)
        detail_layout.addWidget(self._detail_health)
        detail_layout.addWidget(self._issues)
        detail_layout.addLayout(tools)
        detail_layout.addWidget(split, 1)
        main_layout.addWidget(bar)
        main_layout.addWidget(self._projects)
        main_layout.addWidget(detail, 1)

        stack.addWidget(loading)
        stack.addWidget(main)
        stack.setCurrentIndex(0)

        tray = QSystemTrayIcon(icon, self.window)
        menu = QMenu()
        open_action = QAction("打开 AutoGovern2Code", self.window)
        open_action.triggered.connect(self.show_window)
        add_action = QAction("添加项目...", self.window)
        add_action.triggered.connect(self.choose_project)
        check_action = QAction("检查所有项目", self.window)
        check_action.triggered.connect(self.refresh_projects)
        exit_action = QAction("退出管理界面", self.window)
        exit_action.triggered.connect(self.quit)
        menu.addAction(open_action)
        menu.addAction(add_action)
        menu.addAction(check_action)
        if not self._portable and self._frozen:
            menu.addSeparator()
            startup = QAction("登录 Windows 后启动", self.window)
            startup.setCheckable(True)
            startup.setChecked(startup_enabled())
            startup.toggled.connect(lambda checked: apply_startup(checked, sys.executable))
            menu.addAction(startup)
        menu.addSeparator()
        menu.addAction(exit_action)
        tray.setContextMenu(menu)
        tray.setToolTip("AutoGovern2Code — 双击打开")
        tray.activated.connect(lambda reason: self.show_window() if reason == QSystemTrayIcon.ActivationReason.DoubleClick else None)
        tray.show()
        self._tray = tray

        QTimer.singleShot(0, self.start_backend)

    def show(self) -> None:
        self.window.show()

    def show_window(self) -> None:
        self.window.show()
        self.window.setWindowState(self.window.windowState() & ~self._Qt.WindowState.WindowMinimized)
        self.window.raise_()
        self.window.activateWindow()

    def quit(self) -> None:
        self._really_exit = True
        self.window.close()

    def _close_event(self, event) -> None:
        if not self._really_exit:
            event.ignore()
            self.window.hide()
            if not tray_hint_shown():
                self._tray.showMessage("AutoGovern2Code 还在运行", "窗口已放到右下角托盘。")
                mark_tray_hint_shown()
            return
        if self._api is not None:
            stop_desktop_server(self._api, self._process)
        event.accept()
        from PySide6.QtWidgets import QApplication

        QApplication.quit()

    def fail(self, message: str) -> None:
        self._loading_text.setText(message)
        self._stack.setCurrentIndex(0)
        self._QMessageBox.warning(self.window, "AutoGovern2Code", message)

    def start_backend(self) -> None:
        command = runtime_command(self._args, self._app_dir)
        runtime = Path(command[0])
        if runtime.suffix.lower() == ".exe" and not runtime.is_file():
            self.fail("找不到 AG2C 治理核心：" + str(runtime))
            return
        port = free_port()
        extra = portable_env(self._app_dir) if self._portable else None
        try:
            self._process = start_desktop_server(command, port, self._token, extra)
        except OSError as exc:
            self.fail("无法启动 AG2C 本地服务：" + str(exc))
            return
        self._api = DesktopApi(f"http://127.0.0.1:{port}/", self._token)
        if not wait_for_status(self._api):
            self.fail("AG2C 本地服务启动超时。")
            return
        self._stack.setCurrentIndex(1)
        self.refresh_projects()

    def refresh_projects(self) -> None:
        if self._busy or self._api is None:
            return
        self._busy = True
        self._status.setText("正在刷新")
        try:
            self._api.request("POST", "api/projects/align", {})
            payload = self._api.request("GET", "api/projects")
            current = self._selected_root()
            self._projects.clear()
            rows = payload.get("projects") if isinstance(payload.get("projects"), list) else []
            selected_row = 0
            for index, raw in enumerate(rows):
                if not isinstance(raw, dict):
                    continue
                item = self._QListWidgetItem(f"{text(raw, 'name')}    {state_label(text(raw, 'state'))}")
                item.setData(self._Qt.ItemDataRole.UserRole, raw)
                item.setToolTip(text(raw, "root"))
                self._projects.addItem(item)
                if current and text(raw, "root") == current:
                    selected_row = index
            count = self._projects.count()
            self._status.setText("还没有治理项目" if count == 0 else f"已接入 {count} 个项目")
            if count:
                self._projects.setCurrentRow(selected_row)
        except Exception as exc:
            self._status.setText(str(exc))
        finally:
            self._busy = False

    def _selected_root(self) -> str:
        item = self._projects.currentItem()
        if item is None:
            return ""
        row = item.data(self._Qt.ItemDataRole.UserRole)
        return text(row, "root") if isinstance(row, dict) else ""

    def _selected_project(self) -> dict[str, Any] | None:
        item = self._projects.currentItem()
        if item is None:
            return None
        row = item.data(self._Qt.ItemDataRole.UserRole)
        return row if isinstance(row, dict) else None

    def load_selected(self) -> None:
        project = self._selected_project()
        if not project or self._api is None:
            return
        state = text(project, "state")
        self._detail_name.setText(text(project, "name"))
        self._detail_path.setText(text(project, "root"))
        self._detail_health.setText(state_label(state))
        issues = string_list(project, "issues")
        if issues:
            self._issues.setText("！  " + "；".join(issues))
            self._issues.show()
        else:
            self._issues.hide()
        governance = text(project, "governance")
        self._stop.setEnabled(governance != "stopped")
        self._resume.setEnabled(governance == "stopped")
        try:
            self._details = self._api.request("POST", "api/project/details", {"path": text(project, "root")})
            self.render_coverage()
        except Exception as exc:
            self._show_inspect({"title": "无法加载详情", "status": str(exc), "summary": "", "who": "—", "floors": "—", "when": "—", "role": "—", "path": "—"})

    def render_coverage(self) -> None:
        query = self._search.text()
        flag = str(self._filter.currentData() or "")
        files, cards, headline = coverage_rows(self._details, query, flag)
        self._tree.clear()
        self._cards.clear()
        folders: dict[str, Any] = {}
        for rel, node in files:
            parent = None
            prefix = ""
            for part in rel.split("/"):
                prefix = part if not prefix else prefix + "/" + part
                if prefix not in folders:
                    item = self._QTreeWidgetItem([part])
                    item.setData(0, self._Qt.ItemDataRole.UserRole, node)
                    if parent is None:
                        self._tree.addTopLevelItem(item)
                    else:
                        parent.addChild(item)
                    folders[prefix] = item
                parent = folders[prefix]
        self._tree.expandAll()
        for node in cards:
            title = text(node, "title") or text(node, "id")
            status = first_flag_label(node)
            item = self._QListWidgetItem(title if not status else f"{title}  ·  {status}")
            item.setData(self._Qt.ItemDataRole.UserRole, node)
            self._cards.addItem(item)
        self._show_inspect(
            {
                "title": "点文件树或右边的知识卡",
                "status": headline,
                "summary": "",
                "who": "—",
                "floors": "—",
                "when": "—",
                "role": "—",
                "path": "—",
            }
        )

    def inspect_tree(self) -> None:
        items = self._tree.selectedItems()
        if not items:
            return
        node = items[0].data(0, self._Qt.ItemDataRole.UserRole)
        if isinstance(node, dict):
            self._show_inspect(inspect_fields(node))

    def inspect_card(self) -> None:
        item = self._cards.currentItem()
        if item is None:
            return
        node = item.data(self._Qt.ItemDataRole.UserRole)
        if isinstance(node, dict):
            self._show_inspect(inspect_fields(node))

    def _show_inspect(self, fields: dict[str, str]) -> None:
        self._inspect_title.setText(fields.get("title") or "点文件树或右边的知识卡")
        self._inspect_status.setText(fields.get("status") or "")
        self._inspect_summary.setText(fields.get("summary") or "")
        self._inspect_who.setText(fields.get("who") or "—")
        self._inspect_floors.setText(fields.get("floors") or "—")
        self._inspect_when.setText(fields.get("when") or "—")
        self._inspect_role.setText(fields.get("role") or "—")
        self._inspect_path.setText(fields.get("path") or "—")

    def choose_project(self) -> None:
        self.show_window()
        path = self._QFileDialog.getExistingDirectory(self.window, "选择要纳入 AutoGovern2Code 治理的 Git 项目")
        if not path or self._api is None:
            return
        try:
            self._api.request("POST", "api/projects/add", {"path": path})
        except Exception as exc:
            self._QMessageBox.warning(self.window, "AutoGovern2Code", str(exc))
        self.refresh_projects()

    def post_project(self, path: str) -> None:
        project = self._selected_project()
        if not project or self._api is None:
            return
        try:
            self._api.request("POST", path, {"path": text(project, "root")})
        except Exception as exc:
            self._QMessageBox.warning(self.window, "AutoGovern2Code", str(exc))
        self.refresh_projects()

    def confirm_post(self, message: str, path: str) -> None:
        if self._QMessageBox.warning(self.window, "AutoGovern2Code", message, self._QMessageBox.StandardButton.Ok | self._QMessageBox.StandardButton.Cancel) != self._QMessageBox.StandardButton.Ok:
            return
        self.post_project(path)

    def open_folder(self) -> None:
        import os
        import subprocess

        project = self._selected_project()
        if not project:
            return
        root = text(project, "root")
        if not root or not Path(root).is_dir():
            return
        if os.name == "nt":
            subprocess.Popen(["explorer.exe", root])


def _app_icon(QPixmap, QPainter, QColor, QIcon, Qt):
    pixmap = QPixmap(32, 32)
    pixmap.fill(QColor(37, 99, 235))
    painter = QPainter(pixmap)
    painter.setPen(QColor(255, 255, 255))
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "AG")
    painter.end()
    return QIcon(pixmap)
