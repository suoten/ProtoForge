import asyncio
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine


@dataclass
class LogEntry:
    timestamp: float
    protocol: str
    direction: str
    device_id: str
    message_type: str
    summary: str
    detail: dict[str, Any] = field(default_factory=dict)


class LogBus:
    def __init__(self, max_entries: int = 10000):
        self._entries: deque[LogEntry] = deque(maxlen=max_entries)
        self._subscribers: list[asyncio.Queue] = []
        self._callbacks: list[Callable[[LogEntry], Coroutine]] = []
        self._dropped_count: int = 0

    def emit(self, protocol: str, direction: str, device_id: str,
             message_type: str, summary: str, detail: dict[str, Any] | None = None) -> None:
        entry = LogEntry(
            timestamp=time.time(),
            protocol=protocol,
            direction=direction,
            device_id=device_id,
            message_type=message_type,
            summary=summary,
            detail=detail or {},
        )
        self._entries.append(entry)
        for queue in self._subscribers:
            try:
                queue.put_nowait(entry)
            except asyncio.QueueFull:
                self._dropped_count += 1
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                queue.put_nowait(entry)

    def subscribe(self, queue: asyncio.Queue | None = None) -> asyncio.Queue:
        if queue is None:
            queue = asyncio.Queue(maxsize=1000)
        self._subscribers.append(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        if queue in self._subscribers:
            self._subscribers.remove(queue)

    def get_recent(self, count: int = 100, protocol: str | None = None,
                   device_id: str | None = None) -> list[dict[str, Any]]:
        entries = list(self._entries)
        if protocol:
            entries = [e for e in entries if e.protocol == protocol]
        if device_id:
            entries = [e for e in entries if e.device_id == device_id]
        entries = entries[-count:]
        return [
            {
                "timestamp": e.timestamp,
                "protocol": e.protocol,
                "direction": e.direction,
                "device_id": e.device_id,
                "message_type": e.message_type,
                "summary": e.summary,
                "detail": e.detail,
            }
            for e in entries
        ]

    def clear(self) -> None:
        self._entries.clear()
