import asyncio
import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine

logger = logging.getLogger(__name__)


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
        self._last_drop_warning: float = 0.0
        self._lock = threading.Lock()  # FIXED: 添加锁保护，避免并发emit/subscribe/unsubscribe竞态

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
        with self._lock:  # FIXED: 添加锁保护，避免并发emit/subscribe竞态
            self._entries.append(entry)
            queues = list(self._subscribers)
        for queue in queues:
            try:
                queue.put_nowait(entry)
            except asyncio.QueueFull:
                with self._lock:  # FIXED: 添加锁保护dropped_count
                    self._dropped_count += 1
                    dropped_count = self._dropped_count
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty as e:
                    logger.debug("Queue already empty when discarding oldest entry: %s", e)
                try:
                    queue.put_nowait(entry)
                except asyncio.QueueFull as e:
                    logger.debug("Queue still full after discarding oldest entry: %s", e)
                now = time.time()
                if now - self._last_drop_warning > 60:
                    self._last_drop_warning = now
                    logger.warning("LogBus dropped %d entries (subscribers too slow)", dropped_count)

    def subscribe(self, queue: asyncio.Queue | None = None) -> asyncio.Queue:
        if queue is None:
            queue = asyncio.Queue(maxsize=1000)
        with self._lock:  # FIXED: 添加锁保护，避免与emit并发
            self._subscribers.append(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        with self._lock:  # FIXED: 添加锁保护，避免与emit并发
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
        with self._lock:  # FIXED-P0: 添加锁保护，避免与emit并发导致deque迭代中修改
            self._entries.clear()
