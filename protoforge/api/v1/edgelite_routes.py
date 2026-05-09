import logging
from typing import Any, Optional

from fastapi import APIRouter, Body, Depends, HTTPException

from protoforge.api.v1.auth import require_operator, require_viewer
from protoforge.api.v1._helpers import _get_engine

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/integration/edgelite")
async def import_edgelite(config: dict[str, Any], _user: dict = Depends(require_operator)):
    from protoforge.core.integration import import_edgelite_config
    engine = _get_engine()

    try:
        devices = import_edgelite_config(config)
        results = []
        for dev in devices:
            info = await engine.create_device(dev)
            results.append(info.model_dump())
        return {"status": "ok", "imported": len(results), "devices": results}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/integration/edgelite/push/{device_id}")
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
        raise HTTPException(status_code=502, detail=f"EdgeLite 推送失败: {e}")


@router.post("/integration/edgelite/test")
async def test_edgelite_connection(config: Optional[dict[str, Any]] = Body(default=None), _user: dict = Depends(require_operator)):
    from protoforge.core.edgelite import test_edgelite_connection as _test
    if config is None:
        config = {}

    url = config.get("url", "")
    username = config.get("username", "admin")
    password = config.get("password", "")

    if not url:
        return {"ok": False, "error": "请填写 EdgeLite 地址"}
    try:
        return await _test(url, username, password)
    except Exception as e:
        logger.error("EdgeLite connection test failed: %s", e)
        return {"ok": False, "error": f"连接测试异常: {e}"}


@router.get("/integration/edgelite/status/{device_id}")
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
        raise HTTPException(status_code=502, detail=f"EdgeLite 状态查询失败: {e}")


@router.get("/integration/edgelite/points/{device_id}")
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
        return points
    except Exception as e:
        logger.error("EdgeLite read points exception for %s: %s", device_id, e)
        raise HTTPException(status_code=502, detail=f"EdgeLite 测点读取失败: {e}")


@router.get("/integration/edgelite/pipeline/{device_id}")
async def verify_edgelite_pipeline(device_id: str, _user: dict = Depends(require_viewer)):
    from protoforge.core.edgelite import verify_edgelite_pipeline as _verify

    engine = _get_engine()
    instance = engine.get_device_instance(device_id)

    if not instance:
        raise HTTPException(status_code=404, detail="Device not found")

    try:
        result = await _verify(instance)
        if result.get("ok") and "collect" in result.get("steps", {}):
            collect_step = result["steps"]["collect"]
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
        raise HTTPException(status_code=502, detail=f"EdgeLite 管道验证失败: {e}")


@router.delete("/integration/edgelite/push/{device_id}")
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
        raise HTTPException(status_code=502, detail=f"EdgeLite 移除设备失败: {e}")


@router.post("/integration/pygbsentry")
async def import_pygbsentry(config: dict[str, Any], _user: dict = Depends(require_operator)):
    from protoforge.core.integration import import_pygbsentry_config
    engine = _get_engine()

    try:
        devices = import_pygbsentry_config(config)
        results = []

        for dev in devices:
            info = await engine.create_device(dev)
            results.append(info.model_dump())

        return {"status": "ok", "imported": len(results), "devices": results}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
