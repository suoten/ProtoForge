import asyncio
import hashlib
import hmac
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Optional
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)


def _is_private_hostname(hostname: str) -> bool:
    if hostname in ("localhost", "127.0.0.1", "0.0.0.0", "::1"):
        return True
    if hostname.startswith("169.254.") or hostname.startswith("10.") or hostname.startswith("192.168."):
        return True
    if hostname.endswith(".local") or hostname.endswith(".internal"):
        return True
    if hostname.startswith("172."):
        parts = hostname.split(".")
        if len(parts) >= 2:
            try:
                second = int(parts[1])
                if 16 <= second <= 31:
                    return True
            except ValueError:
                pass
    try:
        import ipaddress
        addr = ipaddress.ip_address(hostname)
        if addr.is_private or addr.is_loopback or addr.is_reserved or addr.is_link_local:
            return True
    except ValueError:
        pass
    return False


@dataclass
class WebhookConfig:
    id: str
    name: str
    url: str
    events: list[str] = field(default_factory=lambda: ["rule_triggered"])
    headers: dict[str, str] = field(default_factory=dict)
    enabled: bool = True
    secret: Optional[str] = None
    last_triggered: float = 0
    trigger_count: int = 0
    error_count: int = 0

    def to_dict(self) -> dict:
        return {
            "id": self.id, "name": self.name, "url": self.url,
            "events": self.events, "headers": self.headers,
            "enabled": self.enabled, "secret": "***" if self.secret else None,
            "last_triggered": self.last_triggered,
            "trigger_count": self.trigger_count,
            "error_count": self.error_count,
        }


