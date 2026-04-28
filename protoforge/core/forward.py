import asyncio
import json
import logging
import time
from abc import ABC, abstractmethod
from typing import Any, Optional

import httpx

from protoforge.core.log_bus import LogBus, LogEntry

logger = logging.getLogger(__name__)


class ForwardTarget(ABC):
    @abstractmethod
    async def send(self, records: list[dict[str, Any]]) -> None:
        ...

    @abstractmethod
    async def close(self) -> None:
        ...


class InfluxDBTarget(ForwardTarget):
    def __init__(self, url: str, token: str, org: str, bucket: str):
        self._url = url.rstrip("/")
        self._token = token
        self._org = org
        self._bucket = bucket
        self._client: Optional[httpx.AsyncClient] = None

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._url,
                headers={"Authorization": f"Token {self._token}"},
                timeout=10.0,
            )
        return self._client

    async def send(self, records: list[dict[str, Any]]) -> None:
        lines = []
        for r in records:
            measurement = r.get("protocol", "device")
            tags = f"device_id={r.get('device_id', 'unknown')},protocol={r.get('protocol', 'unknown')}"
            fields_parts = []
            if "value" in r:
                try:
                    fields_parts.append(f"value={float(r['value'])}")
                except (ValueError, TypeError):
                    fields_parts.append(f'value="{r["value"]}"')
            if "point_name" in r:
                fields_parts.append(f'point_name="{r["point_name"]}"')
            if not fields_parts:
                continue
            fields = ",".join(fields_parts)
            ts = int(r.get("timestamp", time.time()) * 1e9)
            lines.append(f"{measurement},{tags} {fields} {ts}")
        if not lines:
            return
        client = await self._ensure_client()
        try:
            resp = await client.post(
                "/api/v2/write",
                params={"org": self._org, "bucket": self._bucket, "precision": "ns"},
                content="\n".join(lines),
            )
            if resp.status_code >= 400:
                logger.warning("InfluxDB write failed: %d %s", resp.status_code, resp.text[:200])
        except Exception as e:
            logger.warning("InfluxDB send error: %s", e)

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None


class HTTPTarget(ForwardTarget):
    def __init__(self, url: str, headers: Optional[dict[str, str]] = None, method: str = "POST"):
        self._url = url
        self._headers = headers or {}
        self._method = method.upper()
        self._client: Optional[httpx.AsyncClient] = None

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=10.0)
        return self._client

    async def send(self, records: list[dict[str, Any]]) -> None:
        client = await self._ensure_client()
        try:
            payload = {"timestamp": time.time(), "records": records}
            if self._method == "POST":
                resp = await client.post(self._url, json=payload, headers=self._headers)
            else:
                resp = await client.put(self._url, json=payload, headers=self._headers)
            if resp.status_code >= 400:
                logger.warning("HTTP forward failed: %d %s", resp.status_code, resp.text[:200])
        except Exception as e:
            logger.warning("HTTP forward error: %s", e)

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None


class FileTarget(ForwardTarget):
    def __init__(self, path: str, format: str = "jsonl"):
        self._path = path
        self._format = format

    async def send(self, records: list[dict[str, Any]]) -> None:
        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self._write_sync, records)
        except Exception as e:
            logger.warning("File forward error: %s", e)

    def _write_sync(self, records: list[dict[str, Any]]) -> None:
        with open(self._path, "a", encoding="utf-8") as f:
            for r in records:
                if self._format == "jsonl":
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
                else:
                    f.write(f"{r.get('timestamp', 0)}|{r.get('device_id', '')}|{r.get('point_name', '')}|{r.get('value', '')}\n")

    async def close(self) -> None:
        pass


class ForwardEngine:
    def __init__(self, log_bus: LogBus):
        self._log_bus = log_bus
        self._targets: dict[str, ForwardTarget] = {}
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=10000)
        self._batch_size = 100
        self._flush_interval = 5.0
        self._sent_count: int = 0
        self._failed_count: int = 0
        self._retry_count: int = 3

    def add_target(self, name: str, target: ForwardTarget) -> None:
        self._targets[name] = target
        logger.info("Forward target added: %s", name)

    def remove_target(self, name: str) -> None:
        self._targets.pop(name, None)
        logger.info("Forward target removed: %s", name)

    def list_targets(self) -> list[dict[str, str]]:
        result = []
        for name, target in self._targets.items():
            target_type = type(target).__name__
            result.append({"name": name, "type": target_type})
        return result

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._log_bus.subscribe(self._queue)
        self._task = asyncio.create_task(self._forward_loop())
        logger.info("Forward engine started with %d targets", len(self._targets))

    async def stop(self) -> None:
        self._running = False
        self._log_bus.unsubscribe(self._queue)
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        for target in self._targets.values():
            try:
                await target.close()
            except Exception as e:
                logger.warning("Error closing target: %s", e)
        logger.info("Forward engine stopped")

    async def _forward_loop(self) -> None:
        while self._running:
            records = []
            try:
                while len(records) < self._batch_size:
                    timeout = 0.1 if records else self._flush_interval
                    msg: LogEntry = await asyncio.wait_for(self._queue.get(), timeout=timeout)
                    records.append({
                        "timestamp": msg.timestamp,
                        "protocol": msg.protocol,
                        "direction": msg.direction,
                        "device_id": msg.device_id,
                        "message_type": msg.message_type,
                        "summary": msg.summary,
                        "detail": msg.detail,
                    })
            except asyncio.TimeoutError:
                pass
            if records and self._targets:
                for name, target in self._targets.items():
                    for attempt in range(self._retry_count):
                        try:
                            await target.send(records)
                            self._sent_count += len(records)
                            break
                        except Exception as e:
                            if attempt < self._retry_count - 1:
                                await asyncio.sleep(0.5 * (attempt + 1))
                            else:
                                self._failed_count += len(records)
                                logger.warning("Forward to %s failed after %d retries: %s", name, self._retry_count, e)

    def get_stats(self) -> dict[str, Any]:
        return {
            "running": self._running,
            "targets": len(self._targets),
            "queue_size": self._queue.qsize(),
            "sent_count": self._sent_count,
            "failed_count": self._failed_count,
        }


def create_target(config: dict[str, Any]) -> ForwardTarget:
    target_type = config.get("type", "http")
    if target_type == "influxdb":
        return InfluxDBTarget(
            url=config["url"], token=config["token"],
            org=config.get("org", "default"), bucket=config.get("bucket", "protoforge"),
        )
    elif target_type == "http":
        return HTTPTarget(
            url=config["url"], headers=config.get("headers"),
            method=config.get("method", "POST"),
        )
    elif target_type == "file":
        return FileTarget(
            path=config["path"], format=config.get("format", "jsonl"),
        )
    else:
        raise ValueError(f"Unknown target type: {target_type}")
