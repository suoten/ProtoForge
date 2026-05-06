import logging
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from protoforge.api.v1.auth import require_operator, require_viewer
from protoforge.api.v1._helpers import _get_log_bus

router = APIRouter()
logger = logging.getLogger(__name__)

_forward_engine = None


def _get_forward_engine():
    global _forward_engine
    if _forward_engine is None:
        from protoforge.core.forward import ForwardEngine
        _forward_engine = ForwardEngine(_get_log_bus())
    return _forward_engine


@router.get("/forward/targets")
async def list_forward_targets(_user: dict = Depends(require_viewer)):
    engine = _get_forward_engine()
    return engine.list_targets()


@router.post("/forward/targets")
async def add_forward_target(config: dict[str, Any], _user: dict = Depends(require_operator)):
    from protoforge.core.forward import create_target

    engine = _get_forward_engine()
    name = config.get("name", f"target-{int(time.time())}")
    if "host" in config and "url" not in config:
        host = config.get("host", "localhost")
        port = config.get("port", 8086)
        if not isinstance(port, int) or port < 1 or port > 65535:
            raise HTTPException(status_code=400, detail="port 必须是 1-65535 之间的整数")
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


@router.delete("/forward/targets/{name}")
async def remove_forward_target(name: str, _user: dict = Depends(require_operator)):
    engine = _get_forward_engine()
    engine.remove_target(name)
    return {"status": "ok"}


@router.post("/forward/start")
async def start_forward(_user: dict = Depends(require_operator)):
    engine = _get_forward_engine()
    try:
        await engine.start()
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to start forward: {str(e)}")


@router.post("/forward/stop")
async def stop_forward(_user: dict = Depends(require_operator)):
    engine = _get_forward_engine()
    try:
        await engine.stop()
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to stop forward: {str(e)}")


@router.get("/forward/stats")
async def forward_stats(_user: dict = Depends(require_viewer)):
    engine = _get_forward_engine()
    return engine.get_stats()
