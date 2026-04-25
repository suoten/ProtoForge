import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)


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
            "events": self.events, "enabled": self.enabled,
            "last_triggered": self.last_triggered,
            "trigger_count": self.trigger_count,
            "error_count": self.error_count,
        }


class WebhookManager:
    def __init__(self):
        self._webhooks: dict[str, WebhookConfig] = {}
        self._client: Optional[httpx.AsyncClient] = None
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=5000)
        self._task: Optional[asyncio.Task] = None
        self._running = False

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
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
        webhook = WebhookConfig(
            id=wh_id, name=config.get("name", wh_id),
            url=config["url"], events=config.get("events", ["rule_triggered"]),
            headers=config.get("headers", {}), enabled=config.get("enabled", True),
            secret=config.get("secret"),
        )
        self._webhooks[wh_id] = webhook
        logger.info("Webhook added: %s -> %s", wh_id, webhook.url)
        return webhook

    def remove_webhook(self, wh_id: str) -> bool:
        if wh_id in self._webhooks:
            del self._webhooks[wh_id]
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
            webhook.url = config["url"]
        if "events" in config:
            webhook.events = config["events"]
        if "headers" in config:
            webhook.headers = config["headers"]
        if "enabled" in config:
            webhook.enabled = config["enabled"]
        if "secret" in config:
            webhook.secret = config["secret"]
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
            try:
                body = {
                    "event": event,
                    "timestamp": timestamp,
                    "webhook_id": webhook.id,
                    "data": payload,
                }
                headers = {"Content-Type": "application/json", **webhook.headers}
                if webhook.secret:
                    import hashlib
                    sig = hashlib.sha256(f"{webhook.secret}:{json.dumps(body)}".encode()).hexdigest()
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
        return {
            "running": self._running,
            "webhooks": len(self._webhooks),
            "queue_size": self._queue.qsize(),
            "total_triggers": sum(w.trigger_count for w in self._webhooks.values()),
            "total_errors": sum(w.error_count for w in self._webhooks.values()),
        }


webhook_manager = WebhookManager()
