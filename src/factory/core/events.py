"""Tiny event bus. Every step start/finish and LLM call is an event, so observability
(console, JSONL file today; dashboards tomorrow) is a subscriber, not step code."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any, Callable

Event = dict[str, Any]


class EventBus:
    def __init__(self) -> None:
        self._subs: list[Callable[[Event], None]] = []

    def subscribe(self, fn: Callable[[Event], None]) -> None:
        self._subs.append(fn)

    def emit(self, type: str, **data: Any) -> None:
        event = {"ts": round(time.time(), 3), "type": type, **data}
        for fn in self._subs:
            fn(event)


class JsonlSink:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def __call__(self, event: Event) -> None:
        with self._lock, self.path.open("a") as f:
            f.write(json.dumps(event, default=str) + "\n")


class ConsoleSink:
    _ICON = {"ok": "✓", "failed": "✗", "skipped": "·", "discarded": "⊘"}

    def __init__(self) -> None:
        self._lock = threading.Lock()

    def __call__(self, event: Event) -> None:
        if event["type"] != "step_finished":
            return
        icon = self._ICON.get(event["status"], "?")
        msg = (event.get("message") or "").splitlines()[:1]
        line = (
            f"  {icon} {event['job']:<22} {event['step']:<12} "
            f"{event['status']:<9} {event['duration_s']:>5.2f}s  {msg[0][:70] if msg else ''}"
        )
        with self._lock:
            print(line, flush=True)
