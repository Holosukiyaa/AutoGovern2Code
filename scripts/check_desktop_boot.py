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
import time
import urllib.error
import urllib.request
from pathlib import Path

READY_TIMEOUT_S = 30.0
POLL_INTERVAL_S = 0.25


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
            tail = (process.stderr.read() if process.stderr else b"").decode("utf-8", "replace")[-500:]
            raise SystemExit(f"FAIL: desktop server exited early with code {process.returncode}: {tail}")
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                return json.loads(response.read().decode("utf-8"))
        except (OSError, urllib.error.URLError):
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
        stderr=subprocess.PIPE,
    )
    try:
        payload = _wait_ready(port, process)
        if payload.get("status") != "ready":
            print(f"FAIL: /api/status answered but status={payload.get('status')!r}")
            return 1
        _shutdown(port, token)
        process.wait(timeout=10)
        print(f"OK: desktop server booted on 127.0.0.1:{port}, answered /api/status, shut down cleanly")
        return 0
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=10)


if __name__ == "__main__":
    raise SystemExit(main())
