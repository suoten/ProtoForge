"""测试结果通知渠道（v1.10.0）：Webhook / 钉钉 / 企业微信 / 邮件。

配置持久化在 ``data/notifiers.json``（经 API 管理，密码类字段读取时脱敏）：

    [
      {"type": "webhook", "url": "https://...", "events": ["test.completed", "test.failed"]},
      {"type": "dingtalk", "access_token": "...", "events": ["test.failed"]},
      {"type": "wecom", "key": "...", "events": ["test.completed"]},
      {"type": "email", "smtp_host": "...", "smtp_port": 465, "username": "...",
       "password": "...", "from_addr": "...", "to_addrs": ["qa@corp.com"],
       "use_tls": true, "events": ["test.completed", "test.failed"]}
    ]

事件：``test.completed``（每次跑完）/ ``test.failed``（失败/错误时）。
全部发送 fire-and-forget：通知失败只记日志，绝不影响测试执行结果。
"""

from __future__ import annotations

import asyncio
import json
import logging
import smtplib
import time
from email.mime.text import MIMEText
from email.utils import formataddr
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

SUPPORTED_TYPES = ("webhook", "dingtalk", "wecom", "email")
SENSITIVE_KEYS = {"password", "access_token", "key", "secret"}

_DEFAULT_EVENTS = ["test.completed", "test.failed"]


def notifiers_file() -> Path:
    from protoforge.core.paths import app_root
    return app_root() / "data" / "notifiers.json"


def load_notifiers() -> list[dict[str, Any]]:
    f = notifiers_file()
    if not f.exists():
        return []
    items: list = []
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
        if isinstance(data, list):
            items = data
    except Exception as e:
        logger.warning("notifiers config malformed: %s", e)
    return items


def save_notifiers(items: list[dict[str, Any]]) -> None:
    f = notifiers_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


def _masked(item: dict[str, Any]) -> dict[str, Any]:
    out = dict(item)
    for k in list(out):
        if k in SENSITIVE_KEYS and out[k]:
            v = str(out[k])
            out[k] = v[:4] + "****" if len(v) > 4 else "****"
    return out


def list_notifiers_masked() -> list[dict[str, Any]]:
    return [_masked(i) for i in load_notifiers()]