class WebhookManager:
    _PERSIST_FILE = "data/webhooks.json"

    def __init__(self):
        self._webhooks: dict[str, WebhookConfig] = {}
        self._client: Optional[httpx.AsyncClient] = None
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=5000)
        self._task: Optional[asyncio.Task] = None
        self._running = False

    def _persist(self) -> None:
        try:
            from pathlib import Path
            path = Path(self._PERSIST_FILE)
            path.parent.mkdir(parents=True, exist_ok=True)
            data = []
            for wh in self._webhooks.values():
                data.append({
                    "id": wh.id, "name": wh.name, "url": wh.url,
                    "events": wh.events, "headers": wh.headers,
                    "enabled": wh.enabled, "secret": wh.secret,
                })
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            logger.warning("Failed to persist webhooks: %s", e)

    def _restore(self) -> None:
        try:
            from pathlib import Path
            path = Path(self._PERSIST_FILE)
            if not path.exists():
                return
            data = json.loads(path.read_text(encoding="utf-8"))
            for item in data:
                wh = WebhookConfig(
                    id=item["id"], name=item.get("name", item["id"]),
                    url=item["url"], events=item.get("events", ["rule_triggered"]),
                    headers=item.get("headers", {}), enabled=item.get("enabled", True),
                    secret=item.get("secret"),
                )
                self._webhooks[wh.id] = wh
            logger.info("Restored %d webhooks from persistence", len(self._webhooks))
        except Exception as e:
            logger.warning("Failed to restore webhooks: %s", e)

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._restore()
        self._client = httpx.AsyncClient(timeout=10.0)
        self._task = asyncio.create_task(self._send_loop())
        logger.info("Webhook manager started with %d webhooks", len(self._webhooks))

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self._client:
            await self._client.aclose()
            self._client = None
        logger.info("Webhook manager stopped")

    def add_webhook(self, config: dict[str, Any]) -> WebhookConfig:
        wh_id = config.get("id", f"wh-{int(time.time())}")
        url = config["url"]
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            raise ValueError(f"Webhook URL must use http/https scheme, got: {parsed.scheme}")
        hostname = parsed.hostname or ""
        if _is_private_hostname(hostname):
            raise ValueError(f"Webhook URL points to private/internal address: {url}")
        webhook = WebhookConfig(
            id=wh_id, name=config.get("name", wh_id),
            url=url, events=config.get("events", ["rule_triggered"]),
            headers=config.get("headers", {}), enabled=config.get("enabled", True),
            secret=config.get("secret"),
        )
        self._webhooks[wh_id] = webhook
        self._persist()
        logger.info("Webhook added: %s -> %s", wh_id, webhook.url)
        return webhook

    def remove_webhook(self, wh_id: str) -> bool:
        if wh_id in self._webhooks:
            del self._webhooks[wh_id]
            self._persist()
            return True
        return False

    def get_webhook(self, wh_id: str) -> Optional[WebhookConfig]:
        return self._webhooks.get(wh_id)

    def list_webhooks(self) -> list[dict]:
        return [wh.to_dict() for wh in self._webhooks.values()]

    def update_webhook(self, wh_id: str, config: dict[str, Any]) -> Optional[WebhookConfig]:
        webhook = self._webhooks.get(wh_id)
        if not webhook:
            return None
        if "name" in config:
            webhook.name = config["name"]
        if "url" in config:
            new_url = config["url"]
            parsed = urlparse(new_url)
            if parsed.scheme not in ("http", "https"):
                raise ValueError(f"Webhook URL must use http/https scheme, got: {parsed.scheme}")
            hostname = parsed.hostname or ""
            if _is_private_hostname(hostname):
                raise ValueError(f"Webhook URL points to private/internal address: {new_url}")
            webhook.url = new_url
        if "events" in config:
            webhook.events = config["events"]
        if "headers" in config:
            webhook.headers = config["headers"]
        if "enabled" in config:
            webhook.enabled = config["enabled"]
        if "secret" in config:
            webhook.secret = config["secret"]
        self._persist()
        return webhook

    async def trigger(self, event: str, payload: dict[str, Any]) -> None:
        await self._queue.put({"event": event, "payload": payload, "timestamp": time.time()})

    async def _send_loop(self) -> None:
        while self._running:
            try:
                msg = await asyncio.wait_for(self._queue.get(), timeout=1.0)
                await self._dispatch(msg)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

    async def _dispatch(self, msg: dict) -> None:
        event = msg["event"]
        payload = msg["payload"]
        timestamp = msg["timestamp"]
        for webhook in self._webhooks.values():
            if not webhook.enabled:
                continue
            if event not in webhook.events and "*" not in webhook.events:
                continue

            # Rate limiting: max 1 trigger per 5 seconds per webhook
            if timestamp - webhook.last_triggered < 5.0:
                continue

            # Auto-disable webhook after too many errors
            if webhook.error_count >= 50:
                webhook.enabled = False
                logger.warning("Webhook %s auto-disabled due to %d errors", webhook.id, webhook.error_count)
                continue

            try:
                body = {
                    "event": event,
                    "timestamp": timestamp,
                    "webhook_id": webhook.id,
                    "data": payload,
                }
                headers = {"Content-Type": "application/json", **webhook.headers}
                if webhook.secret:
                    body_bytes = json.dumps(body).encode()
                    sig = hmac.new(webhook.secret.encode(), body_bytes, hashlib.sha256).hexdigest()
                    headers["X-ProtoForge-Signature"] = sig
                if self._client:
                    resp = await self._client.post(webhook.url, json=body, headers=headers)
                    if resp.status_code >= 400:
                        logger.warning("Webhook %s returned %d", webhook.id, resp.status_code)
                        webhook.error_count += 1
                    else:
                        webhook.trigger_count += 1
                        webhook.last_triggered = time.time()
            except Exception as e:
                logger.warning("Webhook %s dispatch error: %s", webhook.id, e)
                webhook.error_count += 1

    def get_stats(self) -> dict[str, Any]:
        total_triggers = sum(w.trigger_count for w in self._webhooks.values())
        total_errors = sum(w.error_count for w in self._webhooks.values())
        return {
            "running": self._running,
            "webhooks": len(self._webhooks),
            "queue_size": self._queue.qsize(),
            "total_calls": total_triggers,
            "success_count": total_triggers - total_errors,
            "fail_count": total_errors,
        }


webhook_manager = WebhookManager()
