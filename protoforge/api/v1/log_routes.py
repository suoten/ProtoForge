import asyncio
import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from protoforge.core.auth import verify_token
from protoforge.api.v1.auth import require_operator, require_viewer
from protoforge.api.v1._helpers import _get_log_bus

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/logs")
async def get_logs(
    count: int = 100,
    protocol: Optional[str] = None,
    device_id: Optional[str] = None,
    direction: Optional[str] = None,
    message_type: Optional[str] = None,
    _user: dict = Depends(require_viewer),
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
async def clear_logs(_user: dict = Depends(require_operator)):
    log_bus = _get_log_bus()
    log_bus.clear()
    return {"status": "ok", "message": "日志已清空"}


def _extract_ws_token(websocket: WebSocket) -> str | None:
    token = websocket.query_params.get("token", "")
    if token:
        return token
    return None


async def _ws_authenticate(websocket: WebSocket) -> tuple[bool, str]:
    from protoforge.api.v1.auth import is_no_auth

    if is_no_auth():
        return True, "admin"

    token = _extract_ws_token(websocket)
    if not token:
        try:
            msg = await asyncio.wait_for(websocket.receive_text(), timeout=10.0)
            try:
                msg_data = json.loads(msg)
                token = msg_data.get("token", "")
            except (ValueError, TypeError):
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
    await websocket.accept()
    from protoforge.api.v1._helpers import _get_engine
    engine = _get_engine()

    try:
        while True:
            devices = engine.list_devices()
            data = []
            for d in devices:
                try:
                    data.append(d.model_dump())
                except Exception as exc:
                    logger.debug("Device serialization fallback: %s", exc)
                    data.append({"id": d.id, "name": d.name, "protocol": d.protocol, "status": d.status.value})
            await websocket.send_json({"type": "devices", "data": data})

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


@router.websocket("/ws/logs")
async def ws_logs(websocket: WebSocket):
    ok, role = await _ws_authenticate(websocket)
    if not ok:
        return
    await websocket.accept()
    log_bus = _get_log_bus()
    queue = log_bus.subscribe()

    try:
        while True:
            try:
                entry = await asyncio.wait_for(queue.get(), timeout=30.0)
                await websocket.send_json({
                    "type": "log",
                    "data": {
                        "timestamp": entry.timestamp,
                        "protocol": entry.protocol,
                        "direction": entry.direction,
                        "device_id": entry.device_id,
                        "message_type": entry.message_type,
                        "summary": entry.summary,
                        "detail": entry.detail,
                    },

                })
            except asyncio.TimeoutError:
                try:
                    await websocket.send_json({"type": "ping"})
                except Exception as exc:
                    logger.debug("Log WebSocket ping failed: %s", exc)
                    break
    except WebSocketDisconnect:
        logger.debug("WebSocket /ws/logs disconnected")
    except Exception as e:
        logger.warning("WebSocket /ws/logs error: %s", e)
    finally:
        log_bus.unsubscribe(queue)
