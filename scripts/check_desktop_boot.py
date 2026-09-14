"""Product boot check: the desktop backend must come up and answer /api/status.

Scenario checker attached to knowledge.ag2c-desktop. Spawns
`python -m ag2c desktop serve` on a free loopback port, polls /api/status
until the server reports ready, then shuts it down through /api/shutdown.
Exit 0 on success, non-zero on any failure.
"""
from __future__ import annotations

import json
import os
import secrets
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

READY_TIMEOUT_S = 20.0
POLL_INTERVAL_S = 0.25
HARD_EXIT_S = 25.0


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _wait_ready(port: int, process: subprocess.Popen) -> dict:
    deadline = time.monotonic() + READY_TIMEOUT_S
    url = f"http://127.0.0.1:{port}/api/status"
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise SystemExit(f"FAIL: desktop server exited early with code {process.returncode}")
        try:
            probe = socket.create_connection(("127.0.0.1", port), timeout=0.4)
            probe.close()
        except OSError:
            time.sleep(POLL_INTERVAL_S)
            continue
        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                return json.loads(response.read().decode("utf-8"))
        except (OSError, urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            time.sleep(POLL_INTERVAL_S)
    raise SystemExit(f"FAIL: desktop server did not answer /api/status within {READY_TIMEOUT_S:.0f}s")


def _shutdown(port: int, token: str) -> None:
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/shutdown",
        data=b"{}",
        headers={"X-AG2C-Token": token, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        urllib.request.urlopen(request, timeout=5).read()
    except OSError:
        pass  # the server may close the connection without a body


def main() -> int:
    def _hard_exit() -> None:
        sys.stderr.write("FAIL: desktop boot probe hard-exit after 25s without /api/status\n")
        sys.stderr.flush()
        os._exit(2)

    watchdog = threading.Timer(HARD_EXIT_S, _hard_exit)
    watchdog.daemon = True
    watchdog.start()
    root = _repo_root()
    port = _free_port()
    token = secrets.token_hex(16)  # 32 chars, satisfies the >=24 rule
    env = dict(os.environ)
    src = str(root / "src")
    env["PYTHONPATH"] = src + os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else src
    process = subprocess.Popen(
        [sys.executable, "-B", "-m", "ag2c", "desktop", "serve", "--port", str(port), "--token", token],
        cwd=str(root),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        payload = _wait_ready(port, process)
        if payload.get("status") != "ready":
            print(f"FAIL: /api/status answered but status={payload.get('status')!r}")
            return 1
        ui_url = f"http://127.0.0.1:{port}/ui/"
        with urllib.request.urlopen(ui_url, timeout=2) as response:
            page = response.read().decode("utf-8")
            if response.status != 200:
                print(f"FAIL: GET /ui/ status={response.status}")
                return 1
        if 'id="ops"' not in page:
            print("FAIL: GET /ui/ did not contain id=ops")
            return 1
        _shutdown(port, token)
        process.wait(timeout=3)
        print(f"OK: desktop server booted on 127.0.0.1:{port}, answered /api/status and /ui/, shut down cleanly")
        return 0
    finally:
        watchdog.cancel()
        if process.poll() is None:
            process.kill()
            process.wait(timeout=3)


if __name__ == "__main__":
    raise SystemExit(main())
