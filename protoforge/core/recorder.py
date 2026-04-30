import asyncio
import base64
import contextlib
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from protoforge.core.log_bus import LogBus, LogEntry

logger = logging.getLogger(__name__)


def _encrypt_data(data: bytes, key: bytes) -> str:
    from hashlib import sha256
    derived_key = sha256(key).digest()
    result = bytearray()
    for i, b in enumerate(data):
        result.append(b ^ derived_key[i % len(derived_key)])
    return base64.b64encode(bytes(result)).decode("ascii")


def _decrypt_data(encrypted: str, key: bytes) -> bytes:
    from hashlib import sha256
    derived_key = sha256(key).digest()
    data = base64.b64decode(encrypted)
    result = bytearray()
    for i, b in enumerate(data):
        result.append(b ^ derived_key[i % len(derived_key)])
    return bytes(result)


@dataclass
class RecordedMessage:
    timestamp: float
    protocol: str
    direction: str
    device_id: str
    message_type: str
    data: Any
    raw: bytes | None = None

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
    _MAX_MESSAGES = 100000

    def __init__(self, log_bus: LogBus):
        self._log_bus = log_bus
        self._recordings: dict[str, Recording] = {}
        self._active: Recording | None = None
        self._filter_protocol: str | None = None
        self._filter_device: str | None = None
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=50000)
        self._task: asyncio.Task | None = None
        self._running = False
        self._database = None
        self._encryption_key: bytes | None = None

    def set_database(self, database) -> None:
        self._database = database

    def set_encryption_key(self, key: str) -> None:
        if key:
            self._encryption_key = key.encode("utf-8")
            logger.info("Recording encryption enabled")
        else:
            self._encryption_key = None

    async def start_recording(
        self, name: str, protocol: str | None = None,
        device_id: str | None = None, metadata: dict | None = None,
    ) -> Recording:
        if self._active:
            await self.stop_recording()
        rec_id = f"rec-{uuid.uuid4().hex[:12]}"
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

    async def stop_recording(self) -> Recording | None:
        if not self._active:
            return None
        self._running = False
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        self._log_bus.unsubscribe(self._queue)
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
        if self._database:
            try:
                save_data = result.to_full_dict()
                if self._encryption_key:
                    save_data = self._encrypt_recording(save_data)
                await self._database.save_recording(save_data)
            except Exception as e:
                logger.warning("Failed to persist recording: %s", e)
        logger.info("Recording stopped: %s, %d messages", result.id, len(result.messages))
        return result

    def get_recording(self, rec_id: str) -> Recording | None:
        return self._recordings.get(rec_id)

    def list_recordings(self) -> list[dict]:
        return [r.to_dict() for r in self._recordings.values()]

    def delete_recording(self, rec_id: str) -> bool:
        if rec_id in self._recordings:
            del self._recordings[rec_id]
            return True
        return False

    async def delete_recording_persisted(self, rec_id: str) -> bool:
        if rec_id in self._recordings:
            del self._recordings[rec_id]
        if self._database:
            try:
                await self._database.delete_recording(rec_id)
            except Exception as e:
                logger.warning("Failed to delete recording from db: %s", e)
        return True

    async def restore_from_db(self) -> None:
        if not self._database:
            return
        try:
            rows = await self._database.load_all_recordings()
            for row in rows:
                try:
                    full = await self._database.load_recording(row["id"])
                    if full:
                        if full.get("encrypted") and self._encryption_key:
                            full = self._decrypt_recording(full)
                        messages = [RecordedMessage.from_dict(m) for m in full.get("messages", [])]
                        rec = Recording(
                            id=full["id"], name=full["name"],
                            protocol=full["protocol"],
                            start_time=full["start_time"],
                            end_time=full.get("end_time", 0),
                            messages=messages,
                            metadata=full.get("metadata", {}),
                        )
                        self._recordings[rec.id] = rec
                except Exception as e:
                    logger.warning("Failed to restore recording %s: %s", row.get("id"), e)
            logger.info("Restored %d recordings from database", len(self._recordings))
        except Exception as e:
            logger.warning("Failed to restore recordings: %s", e)

    async def replay_recording(self, rec_id: str, speed: float = 1.0, target_engine=None) -> dict:
        recording = self._recordings.get(rec_id)
        if not recording:
            raise ValueError(f"Recording not found: {rec_id}")
        if len(recording.messages) < 2:
            return {"status": "ok", "replayed": 0}
        replayed = 0
        for i, msg in enumerate(recording.messages):
            if i > 0:
                prev_time = recording.messages[i - 1].timestamp
                delay = (msg.timestamp - prev_time) / speed
                if delay > 0:
                    await asyncio.sleep(min(delay, 10.0))
            if target_engine:
                try:
                    if msg.direction == "write" and isinstance(msg.data, dict):
                        point_name = msg.data.get("point_name", "value")
                        point_value = msg.data.get("value")
                        if point_value is not None:
                            await target_engine.write_device_point(msg.device_id, point_name, point_value)
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
        if len(self._active.messages) >= self._MAX_MESSAGES:
            logger.warning("Recording reached max messages limit (%d)", self._MAX_MESSAGES)
            return
        data = {
            "summary": msg.summary,
            "point_name": "",
            "value": None,
        }
        if isinstance(msg.detail, dict):
            data["point_name"] = msg.detail.get("point", msg.detail.get("point_name", ""))
            data["value"] = msg.detail.get("value")
        recorded = RecordedMessage(
            timestamp=msg.timestamp,
            protocol=msg.protocol,
            direction=msg.direction,
            device_id=msg.device_id,
            message_type=msg.message_type,
            data=data,
        )
        self._active.messages.append(recorded)

    def get_stats(self) -> dict[str, Any]:
        is_rec = self._active is not None
        return {
            "recording": is_rec,
            "is_recording": is_rec,
            "active_name": self._active.name if self._active else None,
            "active_messages": len(self._active.messages) if self._active else 0,
            "frames_captured": len(self._active.messages) if self._active else 0,
            "saved_recordings": len(self._recordings),
            "total_recordings": len(self._recordings),
            "encryption_enabled": self._encryption_key is not None,
            "duration_seconds": (time.time() - self._active.start_time) if is_rec and hasattr(self._active, 'start_time') else 0,
        }

    def _encrypt_recording(self, data: dict[str, Any]) -> dict[str, Any]:
        if not self._encryption_key:
            return data
        messages = data.get("messages", [])
        encrypted_messages = []
        for msg in messages:
            msg_bytes = json.dumps(msg, ensure_ascii=False).encode("utf-8")
            encrypted_messages.append(_encrypt_data(msg_bytes, self._encryption_key))
        result = {k: v for k, v in data.items() if k != "messages"}
        result["messages_encrypted"] = encrypted_messages
        result["encrypted"] = True
        return result

    def _decrypt_recording(self, data: dict[str, Any]) -> dict[str, Any]:
        if not self._encryption_key:
            return data
        encrypted_messages = data.get("messages_encrypted", [])
        decrypted_messages = []
        for enc_msg in encrypted_messages:
            try:
                msg_bytes = _decrypt_data(enc_msg, self._encryption_key)
                decrypted_messages.append(json.loads(msg_bytes.decode("utf-8")))
            except Exception as e:
                logger.debug("Failed to decrypt recording message: %s", e)
        result = {k: v for k, v in data.items() if k not in ("messages_encrypted", "encrypted")}
        result["messages"] = decrypted_messages
        return result
