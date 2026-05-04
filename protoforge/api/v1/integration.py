import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Depends

from protoforge.api.v1.auth import require_operator, require_viewer

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/integration", tags=["integration"])


def _get_integration_manager():
    from protoforge.main import get_integration_manager
    return get_integration_manager()


@router.get("/status")
async def get_integration_status(_user: dict = Depends(require_viewer)):
    manager = _get_integration_manager()
    return manager.get_status()


@router.get("/metrics")
async def get_integration_metrics(_user: dict = Depends(require_viewer)):
    manager = _get_integration_manager()
    return manager.metrics.to_dict()


@router.post("/batch-push")
async def batch_push(request: dict[str, Any], _user: dict = Depends(require_operator)):
    from protoforge.main import get_engine
    engine = get_engine()
    manager = _get_integration_manager()

    device_ids = request.get("device_ids", [])
    if not isinstance(device_ids, list):
        raise HTTPException(status_code=400, detail="device_ids 必须是数组")
    protocol_filter = request.get("protocol", "")
    concurrency = request.get("concurrency", 10)
    if not isinstance(concurrency, int) or concurrency < 1:
        concurrency = 10
    elif concurrency > 50:
        concurrency = 50

    devices = []
    for did in device_ids:
        instance = engine.get_device_instance(did)
        if instance:
            if protocol_filter and instance.protocol != protocol_filter:
                continue
            devices.append(instance)

    if not devices:
        raise HTTPException(status_code=400, detail="未找到匹配的设备，请检查 device_ids 和 protocol 参数")

    result = await manager.batch_push(devices, concurrency=concurrency)
    return result


@router.post("/device/{device_id}/start")
async def start_device_collect(device_id: str, _user: dict = Depends(require_operator)):
    manager = _get_integration_manager()
    if not manager.is_connected():
        raise HTTPException(status_code=503, detail="Not connected to EdgeLite")
    result = await manager.send_device_control(device_id, "start_collect")
    return result


@router.post("/device/{device_id}/stop")
async def stop_device_collect(device_id: str, _user: dict = Depends(require_operator)):
    manager = _get_integration_manager()
    if not manager.is_connected():
        raise HTTPException(status_code=503, detail="Not connected to EdgeLite")
    result = await manager.send_device_control(device_id, "stop_collect")
    return result


@router.get("/protocols")
async def get_protocol_mappings(_user: dict = Depends(require_viewer)):
    manager = _get_integration_manager()
    raw_map = manager.protocol_mapper.get_map()
    protocol_map = {}
    for source, target in raw_map.items():
        result = manager.protocol_mapper.map(source)
        protocol_map[source] = {
            "protocol": target or "",
            "driver": target or "",
            "status": result.status,
        }
    return {
        "protocol_map": protocol_map,
        "supported_source_protocols": manager.protocol_mapper.get_supported_source_protocols(),
    }


@router.post("/validate")
async def validate_device_compatibility(request: dict[str, Any], _user: dict = Depends(require_viewer)):
    manager = _get_integration_manager()
    report = manager.validator.validate(
        device_id=request.get("device_id", ""),
        protocol=request.get("protocol", ""),
        points=request.get("points", []),
        driver_config=request.get("config", {}),
    )
    return {
        "compatible": report.compatible,
        "protocol_result": report.protocol_result,
        "data_type_results": report.data_type_results,
        "warnings": report.warnings,
        "errors": report.errors,
    }


@router.get("/backhaul-data")
async def get_backhaul_data(device_id: str = "", limit: int = 100, _user: dict = Depends(require_viewer)):
    manager = _get_integration_manager()
    return {"data": manager.get_backhaul_data(device_id=device_id, limit=limit)}


@router.get("/device-status")
async def get_device_status_cache(_user: dict = Depends(require_viewer)):
    manager = _get_integration_manager()
    return {"devices": manager.get_device_status_cache()}


@router.get("/alarm-rules")
async def get_alarm_reaction_rules(_user: dict = Depends(require_viewer)):
    manager = _get_integration_manager()
    return {"rules": [
        {"rule_id": r.rule_id, "source_device_id": r.source_device_id,
         "alarm_severity": r.alarm_severity, "action": r.action,
         "target_device_id": r.target_device_id, "enabled": r.enabled}
        for r in manager.get_alarm_reaction_rules()
    ]}


@router.post("/alarm-rules")
async def add_alarm_reaction_rule(request: dict[str, Any], _user: dict = Depends(require_operator)):
    from protoforge.core.integration.manager import AlarmReactionRule
    manager = _get_integration_manager()
    rule_id = request.get("rule_id", "")
    source_device_id = request.get("source_device_id", "")
    target_device_id = request.get("target_device_id", "")
    if not rule_id or not source_device_id or not target_device_id:
        raise HTTPException(status_code=400, detail="rule_id、source_device_id 和 target_device_id 为必填项")
    valid_actions = {"stop_device", "start_device", "inject_fault", "adjust_generator", "log_only", "send_alarm", "custom"}
    action = request.get("action", "stop_device")
    if action not in valid_actions:
        raise HTTPException(status_code=400, detail=f"无效的 action，可选值: {', '.join(valid_actions)}")
    rule = AlarmReactionRule(
        rule_id=rule_id,
        source_device_id=source_device_id,
        alarm_severity=request.get("alarm_severity", "warning"),
        action=action,
        target_device_id=target_device_id,
        action_params=request.get("action_params", {}),
        enabled=request.get("enabled", True),
    )
    manager.add_alarm_reaction_rule(rule)
    return {"status": "ok", "rule_id": rule.rule_id}


@router.delete("/alarm-rules/{rule_id}")
async def delete_alarm_reaction_rule(rule_id: str, _user: dict = Depends(require_operator)):
    manager = _get_integration_manager()
    manager.remove_alarm_reaction_rule(rule_id)
    return {"status": "ok"}


@router.post("/message")
async def handle_integration_message(request: dict[str, Any], _user: dict = Depends(require_operator)):
    msg_type = request.get("type", "")
    payload = request.get("payload", request)
    logger.info("Integration message received: type=%s", msg_type)
    manager = _get_integration_manager()
    if manager.is_connected():
        result = await manager.send_message(request)
        return {"status": "ok", "data": result}
    return {"status": "error", "error": "Not connected to integration target"}
