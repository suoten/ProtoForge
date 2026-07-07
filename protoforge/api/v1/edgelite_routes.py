"""EdgeLite 联调 API 路由 — 统一通过 IntegrationManager 调用

重构要点:
- 所有 EdgeLite 操作统一通过 IntegrationManager，不再直接调用 edgelite.py
- 新增 auto_fix 参数支持管线自修复
- 新增批量推送端点
"""

import logging
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query

from protoforge.api.v1._helpers import _get_engine
from protoforge.api.v1.auth import require_operator, require_viewer

router = APIRouter(prefix="/edgelite", tags=["edgelite"])
logger = logging.getLogger(__name__)


def _get_integration_manager():
    """获取 IntegrationManager 实例。"""
    from protoforge.main import get_integration_manager
    try:
        mgr = get_integration_manager()
    except RuntimeError:
        mgr = None
    if not mgr:
        raise HTTPException(status_code=503, detail="IntegrationManager not initialized")
    return mgr


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
        return resp
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/push/{device_id}")
async def push_device_to_edgelite(device_id: str, _user: dict = Depends(require_operator)):
    """推送设备到 EdgeLite — 通过 IntegrationManager 统一入口。"""
    mgr = _get_integration_manager()
    engine = _get_engine()
    instance = engine.get_device_instance(device_id)

    if not instance:
        raise HTTPException(status_code=404, detail="Device not found")

    try:
        result = await mgr.push_device(instance)
        if result is None:
            return {"ok": False, "error": "EdgeLite push returned no result", "error_type": "empty_response"}
        if result.get("ok") is False and not result.get("skipped"):
            logger.warning("EdgeLite push failed for %s: %s", device_id, result.get("error", ""))
        return result
    except Exception as e:
        logger.error("EdgeLite push exception for %s: %s", device_id, e)
        raise HTTPException(status_code=502, detail=f"EdgeLite push failed: {e}")


@router.post("/push")
async def batch_push_devices(
    device_ids: list[str] = Body(default=[], embed=True),
    _user: dict = Depends(require_operator),
):
    """批量推送设备到 EdgeLite。"""
    mgr = _get_integration_manager()
    engine = _get_engine()

    devices = []
    not_found = []
    for did in device_ids:
        instance = engine.get_device_instance(did)
        if instance:
            devices.append(instance)
        else:
            not_found.append(did)

    if not devices:
        raise HTTPException(status_code=404, detail="No devices found")

    try:
        result = await mgr.batch_push(devices)
        if not_found:
            result["not_found"] = not_found
        return result
    except Exception as e:
        logger.error("Batch push exception: %s", e)
        raise HTTPException(status_code=502, detail=f"Batch push failed: {e}")


@router.post("/test")
async def test_edgelite_connection(config: dict[str, Any] | None = Body(default=None), _user: dict = Depends(require_operator)):
    """测试 EdgeLite 网关连通性。"""
    mgr = _get_integration_manager()
    if config is None:
        config = {}

    url = config.get("url", "")
    username = config.get("username", "")
    password = config.get("password", "")

    if not url:
        raise HTTPException(status_code=400, detail="EdgeLite address is required")
    try:
        return await mgr.test_connection(url, username, password)
    except Exception as e:
        logger.error("EdgeLite connection test failed: %s", e)
        raise HTTPException(status_code=502, detail=f"EdgeLite connection test failed: {e}")


@router.get("/status/{device_id}")
async def get_edgelite_device_status(device_id: str, _user: dict = Depends(require_viewer)):
    """查询 EdgeLite 设备状态。"""
    mgr = _get_integration_manager()
    engine = _get_engine()
    instance = engine.get_device_instance(device_id)

    if not instance:
        raise HTTPException(status_code=404, detail="Device not found")

    try:
        return await mgr.get_device_status(instance)
    except Exception as e:
        logger.error("EdgeLite status check exception for %s: %s", device_id, e)
        raise HTTPException(status_code=502, detail=f"EdgeLite status query failed: {e}")


@router.get("/points/{device_id}")
async def read_edgelite_device_points(device_id: str, _user: dict = Depends(require_viewer)):
    """从 EdgeLite 读取设备数据点。"""
    mgr = _get_integration_manager()
    engine = _get_engine()
    instance = engine.get_device_instance(device_id)

    if not instance:
        raise HTTPException(status_code=404, detail="Device not found")

    try:
        result = await mgr.read_device_points(instance)
        if result.get("ok"):
            return result
        return result
    except Exception as e:
        logger.error("EdgeLite read points exception for %s: %s", device_id, e)
        raise HTTPException(status_code=502, detail=f"EdgeLite point read failed: {e}")


@router.get("/pipeline/{device_id}")
async def verify_edgelite_pipeline(
    device_id: str,
    auto_fix: bool = Query(default=True, description="自动修复管线问题"),
    _user: dict = Depends(require_viewer),
):
    """端到端管线验证，支持自动修复。"""
    mgr = _get_integration_manager()
    engine = _get_engine()
    instance = engine.get_device_instance(device_id)

    if not instance:
        raise HTTPException(status_code=404, detail="Device not found")

    try:
        result = await mgr.verify_pipeline(instance, auto_fix=auto_fix)
        # 数据比对
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
                        # 浮点数比较：容差 0.01
                        match = None
                        if el_val is not None:
                            try:
                                match = abs(float(local_val) - float(el_val)) < 0.01
                            except (ValueError, TypeError):
                                match = str(local_val) == str(el_val)
                        comparison.append({
                            "point": name,
                            "protoforge_value": local_val,
                            "edgelite_value": el_val,
                            "match": match,
                        })
                    result["data_comparison"] = comparison
                except Exception as exc:
                    logger.debug("Data comparison failed: %s", exc)
        return result
    except Exception as e:
        logger.error("EdgeLite pipeline verification exception for %s: %s", device_id, e)
        raise HTTPException(status_code=502, detail=f"EdgeLite pipeline verification failed: {e}")


@router.delete("/push/{device_id}")
async def remove_device_from_edgelite(device_id: str, _user: dict = Depends(require_operator)):
    """从 EdgeLite 删除设备。"""
    mgr = _get_integration_manager()
    engine = _get_engine()
    instance = engine.get_device_instance(device_id)

    if not instance:
        raise HTTPException(status_code=404, detail="Device not found")

    try:
        return await mgr.delete_device(instance)
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


@router.get("/integration/status")
async def get_integration_status(_user: dict = Depends(require_viewer)):
    """获取 IntegrationManager 状态。"""
    mgr = _get_integration_manager()
    return mgr.get_status()


@router.get("/integration/metrics")
async def get_integration_metrics(_user: dict = Depends(require_viewer)):
    """获取 IntegrationManager 指标。"""
    mgr = _get_integration_manager()
    return mgr.get_metrics()


@router.get("/integration/backhaul-data")
async def get_backhaul_data(
    device_id: str = Query(default="", description="设备ID，为空则返回全部"),
    limit: int = Query(default=100, ge=1, le=1000),
    _user: dict = Depends(require_viewer),
):
    """获取 EdgeLite 回传数据。"""
    mgr = _get_integration_manager()
    return {"data": mgr.get_backhaul_data(device_id=device_id, limit=limit)}


@router.get("/integration/protocols")
async def get_supported_protocols(_user: dict = Depends(require_viewer)):
    """获取 EdgeLite 支持的协议映射。"""
    mgr = _get_integration_manager()
    return {"protocol_map": mgr.get_protocol_map(), "supported_source_protocols": mgr.get_supported_source_protocols()}
