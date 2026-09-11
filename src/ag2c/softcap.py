"""文件软帽：src/ag2c 单文件行数仪表。只警告不硬化。

房间预算量总量（GDP）；本模块量单文件肥胖（基尼）。阈值 800 行来自交接
定稿：超过单次注意力容量后交互 bug 滋生。kind 刻意不进
checks.ESCALATABLE_KINDS——发现层先观察，拆分原语是后续任务。
"""
from __future__ import annotations

from pathlib import Path

from .model import Manifest

SOFTCAP_LINES = 800
SOFTCAP_WARNING_KIND = "file-soft-cap"
SOFTCAP_ROOT = Path("src") / "ag2c"


def file_soft_cap_warnings(manifest: Manifest) -> list[dict[str, str]]:
    """扫描 src/ag2c 下 *.py，splitlines() > 800 的各出一条警告。读失败跳过。"""
    root = manifest.project_root.resolve()
    base = (root / SOFTCAP_ROOT)
    if not base.is_dir():
        return []
    warnings: list[dict[str, str]] = []
    for path in sorted(base.rglob("*.py")):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        lines = len(text.splitlines())
        if lines <= SOFTCAP_LINES:
            continue
        try:
            rel = path.resolve().relative_to(root).as_posix()
        except ValueError:
            continue
        warnings.append({
            "kind": SOFTCAP_WARNING_KIND,
            "key": f"{SOFTCAP_WARNING_KIND}:{rel}",
            "detail": f"{rel} {lines} 行，软帽 {SOFTCAP_LINES}（超出 {lines - SOFTCAP_LINES}）",
            "path": rel,
            "lines": str(lines),
        })
    return warnings
