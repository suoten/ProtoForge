import asyncio
import hashlib
import hmac
import json
import logging
import os
import threading  # FIXED: WebhookManager._lock需要threading.Lock
import time
from protoforge.core.defaults import HTTP_TIMEOUT_DEFAULT  # FIXED: 恢复导入，webhook使用此超时常量
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
                logger.debug("IP octet parse failed for '%s'", parts[1])
    try:
        import ipaddress
        addr = ipaddress.ip_address(hostname)
        if addr.is_private or addr.is_loopback or addr.is_reserved or addr.is_link_local:
            return True
    except ValueError:
        logger.debug("IP address parse failed for '%s'", hostname)
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
    _PERSIST_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data")
    _PERSIST_FILE = None

    @classmethod
    def _get_persist_file(cls) -> str:
        if cls._PERSIST_FILE is None:
            cls._PERSIST_FILE = os.path.join(cls._PERSIST_DIR, "webhooks.json")
        return cls._PERSIST_FILE

    def __init__(self, queue_maxsize: int = 0,
                 rate_limit_seconds: float = 0.0,
                 auto_disable_threshold: int = 0):
        # FIXED: P4 - Q5 魔法数字→常量，从 settings 获取默认值而非硬编码
        if queue_maxsize <= 0 or rate_limit_seconds <= 0 or auto_disable_threshold <= 0:
            try:
                from protoforge.config import get_settings
                settings = get_settings()
                if queue_maxsize <= 0:
                    queue_maxsize = settings.webhook_queue_size
                if rate_limit_seconds <= 0:
                    rate_limit_seconds = settings.webhook_rate_limit_seconds
                if auto_disable_threshold <= 0:
                    auto_disable_threshold = settings.webhook_auto_disable_threshold
            except Exception:
                queue_maxsize = queue_maxsize or 5000
                rate_limit_seconds = rate_limit_seconds or 5.0
                auto_disable_threshold = auto_disable_threshold or 50
        self._webhooks: dict[str, WebhookConfig] = {}
        self._client: Optional[httpx.AsyncClient] = None
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=queue_maxsize)
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._rate_limit_seconds = rate_limit_seconds
        self._auto_disable_threshold = auto_disable_threshold
        self._lock = threading.Lock()  # FIXED: 添加锁保护，避免add/remove/update与_dispatch并发

    def _persist(self) -> None:
        try:
            from pathlib import Path
            path = Path(self._get_persist_file())
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
            path = Path(self._get_persist_file())
            if not path.exists():
                return
            data = json.loads(path.read_text(encoding="utf-8"))
            for item in data:
                wh_id = item.get("id")
                wh_url = item.get("url")
                if not wh_id or not wh_url:
                    logger.warning("Skipping webhook with missing id or url: %s", item)
                    continue
                wh = WebhookConfig(
                    id=wh_id, name=item.get("name", wh_id),
                    url=wh_url, events=item.get("events", ["rule_triggered"]),
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
        # FIXED: 使用连接池配置，提高 Webhook 发送性能
        self._client = httpx.AsyncClient(
            timeout=HTTP_TIMEOUT_DEFAULT,
            limits=httpx.Limits(
                max_connections=20,
                max_keepalive_connections=10,
                keepalive_expiry=30.0,
            ),
        )
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
        url = config.get("url", "")
        if not url:
            raise ValueError("Webhook URL is required")
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
        with self._lock:  # FIXED: 添加锁保护，避免与_dispatch并发
            self._webhooks[wh_id] = webhook
        try:
            self._persist()
        except Exception as e:  # FIXED: 持久化失败时回滚内存状态
            with self._lock:
                self._webhooks.pop(wh_id, None)
            raise RuntimeError(f"Failed to persist webhook: {e}") from e
        logger.info("Webhook added: %s -> %s", wh_id, webhook.url)
        return webhook

    def remove_webhook(self, wh_id: str) -> bool:
        with self._lock:  # FIXED: 添加锁保护，避免与_dispatch并发
            if wh_id in self._webhooks:
                del self._webhooks[wh_id]
                removed = True
            else:
                removed = False
        if removed:
            self._persist()
        return removed

    def get_webhook(self, wh_id: str) -> Optional[WebhookConfig]:
        return self._webhooks.get(wh_id)

    def list_webhooks(self) -> list[dict]:
        return [wh.to_dict() for wh in self._webhooks.values()]

    def update_webhook(self, wh_id: str, config: dict[str, Any]) -> Optional[WebhookConfig]:
        webhook = self._webhooks.get(wh_id)
        if not webhook:
            return None
        webhook.name = config.get("name", webhook.name)
        new_url = config.get("url", webhook.url)
        if "url" in config:
            parsed = urlparse(new_url)
            if parsed.scheme not in ("http", "https"):
                raise ValueError(f"Webhook URL must use http/https scheme, got: {parsed.scheme}")
            hostname = parsed.hostname or ""
            if _is_private_hostname(hostname):
                raise ValueError(f"Webhook URL points to private/internal address: {new_url}")
        webhook.url = new_url
        webhook.events = config.get("events", webhook.events)
        webhook.headers = config.get("headers", webhook.headers)
        webhook.enabled = config.get("enabled", webhook.enabled)
        webhook.secret = config.get("secret", webhook.secret)
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

    async def _send_single(self, webhook: WebhookConfig, body: dict[str, Any]) -> None:
        if self._client is None:
            raise RuntimeError("WebhookManager is not running. Call start() first.")
        headers = {"Content-Type": "application/json", **webhook.headers}
        if webhook.secret:
            try:
                body_bytes = json.dumps(body).encode("utf-8")
                sig = hmac.new(webhook.secret.encode("utf-8"), body_bytes, hashlib.sha256).hexdigest()
            except (UnicodeEncodeError, TypeError) as enc_err:
                logger.error("Failed to compute HMAC for webhook %s: %s", webhook.id, enc_err)
                return
            headers["X-ProtoForge-Signature"] = sig
        try:
            resp = await self._client.post(webhook.url, json=body, headers=headers)
        except (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError, OSError) as e:
            webhook.error_count += 1
            raise RuntimeError(f"Webhook network error: {e}") from e
        if resp.status_code >= 400:
            webhook.error_count += 1
            # Client errors (4xx) like 405 indicate misconfiguration - auto-disable quickly
            if 400 <= resp.status_code < 500:
                raise RuntimeError(f"Webhook client error HTTP {resp.status_code} (likely misconfigured)")
            raise RuntimeError(f"Webhook returned HTTP {resp.status_code}")
        webhook.trigger_count += 1
        webhook.last_triggered = time.time()
        self._persist()

    async def _dispatch(self, msg: dict) -> None:
        event = msg.get("event")
        payload = msg.get("payload")
        timestamp = msg.get("timestamp")
        if not event:
            logger.warning("Webhook message missing 'event' field")
            return
        for webhook in list(self._webhooks.values()):
            if not webhook.enabled:
                continue
            if event not in webhook.events and "*" not in webhook.events:
                continue

            if timestamp - webhook.last_triggered < self._rate_limit_seconds:
                continue

            # Auto-disable threshold: use lower threshold for client errors (4xx = misconfiguration)
            effective_threshold = self._auto_disable_threshold
            if webhook.error_count >= effective_threshold:
                webhook.enabled = False
                logger.warning("Webhook %s auto-disabled due to %d errors", webhook.id, webhook.error_count)
                self._persist()
                continue

            body = {
                "event": event,
                "timestamp": timestamp,
                "webhook_id": webhook.id,
                "data": payload,
            }
            try:
                await self._send_single(webhook, body)
            except Exception as e:
                err_str = str(e)
                # Client errors (4xx) mean misconfiguration - auto-disable after just 3 failures
                if "client error" in err_str.lower() and webhook.error_count >= 3:
                    webhook.enabled = False
                    logger.warning("Webhook %s auto-disabled: client error (4xx) indicates misconfiguration: %s", webhook.id, e)
                    self._persist()
                else:
                    logger.warning("Webhook %s dispatch error: %s", webhook.id, e)

    def get_stats(self) -> dict[str, Any]:
        total_success = sum(w.trigger_count for w in self._webhooks.values())
        total_errors = sum(w.error_count for w in self._webhooks.values())
        total_calls = total_success + total_errors
        error_rate = total_errors / total_calls if total_calls > 0 else 0.0
        return {
            "running": self._running,
            "webhooks": len(self._webhooks),
            "queue_size": self._queue.qsize(),
            "total_calls": total_calls,
            "total_triggers": total_calls,
            "success_count": total_success,
            "fail_count": total_errors,
            "error_rate": error_rate,
        }


webhook_manager = WebhookManager()
