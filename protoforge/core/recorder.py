import asyncio
import base64
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

from protoforge.core.log_bus import LogBus, LogEntry

logger = logging.getLogger(__name__)

_AES_AVAILABLE = False
try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    _AES_AVAILABLE = True
except ImportError:
    logger.warning(
        "cryptography library not available. Recording encryption will not work. "
        "Install with: pip install cryptography"
    )


def _encrypt_data(data: bytes, key: bytes) -> str:
    if not _AES_AVAILABLE:
        raise RuntimeError("Recording encryption requires the 'cryptography' library. Install with: pip install cryptography")
    try:  # FIXED: 加密操作无异常保护
        derived_key = _derive_key(key)
        nonce = os.urandom(12)
        aesgcm = AESGCM(derived_key)
        ct = aesgcm.encrypt(nonce, data, None)
        return base64.b64encode(nonce + ct).decode("ascii")
    except Exception as e:
        raise RuntimeError(f"Recording encryption failed: {e}") from e


def _decrypt_data(encrypted: str, key: bytes) -> bytes:
    if not _AES_AVAILABLE:
        raise RuntimeError("Recording decryption requires the 'cryptography' library. Install with: pip install cryptography")
    try:  # FIXED: 解密操作无异常保护(base64解码/密文校验均可抛异常)
        derived_key = _derive_key(key)
        raw = base64.b64decode(encrypted)
        nonce = raw[:12]
        ct = raw[12:]
        aesgcm = AESGCM(derived_key)
        return aesgcm.decrypt(nonce, ct, None)
    except Exception as e:
        raise RuntimeError(f"Recording decryption failed: {e}") from e


_SALT_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", ".recording_salt")
_DERIVED_SALT: Optional[bytes] = None


def _get_or_create_salt() -> bytes:
    global _DERIVED_SALT
    if _DERIVED_SALT is not None:
        return _DERIVED_SALT
    try:
        salt_dir = os.path.dirname(_SALT_FILE)
        os.makedirs(salt_dir, exist_ok=True)
        if os.path.exists(_SALT_FILE):
            with open(_SALT_FILE, "rb") as f:
                saved = f.read().strip()
            if saved and len(saved) >= 16:
                _DERIVED_SALT = saved
                return saved
    except Exception as e:
        logger.debug("Could not load recording salt: %s", e)
    new_salt = os.urandom(32)
    _DERIVED_SALT = new_salt
    try:
        salt_dir = os.path.dirname(_SALT_FILE)
        os.makedirs(salt_dir, exist_ok=True)
        with open(_SALT_FILE, "wb") as f:
            f.write(new_salt)
        logger.info("Generated and saved new recording salt")
    except Exception as e:
        logger.error("Could not persist recording salt: %s. Encrypted recordings may not be decryptable after restart!", e)  # FIXED: 提升日志级别为error
    return new_salt


