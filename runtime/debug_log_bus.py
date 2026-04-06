from __future__ import annotations

import asyncio
import threading
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Deque, Dict, List, Optional, Tuple


@dataclass
class DebugLogEntry:
    id: int
    timestamp: str
    level: str
    logger: str
    message: str
    service: str
    channel_id: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "timestamp": self.timestamp,
            "level": self.level,
            "logger": self.logger,
            "message": self.message,
            "service": self.service,
            "channel_id": self.channel_id,
        }


class DebugLogBus:
    def __init__(self, capacity: int = 1000) -> None:
        self._lock = threading.Lock()
        self._buffer: Deque[DebugLogEntry] = deque(maxlen=max(100, int(capacity)))
        self._seq = 0
        self._subscribers: List[Tuple[asyncio.AbstractEventLoop, asyncio.Queue[DebugLogEntry]]] = []

    def subscribe(self, loop: asyncio.AbstractEventLoop) -> "asyncio.Queue[DebugLogEntry]":
        """Register an async subscriber queue. Call from the async event loop."""
        queue: asyncio.Queue[DebugLogEntry] = asyncio.Queue(maxsize=512)
        with self._lock:
            self._subscribers.append((loop, queue))
        return queue

    def unsubscribe(self, queue: "asyncio.Queue[DebugLogEntry]") -> None:
        """Remove a subscriber queue."""
        with self._lock:
            self._subscribers = [(lp, q) for lp, q in self._subscribers if q is not queue]

    def publish(self, *, level: str, logger_name: str, message: str, service: str, channel_id: Optional[int]) -> DebugLogEntry:
        with self._lock:
            self._seq += 1
            entry = DebugLogEntry(
                id=self._seq,
                timestamp=datetime.now(timezone.utc).isoformat(),
                level=level,
                logger=logger_name,
                message=message,
                service=service,
                channel_id=channel_id,
            )
            self._buffer.append(entry)
            dead: List[Tuple[asyncio.AbstractEventLoop, asyncio.Queue[DebugLogEntry]]] = []
            for loop, queue in self._subscribers:
                try:
                    loop.call_soon_threadsafe(queue.put_nowait, entry)
                except RuntimeError:
                    dead.append((loop, queue))
            for item in dead:
                self._subscribers.remove(item)
        return entry

    def snapshot(self, *, limit: int = 200) -> List[Dict[str, Any]]:
        with self._lock:
            items = list(self._buffer)[-max(1, min(2000, int(limit))):]
            return [item.to_dict() for item in items]

    def snapshot_after(self, last_id: int) -> List[DebugLogEntry]:
        """Return buffered entries with id > last_id (no blocking)."""
        with self._lock:
            return [item for item in self._buffer if item.id > last_id]
