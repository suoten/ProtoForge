import asyncio
import contextlib
import logging
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

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


class EventBus:
    def __init__(self, max_history: int = 5000):
        self._subscribers: dict[str, list[asyncio.Queue]] = {}
        self._callbacks: dict[str, list[Callable]] = {}
        self._history: deque[Event] = deque(maxlen=max_history)
        self._dropped_count: int = 0
        self._lock = asyncio.Lock()

    def subscribe(self, event_type: str, queue: asyncio.Queue | None = None) -> asyncio.Queue:
        if queue is None:
            queue = asyncio.Queue(maxsize=1000)
        self._subscribers.setdefault(event_type, []).append(queue)
        return queue

    def unsubscribe(self, event_type: str, queue: asyncio.Queue) -> None:
        subs = self._subscribers.get(event_type, [])
        if queue in subs:
            subs.remove(queue)

    def on(self, event_type: str, callback: Callable) -> None:
        self._callbacks.setdefault(event_type, []).append(callback)

    def off(self, event_type: str, callback: Callable) -> None:
        cbs = self._callbacks.get(event_type, [])
        if callback in cbs:
            cbs.remove(callback)

    async def publish(self, event: Event) -> None:
        event_type = type(event).__name__
        self._history.append(event)

        for queue in self._subscribers.get(event_type, []):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                self._dropped_count += 1
                with contextlib.suppress(asyncio.QueueEmpty):
                    queue.get_nowait()
                with contextlib.suppress(asyncio.QueueFull):
                    queue.put_nowait(event)

        for callback in self._callbacks.get(event_type, []):
            try:
                result = callback(event)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as e:
                logger.error("Event callback error for %s: %s", event_type, e)

    async def publish_safe(self, event: Event) -> None:
        try:
            await self.publish(event)
        except Exception as e:
            logger.error("Event publish error: %s", e)
