"""Log streaming and device log WebSocket API routes."""

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect

from protoforge.api.v1._helpers import _get_log_bus
from protoforge.api.v1.auth import require_operator, require_viewer
from protoforge.core.auth import verify_token

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/logs")
async def get_logs(
    count: int = 100,
    protocol: str | None = None,
    device_id: str | None = None,
    direction: str | None = None,
    message_type: str | None = None,
    _user: dict[str, Any] = Depends(require_viewer),
):
    if count < 1:
        count = 1
    elif count > 1000:
        count = 1000

    log_bus = _get_log_bus()
    entries = log_bus.get_recent(count=count * 5, protocol=protocol, device_id=device_id)

    if direction:
        entries = [e for e in entries if e.get("direction") == direction]
    if message_type:
        entries = [e for e in entries if message_type in e.get("message_type", "")]
    return {"entries": entries[-count:]}


@router.delete("/logs")
async def clear_logs(_user: dict[str, Any] = Depends(require_operator)):
    log_bus = _get_log_bus()
    log_bus.clear()
    return {"status": "ok", "message": "Logs cleared"}


def _extract_ws_token(websocket: WebSocket) -> str | None:
    token = websocket.query_params.get("token", "")
    if token:
        return token
    return None


async def _ws_authenticate(websocket: WebSocket) -> tuple[bool, str]:
    """WebSocket 认证。必须先 accept 再验证/关闭，否则 close() 无效且 Starlette 会返回 403。"""
    from protoforge.api.v1.auth import is_no_auth

    if is_no_auth():
        await websocket.accept()
        return True, "admin"

    # 始终先 accept，确保后续 close() 能正常工作
    await websocket.accept()

    token = _extract_ws_token(websocket)
    if not token:
        # 等待客户端通过首帧发送 token
        try:
            msg = await asyncio.wait_for(websocket.receive_text(), timeout=10.0)
            try:
                msg_data = json.loads(msg)
                token = msg_data.get("token", "")
            except (json.JSONDecodeError, TypeError):
                token = msg
        except asyncio.TimeoutError:
            await websocket.close(code=4001, reason="Authentication timeout")
            return False, ""

    if not token:
        await websocket.close(code=4001, reason="Authentication required")
        return False, ""

    payload = verify_token(token)
    if payload is None:
        await websocket.close(code=4001, reason="Invalid token")
        return False, ""

    role = payload.get("role", "user")
    if role not in ("admin", "operator", "user", "viewer"):
        await websocket.close(code=4003, reason="Insufficient permissions")
        return False, ""

    return True, role


@router.websocket("/ws/devices")
async def ws_devices(websocket: WebSocket):
    ok, role = await _ws_authenticate(websocket)
    if not ok:
        return
    # _ws_authenticate 已经调用了 websocket.accept()
    from protoforge.api.v1._helpers import _get_engine
    engine = _get_engine()

    event_bus = getattr(engine, '_event_bus', None)
    proto_queue = None
    if event_bus:
        proto_queue = event_bus.subscribe("ProtocolStatusEvent")

    try:
        # FIXED-P1: 高频流量防护。原实现每轮循环都全量序列化并发送设备列表
        # （即使无变化），协议事件风暴时迭代加速到每秒上百次，前端全量重渲染。
        # 改为：协议事件批量排干（一帧最多 20 个）+ 设备列表仅在内容变化时发送。
        last_devices_payload: str | None = None
        while True:
            events = []
            if proto_queue is not None:
                try:
                    events.append(await asyncio.wait_for(proto_queue.get(), timeout=0.1))
                except asyncio.TimeoutError:
                    pass
                for _ in range(19):
                    try:
                        events.append(proto_queue.get_nowait())
                    except asyncio.QueueEmpty:
                        break
            else:
                await asyncio.sleep(0.1)
            if events:
                await websocket.send_json({
                    "type": "protocol_status_batch",
                    "data": [
                        {
                            "protocol_name": e.protocol_name,
                            "old_status": e.old_status,
                            "new_status": e.new_status,
                        }
                        for e in events
                    ],
                })
                if len(events) >= 20:
                    # 事件风暴下让出调度，避免忙转
                    await asyncio.sleep(0)

            devices = engine.list_devices()
            data = []
            for d in devices:
                try:
                    data.append(d.model_dump())
                except Exception as exc:
                    logger.debug("Device serialization fallback: %s", exc)
                    data.append({"id": d.id, "name": d.name, "protocol": d.protocol, "status": d.status.value})
            payload = json.dumps(data, ensure_ascii=False, default=str)
            if payload != last_devices_payload:
                await websocket.send_json({"type": "devices", "data": data})
                last_devices_payload = payload

            try:
                await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
            except asyncio.TimeoutError:
                try:
                    await websocket.send_json({"type": "ping"})
                except Exception as exc:
                    logger.debug("WebSocket ping failed: %s", exc)
                    break
    except WebSocketDisconnect:
        logger.debug("WebSocket /ws/devices disconnected")
    except Exception as e:
        logger.warning("WebSocket /ws/devices error: %s", e)
    finally:
        if event_bus and proto_queue:
            event_bus.unsubscribe("ProtocolStatusEvent", proto_queue)


@router.websocket("/ws/logs")
async def ws_logs(websocket: WebSocket):
    ok, role = await _ws_authenticate(websocket)
    if not ok:
        return
    # _ws_authenticate 已经调用了 websocket.accept()
    log_bus = _get_log_bus()
    queue = log_bus.subscribe()

    try:
        while True:
            # FIXED-P1: 批量下发。高流量场景（如多设备被持续轮询）下逐条发送
            # 会产生每秒上千个 WS 帧，前端逐帧全量重渲染直至崩溃。改为先阻塞
            # 等首条，再把队列中积压的日志一次打包成一帧（最多 200 条/帧）。
            batch: list[Any] = []
            try:
                batch.append(await asyncio.wait_for(queue.get(), timeout=30.0))
            except asyncio.TimeoutError:
                try:
                    await websocket.send_json({"type": "ping"})
                except Exception as exc:
                    logger.debug("Log WebSocket ping failed: %s", exc)
                    break
                continue
            for _ in range(199):
                try:
                    batch.append(queue.get_nowait())
                except asyncio.QueueEmpty:
                    break
            # 合并窗口（确定性，不依赖系统定时器）：yield 一次让事件循环把所有
            # 已就绪的投递回调批量执行完，队列汇入积压日志后再排干，帧数降低
            # 一个数量级以上。若依赖 asyncio.sleep 定时窗口，在部分 Windows
            # 机器上时钟异常会导致合并失效。
            await asyncio.sleep(0)
            for _ in range(199):
                try:
                    batch.append(queue.get_nowait())
                except asyncio.QueueEmpty:
                    break
            try:
                await websocket.send_json({
                    "type": "log_batch",
                    "data": [
                        {
                            "timestamp": entry.timestamp,
                            "protocol": entry.protocol,
                            "direction": entry.direction,
                            "device_id": entry.device_id,
                            "message_type": entry.message_type,
                            "summary": entry.summary,
                            "detail": entry.detail,
                        }
                        for entry in batch
                    ],
                })
            except Exception as exc:
                logger.debug("Log WebSocket batch send failed: %s", exc)
                break
    except WebSocketDisconnect:
        logger.debug("WebSocket /ws/logs disconnected")
    except Exception as e:
        logger.warning("WebSocket /ws/logs error: %s", e)
    finally:
        log_bus.unsubscribe(queue)
