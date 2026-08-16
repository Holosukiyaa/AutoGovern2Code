from __future__ import annotations

import json
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .errors import LedgerError
from .util import canonical_json, digest_json

EVENT_SCHEMA = "ag2c.ledger.event.v1"
ZERO_DIGEST = "0" * 64


@contextmanager
def _exclusive_lock(path: Path) -> Iterator[None]:
    lock_path = path.with_suffix(path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as handle:
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _read_events(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise LedgerError(f"invalid ledger JSON at line {line_number}: {exc}") from exc
        if not isinstance(value, dict):
            raise LedgerError(f"ledger event at line {line_number} must be an object")
        events.append(value)
    return events


def verify_ledger(path: Path) -> list[str]:
    if not path.exists():
        return []
    try:
        events = _read_events(path)
    except (OSError, LedgerError) as exc:
        return [str(exc)]
    errors: list[str] = []
    previous = ZERO_DIGEST
    for index, event in enumerate(events, 1):
        if event.get("schema") != EVENT_SCHEMA:
            errors.append(f"event {index} has an unsupported schema")
        if event.get("sequence") != index:
            errors.append(f"event {index} has an invalid sequence")
        if event.get("previous_digest") != previous:
            errors.append(f"event {index} breaks the hash chain")
        recorded = str(event.get("event_digest", ""))
        unsigned = dict(event)
        unsigned.pop("event_digest", None)
        actual = digest_json(unsigned)
        if recorded != actual:
            errors.append(f"event {index} digest mismatch")
        previous = recorded
    return errors


def append_event(path: Path, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    with _exclusive_lock(path):
        errors = verify_ledger(path)
        if errors:
            raise LedgerError("refusing to append to an invalid ledger:\n- " + "\n- ".join(errors))
        events = _read_events(path)
        previous = str(events[-1]["event_digest"]) if events else ZERO_DIGEST
        event: dict[str, Any] = {
            "schema": EVENT_SCHEMA,
            "sequence": len(events) + 1,
            "occurred_at": datetime.now(timezone.utc).isoformat(),
            "event_type": event_type,
            "previous_digest": previous,
            "payload": payload,
        }
        event["event_digest"] = digest_json(event)
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(canonical_json(event) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        return event


def ledger_summary(path: Path) -> dict[str, Any]:
    errors = verify_ledger(path)
    if errors:
        raise LedgerError("cannot summarize an invalid ledger:\n- " + "\n- ".join(errors))
    events = _read_events(path)
    counts: dict[str, int] = {}
    for event in events:
        event_type = str(event.get("event_type", "unknown"))
        counts[event_type] = counts.get(event_type, 0) + 1
    return {
        "schema": EVENT_SCHEMA,
        "events": len(events),
        "event_types": dict(sorted(counts.items())),
        "head_digest": events[-1]["event_digest"] if events else ZERO_DIGEST,
    }


def read_events(path: Path) -> list[dict[str, Any]]:
    errors = verify_ledger(path)
    if errors:
        raise LedgerError("cannot read an invalid ledger:\n- " + "\n- ".join(errors))
    return _read_events(path)
