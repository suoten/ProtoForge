import logging
import threading
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from protoforge.api.v1.auth import require_operator, require_viewer
from protoforge.api.v1._helpers import _get_log_bus

router = APIRouter()
logger = logging.getLogger(__name__)

_forward_engine = None
_forward_engine_lock = threading.Lock()


def _get_forward_engine():
    global _forward_engine
    if _forward_engine is None:  # FIXED: thread-safe singleton with double-checked locking
        with _forward_engine_lock:
            if _forward_engine is None:
                from protoforge.core.forward import ForwardEngine
                _forward_engine = ForwardEngine(_get_log_bus())
    return _forward_engine


@router.get("/forward/targets")
async def list_forward_targets(_user: dict = Depends(require_viewer)):
    try:
        engine = _get_forward_engine()
        return {"targets": engine.list_targets()}
    except Exception as e:
        logger.error("Failed to list forward targets: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to list forward targets: {e}") from e  # FIXED: 中文→英文


@router.post("/forward/targets")
async def add_forward_target(config: dict[str, Any], _user: dict = Depends(require_operator)):
    try:
        from protoforge.core.forward import create_target

        engine = _get_forward_engine()
        name = config.get("name", f"target-{int(time.time())}")
        if "host" in config and "url" not in config:
            host = config.get("host", "localhost")
            port = config.get("port", 8086)
            if not isinstance(port, int) or port < 1 or port > 65535:
                raise HTTPException(status_code=400, detail="port must be an integer between 1 and 65535")  # FIXED: 中文→英文
            protocol = config.get("protocol", "http")
            if protocol in ("influxdb",):
                config["url"] = f"http://{host}:{port}"
                config.setdefault("type", "influxdb")
            else:
                config["url"] = f"http://{host}:{port}"
                config.setdefault("type", "http")
        target = create_target(config)
        engine.add_target(name, target)
        return {"status": "ok", "name": name}
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.error("Failed to add forward target: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to add forward target: {e}") from e  # FIXED: 中文→英文


@router.delete("/forward/targets/{name}")
async def remove_forward_target(name: str, _user: dict = Depends(require_operator)):
    try:
        engine = _get_forward_engine()
        engine.remove_target(name)
        return {"status": "ok"}
    except Exception as e:
        logger.error("Failed to remove forward target: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to remove forward target: {e}") from e  # FIXED: 中文→英文


@router.post("/forward/start")
async def start_forward(_user: dict = Depends(require_operator)):
    engine = _get_forward_engine()
    try:
        await engine.start()
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to start data forwarding: {str(e)}")  # FIXED: 中文→英文


@router.post("/forward/stop")
async def stop_forward(_user: dict = Depends(require_operator)):
    engine = _get_forward_engine()
    try:
        await engine.stop()
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to stop data forwarding: {str(e)}")  # FIXED: 中文→英文


@router.get("/forward/stats")
async def forward_stats(_user: dict = Depends(require_viewer)):
    try:
        engine = _get_forward_engine()
        return engine.get_stats()
    except Exception as e:
        logger.error("Failed to get forward stats: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to get forward stats: {e}") from e  # FIXED: 中文→英文
