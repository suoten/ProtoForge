import logging
from typing import Any, Optional

from fastapi import APIRouter, Body, Depends, HTTPException

from protoforge.api.v1.auth import require_operator, require_viewer
from protoforge.api.v1._helpers import _get_engine

router = APIRouter(prefix="/edgelite", tags=["edgelite"])
logger = logging.getLogger(__name__)


@router.post("")
async def import_edgelite(config: dict[str, Any], _user: dict = Depends(require_operator)):
    from protoforge.core.integration import import_edgelite_config
    engine = _get_engine()

    try:
        devices = import_edgelite_config(config)
        results = []
        errors = []
        for dev in devices:
            try:
                info = await engine.create_device(dev)
                results.append(info.model_dump())
            except Exception as dev_err:
                logger.warning("Failed to import device %s: %s", getattr(dev, 'id', '?'), dev_err)
                errors.append({"device_id": getattr(dev, 'id', '?'), "error": str(dev_err)})
        resp = {"status": "ok" if not errors else "partial", "imported": len(results), "devices": results}
        if errors:
            resp["errors"] = errors
        # FIXED: 统一返回值格式 - 操作类接口返回裸对象
        return resp
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/push/{device_id}")
async def push_device_to_edgelite(device_id: str, _user: dict = Depends(require_operator)):
    from protoforge.core.edgelite import push_device_to_edgelite as _push
    engine = _get_engine()
    instance = engine.get_device_instance(device_id)

    if not instance:
        raise HTTPException(status_code=404, detail="Device not found")

    try:
        result = await _push(instance)
        if result.get("ok") is False and not result.get("skipped"):
            logger.warning("EdgeLite push failed for %s: %s", device_id, result.get("error", ""))
        return result
    except Exception as e:
        logger.error("EdgeLite push exception for %s: %s", device_id, e)
        raise HTTPException(status_code=502, detail=f"EdgeLite push failed: {e}")


@router.post("/test")
async def test_edgelite_connection(config: Optional[dict[str, Any]] = Body(default=None), _user: dict = Depends(require_operator)):
    from protoforge.core.edgelite import test_edgelite_connection as _test
    if config is None:
        config = {}

    url = config.get("url", "")
    username = config.get("username", "")
    password = config.get("password", "")

    if not url:
        raise HTTPException(status_code=400, detail="EdgeLite address is required")
    try:
        return await _test(url, username, password)
    except Exception as e:
        logger.error("EdgeLite connection test failed: %s", e)
        raise HTTPException(status_code=502, detail=f"EdgeLite connection test failed: {e}")


@router.get("/status/{device_id}")  # FIXED: 去掉多余的/edgelite前缀，router已有prefix="/edgelite"
async def get_edgelite_device_status(device_id: str, _user: dict = Depends(require_viewer)):
    from protoforge.core.edgelite import get_edgelite_device_status as _status

    engine = _get_engine()
    instance = engine.get_device_instance(device_id)

    if not instance:
        raise HTTPException(status_code=404, detail="Device not found")

    try:
        return await _status(instance)
    except Exception as e:
        logger.error("EdgeLite status check exception for %s: %s", device_id, e)
        raise HTTPException(status_code=502, detail=f"EdgeLite status query failed: {e}")


@router.get("/points/{device_id}")  # FIXED: 去掉多余的/edgelite前缀，router已有prefix="/edgelite"
async def read_edgelite_device_points(device_id: str, _user: dict = Depends(require_viewer)):
    from protoforge.core.edgelite import read_edgelite_device_points as _read

    engine = _get_engine()
    instance = engine.get_device_instance(device_id)

    if not instance:
        raise HTTPException(status_code=404, detail="Device not found")

    try:
        points = await _read(instance)
        if isinstance(points, list):
            return {"points": points}
        if isinstance(points, dict) and "points" in points:
            return points
        return {"points": points if points else []}
    except Exception as e:
        logger.error("EdgeLite read points exception for %s: %s", device_id, e)
        raise HTTPException(status_code=502, detail=f"EdgeLite point read failed: {e}")


@router.get("/pipeline/{device_id}")
async def verify_edgelite_pipeline(device_id: str, _user: dict = Depends(require_viewer)):
    from protoforge.core.edgelite import verify_edgelite_pipeline as _verify

    engine = _get_engine()
    instance = engine.get_device_instance(device_id)

    if not instance:
        raise HTTPException(status_code=404, detail="Device not found")

    try:
        result = await _verify(instance)
        # FIXED: 添加链式空值保护，避免steps["collect"]潜在的KeyError
        if result.get("ok") and "collect" in result.get("steps", {}):
            collect_step = result.get("steps", {}).get("collect", {})
            if collect_step.get("ok") and collect_step.get("has_real_data"):
                try:
                    local_points = await engine.read_device_points(device_id)
                    local_map = {p.name: p.value for p in local_points}
                    edgelite_data = collect_step.get("data", {})
                    if isinstance(edgelite_data, list):
                        edgelite_map = {}
                        for item in edgelite_data:
                            if isinstance(item, dict) and "name" in item:
                                edgelite_map[item["name"]] = item.get("value")
                            elif isinstance(item, dict) and "point_name" in item:
                                edgelite_map[item["point_name"]] = item.get("value")
                        edgelite_data = edgelite_map
                    elif not isinstance(edgelite_data, dict):
                        edgelite_data = {}
                    comparison = []

                    for name, local_val in local_map.items():
                        el_val = edgelite_data.get(name)
                        comparison.append({
                            "point": name,
                            "protoforge_value": local_val,
                            "edgelite_value": el_val,
                            "match": str(local_val) == str(el_val) if el_val is not None else None,
                        })
                    result["data_comparison"] = comparison
                except Exception as exc:
                    logger.debug("Data comparison failed: %s", exc)
        return result
    except Exception as e:
        logger.error("EdgeLite pipeline verification exception for %s: %s", device_id, e)
        raise HTTPException(status_code=502, detail=f"EdgeLite pipeline verification failed: {e}")


@router.delete("/push/{device_id}")  # FIXED: 去掉多余的/edgelite前缀，router已有prefix="/edgelite"
async def remove_device_from_edgelite(device_id: str, _user: dict = Depends(require_operator)):
    from protoforge.core.edgelite import remove_device_from_edgelite as _remove

    engine = _get_engine()
    instance = engine.get_device_instance(device_id)

    if not instance:
        raise HTTPException(status_code=404, detail="Device not found")

    try:
        return await _remove(instance)
    except Exception as e:
        logger.error("EdgeLite remove device exception for %s: %s", device_id, e)
        raise HTTPException(status_code=502, detail=f"EdgeLite device removal failed: {e}")


@router.post("/pygbsentry")
async def import_pygbsentry(config: dict[str, Any], _user: dict = Depends(require_operator)):
    from protoforge.core.integration import import_pygbsentry_config
    engine = _get_engine()

    try:
        devices = import_pygbsentry_config(config)
        results = []
        errors = []
        for dev in devices:
            try:
                info = await engine.create_device(dev)
                results.append(info.model_dump())
            except Exception as dev_err:
                logger.warning("Failed to import pygbsentry device %s: %s", getattr(dev, 'id', '?'), dev_err)
                errors.append({"device_id": getattr(dev, 'id', '?'), "error": str(dev_err)})
        resp = {"status": "ok" if not errors else "partial", "imported": len(results), "devices": results}
        if errors:
            resp["errors"] = errors
        return resp
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
