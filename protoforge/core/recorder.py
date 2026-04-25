import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from protoforge.core.log_bus import LogBus, LogEntry

logger = logging.getLogger(__name__)


@dataclass
class RecordedMessage:
    timestamp: float
    protocol: str
    direction: str
    device_id: str
    message_type: str
    data: Any
    raw: Optional[bytes] = None

    def to_dict(self) -> dict:
        d = {
            "timestamp": self.timestamp, "protocol": self.protocol,
            "direction": self.direction, "device_id": self.device_id,
            "message_type": self.message_type, "data": self.data,
        }
        if self.raw:
            d["raw_hex"] = self.raw.hex()
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "RecordedMessage":
        raw = None
        if "raw_hex" in data:
            raw = bytes.fromhex(data["raw_hex"])
        return cls(
            timestamp=data["timestamp"], protocol=data["protocol"],
            direction=data["direction"], device_id=data["device_id"],
            message_type=data["message_type"], data=data["data"], raw=raw,
        )


@dataclass
class Recording:
    id: str
    name: str
    protocol: str
    start_time: float
    end_time: float = 0
    messages: list[RecordedMessage] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id": self.id, "name": self.name, "protocol": self.protocol,
            "start_time": self.start_time, "end_time": self.end_time,
            "message_count": len(self.messages),
            "metadata": self.metadata,
        }

    def to_full_dict(self) -> dict:
        d = self.to_dict()
        d["messages"] = [m.to_dict() for m in self.messages]
        return d

    def export_json(self) -> str:
        return json.dumps(self.to_full_dict(), indent=2, ensure_ascii=False)


class Recorder:
    def __init__(self, log_bus: LogBus):
        self._log_bus = log_bus
        self._recordings: dict[str, Recording] = {}
        self._active: Optional[Recording] = None
        self._filter_protocol: Optional[str] = None
        self._filter_device: Optional[str] = None
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=50000)
        self._task: Optional[asyncio.Task] = None
        self._running = False

    async def start_recording(
        self, name: str, protocol: Optional[str] = None,
        device_id: Optional[str] = None, metadata: Optional[dict] = None,
    ) -> Recording:
        if self._active:
            await self.stop_recording()
        rec_id = f"rec-{int(time.time())}"
        self._active = Recording(
            id=rec_id, name=name, protocol=protocol or "*",
            start_time=time.time(), metadata=metadata or {},
        )
        self._filter_protocol = protocol
        self._filter_device = device_id
        self._running = True
        self._log_bus.subscribe(self._queue)
        self._task = asyncio.create_task(self._collect_loop())
        logger.info("Recording started: %s (%s)", name, rec_id)
        return self._active

    async def stop_recording(self) -> Optional[Recording]:
        if not self._active:
            return None
        self._running = False
        self._log_bus.unsubscribe(self._queue)
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        while not self._queue.empty():
            try:
                msg = self._queue.get_nowait()
                self._process_message(msg)
            except asyncio.QueueEmpty:
                break
        self._active.end_time = time.time()
        self._recordings[self._active.id] = self._active
        result = self._active
        self._active = None
        logger.info("Recording stopped: %s, %d messages", result.id, len(result.messages))
        return result

    def get_recording(self, rec_id: str) -> Optional[Recording]:
        return self._recordings.get(rec_id)

    def list_recordings(self) -> list[dict]:
        return [r.to_dict() for r in self._recordings.values()]

    def delete_recording(self, rec_id: str) -> bool:
        if rec_id in self._recordings:
            del self._recordings[rec_id]
            return True
        return False

    async def replay_recording(self, rec_id: str, speed: float = 1.0, target_engine=None) -> dict:
        recording = self._recordings.get(rec_id)
        if not recording:
            raise ValueError(f"Recording not found: {rec_id}")
        if len(recording.messages) < 2:
            return {"status": "ok", "replayed": 0}
        replayed = 0
        base_time = recording.messages[0].timestamp
        for i, msg in enumerate(recording.messages):
            if i > 0:
                delay = (msg.timestamp - base_time) / speed
                prev_time = recording.messages[i - 1].timestamp
                delay = (msg.timestamp - prev_time) / speed
                if delay > 0:
                    await asyncio.sleep(min(delay, 10.0))
            if target_engine:
                try:
                    device = target_engine._devices.get(msg.device_id)
                    if device and msg.direction == "write" and msg.data:
                        point_name = msg.data.get("point_name", "value")
                        point_value = msg.data.get("value")
                        if point_value is not None:
                            device.write_point(point_name, point_value)
                except Exception as e:
                    logger.debug("Replay write error: %s", e)
            replayed += 1
        return {"status": "ok", "replayed": replayed, "recording_id": rec_id}

    async def _collect_loop(self) -> None:
        while self._running:
            try:
                msg = await asyncio.wait_for(self._queue.get(), timeout=1.0)
                self._process_message(msg)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

    def _process_message(self, msg: LogEntry) -> None:
        if not self._active:
            return
        if self._filter_protocol and msg.protocol != self._filter_protocol:
            return
        if self._filter_device and msg.device_id != self._filter_device:
            return
        recorded = RecordedMessage(
            timestamp=msg.timestamp,
            protocol=msg.protocol,
            direction=msg.direction,
            device_id=msg.device_id,
            message_type=msg.message_type,
            data=msg.summary,
        )
        self._active.messages.append(recorded)

    def get_stats(self) -> dict[str, Any]:
        return {
            "recording": self._active is not None,
            "active_name": self._active.name if self._active else None,
            "active_messages": len(self._active.messages) if self._active else 0,
            "saved_recordings": len(self._recordings),
        }
