import asyncio
import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine

logger = logging.getLogger(__name__)


@dataclass
class Event:
    timestamp: float = field(default_factory=lambda: time.time())


@dataclass
class DeviceCreatedEvent(Event):
    device_id: str = ""
    protocol: str = ""
    protocol_config: dict[str, Any] = field(default_factory=dict)


@dataclass
class DeviceStartedEvent(Event):
    device_id: str = ""


@dataclass
class DeviceStoppedEvent(Event):
    device_id: str = ""


@dataclass
class DeviceRemovedEvent(Event):
    device_id: str = ""


@dataclass
class IntegrationConnectionEvent(Event):
    status: str = ""
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass
class IntegrationHealthAlertEvent(Event):
    alert_type: str = ""
    message: str = ""
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass
class ProtocolStatusEvent(Event):
    protocol_name: str = ""
    old_status: str = ""
    new_status: str = ""


class EventBus:
    def __init__(self, max_history: int = 5000):
        self._subscribers: dict[str, list[asyncio.Queue]] = {}
        self._callbacks: dict[str, list[Callable]] = {}
        self._history: deque[Event] = deque(maxlen=max_history)
        self._dropped_count: int = 0
        self._last_drop_warning: float = 0.0
        self._lock = threading.Lock()  # FIXED: 使用threading.Lock替代asyncio.Lock，保护subscribe/unsubscribe/on/off/publish并发安全

    def subscribe(self, event_type: str, queue: asyncio.Queue | None = None) -> asyncio.Queue:
        if queue is None:
            queue = asyncio.Queue(maxsize=1000)
        with self._lock:  # FIXED: 添加锁保护，避免与publish/unsubscribe并发时的竞态条件
            self._subscribers.setdefault(event_type, []).append(queue)
        return queue

    def unsubscribe(self, event_type: str, queue: asyncio.Queue) -> None:
        with self._lock:  # FIXED: 添加锁保护，避免与publish/subscribe并发时的竞态条件
            subs = self._subscribers.get(event_type, [])
            if queue in subs:
                subs.remove(queue)

    def on(self, event_type: str, callback: Callable) -> None:
        with self._lock:  # FIXED: 添加锁保护，避免与publish/off并发时的竞态条件
            self._callbacks.setdefault(event_type, []).append(callback)

    def off(self, event_type: str, callback: Callable) -> None:
        with self._lock:  # FIXED: 添加锁保护，避免与publish/on并发时的竞态条件
            cbs = self._callbacks.get(event_type, [])
            if callback in cbs:
                cbs.remove(callback)

    async def publish(self, event: Event) -> None:
        event_type = type(event).__name__
        with self._lock:  # FIXED: 添加锁保护history和dropped_count的读写
            self._history.append(event)
            dropped = self._dropped_count
            queues = list(self._subscribers.get(event_type, []))
            callbacks = list(self._callbacks.get(event_type, []))

        for queue in queues:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                with self._lock:
                    self._dropped_count += 1
                    dropped_count = self._dropped_count
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                try:
                    queue.put_nowait(event)
                except asyncio.QueueFull:
                    pass
                now = time.time()
                if now - self._last_drop_warning > 60:
                    self._last_drop_warning = now
                    logger.warning("EventBus dropped %d events (subscribers too slow)", dropped_count)

        for callback in callbacks:
            try:
                result = callback(event)
                if asyncio.iscoroutine(result):
                    # FIXED: 异步回调不等待，避免阻塞事件发布
                    asyncio.create_task(self._safe_callback(result, event_type, callback))
            except Exception as e:
                logger.error("Event callback error for %s: %s", event_type, e)

    async def _safe_callback(self, coro: Coroutine, event_type: str, callback: Callable) -> None:
        """安全执行异步回调，避免异常传播"""
        try:
            await coro
        except Exception as e:
            logger.error("Async event callback error for %s: %s", event_type, e)

    async def publish_safe(self, event: Event) -> None:
        try:
            await self.publish(event)
        except Exception as e:
            logger.error("Event publish error: %s", e)
