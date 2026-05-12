from __future__ import annotations

import json
import threading
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class BrokerEvent:
    ts: str
    event: str
    order_id: str | None = None
    symbol: str = ""
    direction: str = ""
    qty: int = 0
    strike: int = 0
    price: float | None = None
    provider: str = ""
    note: str = ""


class JsonlCaptureWriter:
    """Append broker/order events for later replay and RCA."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._lock = threading.Lock()
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, event: BrokerEvent | dict[str, Any]) -> None:
        payload = asdict(event) if isinstance(event, BrokerEvent) else dict(event)
        line = json.dumps(payload, ensure_ascii=True)
        with self._lock:
            with self._path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")

    @property
    def path(self) -> Path:
        return self._path
