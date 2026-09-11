"""Windows clipboard lock probe for gui tests. Never patches imgui_bundle."""

from __future__ import annotations

import sys
import threading
import time
import unittest

CLIPBOARD_LOCK_RETRIES = 5
CLIPBOARD_LOCK_WAIT_S = 2.0
CLIPBOARD_LOCKED_MARK = "clipboard-locked"


def _user32():
    if sys.platform != "win32":
        return None
    import ctypes

    return ctypes.windll.user32


def clipboard_unlocked(
    *,
    retries: int = CLIPBOARD_LOCK_RETRIES,
    wait_s: float = CLIPBOARD_LOCK_WAIT_S,
) -> bool:
    """True if OpenClipboard/CloseClipboard succeeds after a short retry window."""
    user32 = _user32()
    if user32 is None:
        return True
    attempts = max(1, int(retries))
    delay = max(0.0, float(wait_s))
    for index in range(attempts):
        if user32.OpenClipboard(None):
            user32.CloseClipboard()
            return True
        if index + 1 < attempts and delay:
            time.sleep(delay)
    return False


def require_clipboard(
    *,
    retries: int = CLIPBOARD_LOCK_RETRIES,
    wait_s: float = CLIPBOARD_LOCK_WAIT_S,
) -> None:
    """Skip with a grep-able clipboard-locked reason when the lock will not yield."""
    if clipboard_unlocked(retries=retries, wait_s=wait_s):
        return
    message = (
        f"{CLIPBOARD_LOCKED_MARK}: another process holds the Windows clipboard; "
        "imgui clipboard test skipped"
    )
    print(message, flush=True)
    raise unittest.SkipTest(message)


class ClipboardLock:
    """Hold OpenClipboard on a side thread so the test thread sees ACCESS_DENIED."""

    def __init__(self) -> None:
        self.held = False
        self._started = threading.Event()
        self._release = threading.Event()
        self._thread: threading.Thread | None = None

    def __enter__(self) -> "ClipboardLock":
        user32 = _user32()
        if user32 is None:
            self._started.set()
            return self

        def _hold() -> None:
            if not user32.OpenClipboard(None):
                self._started.set()
                return
            self.held = True
            self._started.set()
            self._release.wait(timeout=30)
            user32.CloseClipboard()
            self.held = False

        self._thread = threading.Thread(target=_hold, daemon=True)
        self._thread.start()
        self._started.wait(timeout=5)
        return self

    def release(self) -> None:
        self._release.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def __exit__(self, *exc: object) -> None:
        self.release()
