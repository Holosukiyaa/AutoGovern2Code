"""托管模式：市长只剩看 / 否 / 授。不是 L0 总闸，也不是停止治理。"""
from __future__ import annotations

from typing import Any

from .dashboard import DECISION, MUTED, NOTICE, OK_DIM

_FLAGS = (
    ("auto_settle", "结算"),
    ("auto_census", "普查认领"),
    ("auto_warning", "良性警告认领"),
)
_WATCH = {"settle": "自动结算", "census": "自动普查认领", "warning": "自动认领警告"}
_IRREVERSIBLE = "合并、删除、放弃永不代理"


def custody_model(details: dict[str, Any] | None) -> dict[str, Any]:
    """Pure assembly for 托管 mode. Garbage input degrades to 未托管 empty."""
    blob = details if isinstance(details, dict) else {}
    project = blob.get("project") if isinstance(blob.get("project"), dict) else {}
    name = str(project.get("name") or "").strip()
    proxy = blob.get("proxy") if isinstance(blob.get("proxy"), dict) else {}
    flags: list[dict[str, Any]] = []
    granted = False
    for fid, label in _FLAGS:
        on = proxy.get(fid) is True
        granted = granted or on
        flags.append({"id": fid, "label": label, "on": on})
    watch: list[dict[str, str]] = []
    for item in proxy.get("recent") or []:
        if not isinstance(item, dict):
            continue
        rule = str(item.get("rule") or "")
        watch.append({"rule": rule, "text": _WATCH.get(rule, rule or "代理决定"), "at": str(item.get("occurred_at") or "")})
    audit = blob.get("audit") if isinstance(blob.get("audit"), dict) else {}
    veto: list[dict[str, str]] = []
    for item in audit.get("pending") or []:
        if isinstance(item, dict):
            veto.append({"id": str(item.get("id") or ""), "question": str(item.get("question") or "")})
    return {
        "project": name,
        "empty": not bool(name),
        "headline": "托管中" if granted else "未托管",
        "granted": granted,
        "flags": flags,
        "watch": watch,
        "veto": veto,
        "irreversible": _IRREVERSIBLE,
    }


def home_custody_open(state: Any) -> bool:
    """Dedicated 托管 button on 首页. Not a drawer, not 停止治理."""
    from imgui_bundle import imgui
    from .imgui_tray import audit

    with state.lock:
        open_custody = bool(state.custody_open)
    pushed = 0
    if open_custody:
        imgui.push_style_color(imgui.Col_.button, (0.28, 0.50, 0.78, 0.70))
        imgui.push_style_color(imgui.Col_.button_hovered, (0.32, 0.56, 0.84, 0.85))
        pushed = 2
    clicked = imgui.small_button("托管")
    if pushed:
        imgui.pop_style_color(pushed)
    if clicked:
        with state.lock:
            state.custody_open = not state.custody_open
            open_custody = bool(state.custody_open)
        audit(state, ("打开" if open_custody else "关闭") + "托管", "首页", "")
    imgui.same_line()
    imgui.text_disabled("看 · 否 · 授" if open_custody else "需要你处理")
    return open_custody


def draw_custody(model: dict[str, Any]) -> list[tuple[str, bool]]:
    """Render 看/否/授. Returns clicks: (flag, on) or ('audit-ack', True)."""
    from imgui_bundle import imgui

    clicks: list[tuple[str, bool]] = []
    if model.get("empty"):
        imgui.text_disabled("先选择一个项目，再谈托管。")
        return clicks
    imgui.text_disabled(str(model.get("project") or ""))
    color = OK_DIM if model.get("granted") else DECISION
    imgui.text_colored(color, str(model.get("headline") or "未托管"))
    imgui.text_disabled("市长只做三件事：看代理在做什么、否决、授新权。")
    imgui.text_disabled(str(model.get("irreversible") or _IRREVERSIBLE))
    imgui.separator()
    imgui.text_colored(NOTICE, "看")
    watch = model.get("watch") or []
    if watch:
        for item in watch:
            imgui.bullet_text(str(item.get("text") or "代理决定"))
    else:
        imgui.text_disabled("还没有代理决定")
    imgui.separator()
    imgui.text_colored(DECISION, "否")
    veto = model.get("veto") or []
    if veto:
        for item in veto:
            imgui.bullet_text(f"{item.get('id') or ''} — {item.get('question') or ''}")
        if imgui.small_button("已抽查##custody"):
            clicks.append(("audit-ack", True))
    else:
        imgui.text_disabled("没有待否决的抽查")
    imgui.separator()
    imgui.text_colored(MUTED, "授")
    for item in model.get("flags") or []:
        fid = str(item.get("id") or "")
        label = str(item.get("label") or fid)
        on = bool(item.get("on"))
        imgui.text(f"{label} · {'已授' if on else '未授'}")
        imgui.same_line()
        if on:
            if imgui.small_button(f"收回##{fid}"):
                clicks.append((fid, False))
        else:
            if imgui.small_button(f"授##{fid}"):
                clicks.append((fid, True))
    return clicks


def apply_custody_clicks(state: Any, clicks: list[tuple[str, bool]]) -> None:
    if not clicks:
        return
    from .imgui_tray import _post, _refresh

    with state.lock:
        root = state.selected_root
    if not root:
        return
    for flag, on in clicks:
        if flag == "audit-ack":
            state.run_job(lambda: _post(state, "api/project/audit-ack", root))
            continue

        def job(flag: str = flag, on: bool = on, path: str = root) -> None:
            if state.api is None:
                return
            state.api.request(
                "POST",
                "api/project/proxy",
                {"path": path, "flag": flag, "on": on, "reason": "mayor 授 from 托管"},
            )
            _refresh(state)

        state.run_job(job)