class NotifierDispatcher:
    """把一次测试运行分发给所有命中事件的渠道（全部后台执行）。"""

    def __init__(self, timeout: float = 10.0):
        self._timeout = timeout

    async def dispatch_test_run(self, run: dict[str, Any], server_url: str = "") -> int:
        """按 run 结果向各渠道推送。返回成功入队数（发送为后台任务）。"""
        status = str(run.get("status", "")).lower()
        failed = status in ("failed", "error", "aborted")
        tasks: list[asyncio.Task] = []
        for item in load_notifiers():
            ntype = str(item.get("type", "")).lower()
            if ntype not in SUPPORTED_TYPES:
                continue
            events = item.get("events") or _DEFAULT_EVENTS
            # 事件语义（精确匹配）：test.completed=通过时发；test.failed=失败时发。
            # 只订 test.failed 的渠道（如钉钉告警机器人）在通过时不打扰。
            want = ("test.completed" in events) if not failed else ("test.failed" in events)
            if not want:
                continue
            message = _format_message(run, server_url)
            if ntype == "webhook":
                payload = {"event": "test.failed" if failed else "test.completed",
                           "test_run": run}
                tasks.append(asyncio.create_task(
                    self._send_webhook(item.get("url", ""), payload)))
            elif ntype == "dingtalk":
                tasks.append(asyncio.create_task(
                    self._send_dingtalk(item, message)))
            elif ntype == "wecom":
                tasks.append(asyncio.create_task(
                    self._send_wecom(item, message)))
            elif ntype == "email":
                tasks.append(asyncio.create_task(
                    self._send_email(item, run, message)))
        ok = 0
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for r in results:
            if isinstance(r, Exception):
                logger.warning("notifier dispatch error: %s", r)
            else:
                ok += int(bool(r))
        return ok

    # -- 渠道实现 ---------------------------------------------------------

    async def _send_webhook(self, url: str, payload: dict[str, Any]) -> bool:
        sent = False
        if url:
            try:
                async with httpx.AsyncClient(timeout=self._timeout, trust_env=False) as client:
                    resp = await client.post(url, json=payload)
                    resp.raise_for_status()
                sent = True
            except Exception as e:
                logger.warning("webhook notify failed: %s", e)
        return sent

    async def _send_dingtalk(self, item: dict[str, Any], message: str) -> bool:
        token = item.get("access_token", "")
        url = (f"https://oapi.dingtalk.com/robot/send?access_token={token}"
               if token else "")
        body = {"msgtype": "markdown", "markdown": {
            "title": "ProtoForge 测试通知", "text": message}}
        sent = False
        if url:
            try:
                async with httpx.AsyncClient(timeout=self._timeout, trust_env=False) as client:
                    resp = await client.post(url, json=body)
                    resp.raise_for_status()
                sent = True
            except Exception as e:
                logger.warning("dingtalk notify failed: %s", e)
        return sent

    async def _send_wecom(self, item: dict[str, Any], message: str) -> bool:
        key = item.get("key", "")
        url = (f"https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key={key}"
               if key else "")
        body = {"msgtype": "markdown", "markdown": {"content": message}}
        sent = False
        if url:
            try:
                async with httpx.AsyncClient(timeout=self._timeout, trust_env=False) as client:
                    resp = await client.post(url, json=body)
                    resp.raise_for_status()
                sent = True
            except Exception as e:
                logger.warning("wecom notify failed: %s", e)
        return sent

    async def _send_email(self, item: dict[str, Any], run: dict[str, Any],
                          message: str) -> bool:
        host = item.get("smtp_host")
        to_addrs = item.get("to_addrs") or []
        if not host or not to_addrs:
            return False
        subject = f"[ProtoForge] 测试{ '失败' if str(run.get('status')).lower() in ('failed','error','aborted') else '完成' } - {run.get('plan_name') or run.get('plan_id', '')}"

        def _send() -> bool:
            msg = MIMEText(message, "html" if "<" in message else "plain", "utf-8")
            msg["Subject"] = subject
            msg["From"] = formataddr(("ProtoForge", item.get("from_addr") or item.get("username") or ""))
            msg["To"] = ", ".join(to_addrs)
            port = int(item.get("smtp_port", 465))
            use_tls = bool(item.get("use_tls", port == 465))
            if use_tls:
                with smtplib.SMTP_SSL(host, port, timeout=self._timeout) as s:
                    if item.get("username"):
                        s.login(item["username"], item.get("password", ""))
                    s.sendmail(msg["From"], to_addrs, msg.as_string())
            else:
                with smtplib.SMTP(host, port, timeout=self._timeout) as s:
                    if item.get("starttls"):
                        s.starttls()
                    if item.get("username"):
                        s.login(item["username"], item.get("password", ""))
                    s.sendmail(msg["From"], to_addrs, msg.as_string())
            return True

        sent = False
        try:
            sent = await asyncio.to_thread(_send)
        except Exception as e:
            logger.warning("email notify failed: %s", e)
        return sent


def _format_message(run: dict[str, Any], server_url: str = "") -> str:
    summary = run.get("results_summary") or {}
    status = str(run.get("status", "")).lower()
    icon = "✅" if status == "passed" else "❌"
    link = f"\n\n> 详情：{server_url}/test-runs/{run.get('id', '')}" if server_url else ""
    return (
        f"{icon} **ProtoForge 测试{'失败' if icon == '❌' else '完成'}**\n\n"
        f"- 计划：{run.get('plan_name') or run.get('plan_id', '')}"
        f"（v{run.get('plan_version', '')}）\n"
        f"- 状态：{status}\n"
        f"- 结果：总计 {summary.get('total', 0)} / 通过 {summary.get('passed', 0)}"
        f" / 失败 {summary.get('failed', 0)} / 错误 {summary.get('errors', 0)}"
        f" / 跳过 {summary.get('skipped', 0)}\n"
        f"- 用时：{summary.get('duration_seconds', '-')}s\n"
        f"- 时间：{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(float(run.get('end_time') or time.time())))}"
        f"{link}"
    )


_dispatcher = NotifierDispatcher()


async def notify_test_run(run: dict[str, Any], server_url: str = "") -> int:
    """模块级入口：测试跑完后调用。无配置时零开销。"""
    if not load_notifiers():
        return 0
    return await _dispatcher.dispatch_test_run(run, server_url)
