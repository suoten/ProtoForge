"""故障注入管理 REST API 端点。

提供以下端点：
  - POST   /api/v1/faults           注入故障
  - DELETE /api/v1/faults/{id}      移除故障
  - GET    /api/v1/faults              获取故障列表
  - POST   /api/v1/faults/clear     清除所有故障
  - POST   /api/v1/faults/{id}/activate   激活故障
  - POST   /api/v1/faults/{id}/deactivate 停用故障
  - GET    /api/v1/faults/scenarios  获取故障场景列表
  - POST   /api/v1/faults/scenarios  创建故障场景
"""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from protoforge.api.v1._helpers import _get_engine, _trigger_webhook_safe
from protoforge.api.v1.auth import require_operator, require_viewer
from protoforge.core.fault_injection import (
    FaultConfig,
    FaultType,
    TriggerMode,
)

router = APIRouter()
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
#  请求/响应模型
# ---------------------------------------------------------------------------

class CreateFaultRequest(BaseModel):
    """创建故障请求。"""
    device_id: str = Field(..., description="目标设备 ID")
    fault_type: str = Field(..., description="故障类型")
    target_point: str = Field("*", description="目标点位名称，'*' 表示所有点位")
    trigger_mode: str = Field("manual", description="触发模式: manual/random/scheduled/conditional")
    parameters: dict[str, Any] = Field(default_factory=dict, description="故障参数")
    probability: float = Field(0.0, description="随机触发概率 (RANDOM 模式)")
    start_time: float | None = Field(None, description="定时触发时间戳 (SCHEDULED 模式)")
    description: str = Field("", description="故障描述")
    auto_activate: bool = Field(True, description="创建后是否自动激活")


class FaultActionRequest(BaseModel):
    """故障操作请求。"""
    device_id: str = Field(..., description="设备 ID")


class ClearFaultsRequest(BaseModel):
    """清除故障请求。"""
    device_id: str | None = Field(None, description="设备 ID，None 表示所有设备")


# ---------------------------------------------------------------------------
#  辅助函数
# ---------------------------------------------------------------------------

def _get_device_instance(device_id: str):
    """获取设备实例，不存在则抛出 404。"""
    engine = _get_engine()
    instance = engine.get_device_instance(device_id)
    if instance is None:
        raise HTTPException(status_code=404, detail=f"Device not found: {device_id}")
    return instance


def _fault_config_to_dict(config: FaultConfig) -> dict[str, Any]:
    """将 FaultConfig 转为 API 响应字典。"""
    return config.to_dict()


# ---------------------------------------------------------------------------
#  API 端点
# ---------------------------------------------------------------------------

@router.post("/faults")
async def create_fault(req: CreateFaultRequest, _user: dict = Depends(require_operator)):
    """注入故障到指定设备。

    在目标设备上创建故障配置，可选自动激活。
    """
    instance = _get_device_instance(req.device_id)

    try:
        fault_type = FaultType(req.fault_type)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid fault type: {req.fault_type}. Valid types: {[t.value for t in FaultType]}",
        )

    try:
        trigger_mode = TriggerMode(req.trigger_mode)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid trigger mode: {req.trigger_mode}. Valid modes: {[m.value for m in TriggerMode]}",
        )

    config = FaultConfig(
        fault_type=fault_type,
        target_point=req.target_point,
        trigger_mode=trigger_mode,
        parameters=req.parameters,
        target_device=req.device_id,
        probability=req.probability,
        start_time=req.start_time,
        description=req.description,
    )

    fault_id = instance.inject_fault(config)

    if req.auto_activate:
        instance.activate_fault(fault_id)

    # WebSocket 事件推送
    await _trigger_webhook_safe("fault.activated", {
        "device_id": req.device_id,
        "fault_id": fault_id,
        "fault_type": fault_type.value,
        "target_point": req.target_point,
    })

    logger.info(
        "Fault injected: device=%s, fault_id=%s, type=%s",
        req.device_id, fault_id, fault_type.value,
    )

    return {
        "fault_id": fault_id,
        "device_id": req.device_id,
        "fault_type": fault_type.value,
        "target_point": req.target_point,
        "trigger_mode": trigger_mode.value,
        "active": req.auto_activate,
    }