def _derive_key(key: bytes) -> bytes:
    from hashlib import sha256
    salt = _get_or_create_salt()
    return sha256(salt + key).digest()


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
            try:  # FIXED: bytes.fromhex可能抛ValueError
                raw = bytes.fromhex(data["raw_hex"])
            except ValueError as e:
                logger.debug("Invalid raw_hex in recorded message: %s", e)
        return cls(
            timestamp=data.get("timestamp", 0), protocol=data.get("protocol", ""),
            direction=data.get("direction", ""), device_id=data.get("device_id", ""),
            message_type=data.get("message_type", ""), data=data.get("data"), raw=raw,
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
        duration = (self.end_time - self.start_time) if self.end_time > 0 else 0
        return {
            "id": self.id, "name": self.name, "protocol": self.protocol,
            "start_time": self.start_time, "end_time": self.end_time,
            "started_at": self.start_time, "stopped_at": self.end_time,
            "frame_count": len(self.messages), "event_count": len(self.messages),
            "is_active": self.end_time == 0,
            "metadata": self.metadata,
            "device_id": self.metadata.get("device_id", ""),
            "duration_seconds": round(duration, 1),
            "created_at": self.start_time,
        }

    def to_full_dict(self) -> dict:
        d = self.to_dict()
        d["frames"] = [{**m.to_dict(), "index": i} for i, m in enumerate(self.messages)]
        d["events"] = d["frames"]
        return d

    def export_json(self) -> str:
        return json.dumps(self.to_full_dict(), indent=2, ensure_ascii=False)


class Recorder:
    _MAX_MESSAGES = None

    @classmethod
    def _get_max_messages(cls) -> int:
        if cls._MAX_MESSAGES is None:
            try:
                from protoforge.config import get_settings
                cls._MAX_MESSAGES = get_settings().recorder_max_messages
            except Exception:
                cls._MAX_MESSAGES = 100000
        return cls._MAX_MESSAGES

    def __init__(self, log_bus: LogBus):
        self._log_bus = log_bus
        self._recordings: dict[str, Recording] = {}
        self._active: Optional[Recording] = None
        self._filter_protocol: Optional[str] = None
        self._filter_device: Optional[str] = None
        try:
            from protoforge.config import get_settings
            queue_size = get_settings().recorder_queue_size
        except Exception:
            queue_size = 50000
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=queue_size)
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._database = None
        self._encryption_key: Optional[bytes] = None
        self._max_warned_active: bool = False

    def set_database(self, database) -> None:
        self._database = database

    def set_encryption_key(self, key: str) -> None:
        if key:
            if not _AES_AVAILABLE:
                raise RuntimeError(
                    "Recording encryption requires the 'cryptography' library. "
                    "Install with: pip install cryptography"
                )
            self._encryption_key = key.encode("utf-8")
            logger.info("Recording encryption enabled")
        else:
            self._encryption_key = None

    async def start_recording(
        self, name: str, protocol: Optional[str] = None,
        device_id: Optional[str] = None, metadata: Optional[dict] = None,
    ) -> Recording:
        if self._active:
            await self.stop_recording()
        rec_id = f"rec-{uuid.uuid4().hex[:12]}"
        self._active = Recording(
            id=rec_id, name=name, protocol=protocol or "*",
            start_time=time.time(), metadata=metadata or {},
        )
        self._max_warned_active = False
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
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
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

    def get_recording(self, rec_id: str) -> Optional[Recording]:
        return self._recordings.get(rec_id)

    def list_recordings(self) -> list[dict]:
        return [r.to_dict() for r in self._recordings.values()]

    def delete_recording(self, rec_id: str) -> bool:
        if rec_id in self._recordings:
            del self._recordings[rec_id]
            return True
        return False

    async def delete_recording_persisted(self, rec_id: str) -> bool:
        if rec_id not in self._recordings and not self._database:
            return False
        if rec_id in self._recordings:
            del self._recordings[rec_id]
        if self._database:
            try:
                await self._database.delete_recording(rec_id)
            except Exception as e:
                logger.warning("Failed to delete recording from db: %s", e)
                return False
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
        import math
        if not isinstance(speed, (int, float)) or speed <= 0 or math.isinf(speed) or math.isnan(speed):  # FIXED: 排除NaN/Infinity
            raise ValueError(f"Speed must be a positive finite number, got: {speed}")
        recording = self._recordings.get(rec_id)
        if not recording:
            raise ValueError(f"Recording not found: {rec_id}")
        total = len(recording.messages)
        if total < 2:
            return {"status": "ok", "replayed": 0, "replayed_events": 0, "total_events": total,
                    "success_count": 0, "error_count": 0, "duration_seconds": 0, "recording_id": rec_id}
        replayed = 0
        errors = 0
        start_ts = time.time()
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
                    errors += 1
            replayed += 1
        elapsed = round(time.time() - start_ts, 2)
        return {"status": "ok", "replayed": replayed, "recording_id": rec_id,
                "replayed_events": replayed, "total_events": total,
                "success_count": replayed - errors, "error_count": errors,
                "duration_seconds": elapsed}

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
        if len(self._active.messages) >= self._get_max_messages():
            if not self._max_warned_active:
                logger.warning("Recording reached max messages limit (%d), new messages will be dropped", self._get_max_messages())
                self._max_warned_active = True
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
        active = self._active  # FIXED: 缓存引用，防止并发stop_recording导致None
        is_rec = active is not None
        total_events = sum(len(r.messages) for r in self._recordings.values())
        if is_rec:
            total_events += len(active.messages)
        total_bytes = 0
        for r in self._recordings.values():
            for msg in r.messages:
                total_bytes += len(json.dumps(msg.to_dict(), ensure_ascii=False).encode("utf-8"))
        if is_rec:
            for msg in active.messages:
                total_bytes += len(json.dumps(msg.to_dict(), ensure_ascii=False).encode("utf-8"))
        avg_events = round(total_events / max(len(self._recordings), 1), 1)
        return {
            "is_recording": is_rec,
            "active_name": active.name if is_rec else None,
            "frames_captured": len(active.messages) if is_rec else 0,
            "total_recordings": len(self._recordings),
            "total_events": total_events,
            "total_bytes": total_bytes,
            "avg_events_per_recording": avg_events,
            "encryption_enabled": self._encryption_key is not None,
            "duration_seconds": (time.time() - active.start_time) if is_rec else 0,
        }

    def _encrypt_recording(self, data: dict[str, Any]) -> dict[str, Any]:
        if not self._encryption_key:
            return data
        try:  # FIXED: 加密失败时fallback保存未加密数据
            messages = data.get("messages", [])
            encrypted_messages = []
            for msg in messages:
                msg_bytes = json.dumps(msg, ensure_ascii=False).encode("utf-8")
                encrypted_messages.append(_encrypt_data(msg_bytes, self._encryption_key))
            result = {k: v for k, v in data.items() if k != "messages"}
            result["messages_encrypted"] = encrypted_messages
            result["encrypted"] = True
            return result
        except Exception as e:
            logger.error("Recording encryption failed, saving unencrypted: %s", e)
            return data

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