@router.delete("/faults/{fault_id}")
async def delete_fault(fault_id: str, device_id: str, _user: dict = Depends(require_operator)):
    """从指定设备移除故障。"""
    instance = _get_device_instance(device_id)
    success = instance.remove_fault(fault_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Fault not found: {fault_id}")

    await _trigger_webhook_safe("fault.deactivated", {
        "device_id": device_id,
        "fault_id": fault_id,
    })

    return {"message": "Fault removed", "fault_id": fault_id, "device_id": device_id}


@router.get("/faults")
async def list_faults(device_id: str | None = None, _user: dict = Depends(require_viewer)):
    """获取故障列表。

    :param device_id: 设备 ID，不指定则返回所有设备的故障
    """
    engine = _get_engine()
    result = []

    if device_id:
        instance = engine.get_device_instance(device_id)
        if instance is None:
            raise HTTPException(status_code=404, detail=f"Device not found: {device_id}")
        for config in instance.get_all_faults():
            d = _fault_config_to_dict(config)
            d["device_id"] = device_id
            result.append(d)
    else:
        for dev_id, instance in engine.get_all_device_instances().items():
            for config in instance.get_all_faults():
                d = _fault_config_to_dict(config)
                d["device_id"] = dev_id
                result.append(d)

    return {"faults": result, "count": len(result)}


@router.post("/faults/clear")
async def clear_faults(req: ClearFaultsRequest, _user: dict = Depends(require_operator)):
    """清除故障。

    :param req.device_id: 设备 ID，None 表示清除所有设备的故障
    """
    engine = _get_engine()
    total_cleared = 0

    if req.device_id:
        instance = engine.get_device_instance(req.device_id)
        if instance is None:
            raise HTTPException(status_code=404, detail=f"Device not found: {req.device_id}")
        total_cleared = instance.clear_all_faults()
        await _trigger_webhook_safe("fault.cleared", {"device_id": req.device_id, "count": total_cleared})
    else:
        for _dev_id, instance in engine.get_all_device_instances().items():
            count = instance.clear_all_faults()
            total_cleared += count
        await _trigger_webhook_safe("fault.cleared", {"device_id": "*", "count": total_cleared})

    return {"message": "Faults cleared", "count": total_cleared}


@router.post("/faults/{fault_id}/activate")
async def activate_fault(fault_id: str, req: FaultActionRequest, _user: dict = Depends(require_operator)):
    """激活指定故障。"""
    instance = _get_device_instance(req.device_id)
    success = instance.activate_fault(fault_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Fault not found: {fault_id}")

    await _trigger_webhook_safe("fault.activated", {
        "device_id": req.device_id,
        "fault_id": fault_id,
    })

    return {"message": "Fault activated", "fault_id": fault_id, "device_id": req.device_id}


@router.post("/faults/{fault_id}/deactivate")
async def deactivate_fault(fault_id: str, req: FaultActionRequest, _user: dict = Depends(require_operator)):
    """停用指定故障。"""
    instance = _get_device_instance(req.device_id)
    success = instance.deactivate_fault(fault_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Fault not found: {fault_id}")

    await _trigger_webhook_safe("fault.deactivated", {
        "device_id": req.device_id,
        "fault_id": fault_id,
    })

    return {"message": "Fault deactivated", "fault_id": fault_id, "device_id": req.device_id}


@router.get("/faults/types")
async def list_fault_types(_user: dict = Depends(require_viewer)):
    """返回所有可用的故障类型和触发模式。"""
    return {
        "fault_types": [{"value": t.value, "name": t.name} for t in FaultType],
        "trigger_modes": [{"value": m.value, "name": m.name} for m in TriggerMode],
    }
