import logging
from typing import Any

from fastapi import APIRouter, HTTPException

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/integration", tags=["integration"])


def _get_integration_manager():
    from protoforge.main import get_integration_manager
    return get_integration_manager()


@router.get("/status")
async def get_integration_status():
    manager = _get_integration_manager()
    return manager.get_status()


@router.get("/metrics")
async def get_integration_metrics():
    manager = _get_integration_manager()
    return manager.metrics.to_dict()


@router.post("/push-device/{device_id}")
async def push_device(device_id: str):
    from protoforge.main import get_engine
    engine = get_engine()
    manager = _get_integration_manager()

    instance = engine._devices.get(device_id)
    if not instance:
        raise HTTPException(status_code=404, detail=f"Device not found: {device_id}")

    result = await manager.push_device(instance)
    return result


@router.post("/batch-push")
async def batch_push(request: dict[str, Any]):
    from protoforge.main import get_engine
    engine = get_engine()
    manager = _get_integration_manager()

    device_ids = request.get("device_ids", [])
    protocol_filter = request.get("protocol", "")
    concurrency = request.get("concurrency", 10)

    devices = []
    for did in device_ids:
        instance = engine._devices.get(did)
        if instance:
            if protocol_filter and instance.protocol != protocol_filter:
                continue
            devices.append(instance)

    if not devices:
        raise HTTPException(status_code=400, detail="No matching devices found")

    result = await manager.batch_push(devices, concurrency=concurrency)
    return result


@router.delete("/device/{device_id}")
async def delete_device_from_edgelite(device_id: str):
    manager = _get_integration_manager()
    result = await manager.delete_device(device_id)
    return result


@router.post("/device/{device_id}/start")
async def start_device_collect(device_id: str):
    manager = _get_integration_manager()
    if not manager._channel or not manager._channel.is_connected:
        raise HTTPException(status_code=503, detail="Not connected to EdgeLite")
    result = await manager._channel.send({
        "type": "device_control",
        "payload": {"device_id": device_id, "action": "start_collect"},
    })
    return result


@router.post("/device/{device_id}/stop")
async def stop_device_collect(device_id: str):
    manager = _get_integration_manager()
    if not manager._channel or not manager._channel.is_connected:
        raise HTTPException(status_code=503, detail="Not connected to EdgeLite")
    result = await manager._channel.send({
        "type": "device_control",
        "payload": {"device_id": device_id, "action": "stop_collect"},
    })
    return result


@router.get("/protocols")
async def get_protocol_mappings():
    manager = _get_integration_manager()
    return {
        "protocol_map": manager.protocol_mapper.get_map(),
        "supported_source_protocols": manager.protocol_mapper.get_supported_source_protocols(),
    }


@router.post("/validate")
async def validate_device_compatibility(request: dict[str, Any]):
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


@router.post("/test-connection")
async def test_connection(request: dict[str, Any]):
    from protoforge.core.edgelite import test_edgelite_connection
    result = await test_edgelite_connection(
        url=request.get("url", ""),
        username=request.get("username", "admin"),
        password=request.get("password", ""),
    )
    return result


@router.get("/backhaul-data")
async def get_backhaul_data(device_id: str = "", limit: int = 100):
    manager = _get_integration_manager()
    return {"data": manager.get_backhaul_data(device_id=device_id, limit=limit)}


@router.get("/device-status")
async def get_device_status_cache():
    manager = _get_integration_manager()
    return {"devices": manager.get_device_status_cache()}


@router.get("/alarm-rules")
async def get_alarm_reaction_rules():
    manager = _get_integration_manager()
    return {"rules": [
        {"rule_id": r.rule_id, "source_device_id": r.source_device_id,
         "alarm_severity": r.alarm_severity, "action": r.action,
         "target_device_id": r.target_device_id, "enabled": r.enabled}
        for r in manager.get_alarm_reaction_rules()
    ]}


@router.post("/alarm-rules")
async def add_alarm_reaction_rule(request: dict[str, Any]):
    from protoforge.core.integration.manager import AlarmReactionRule
    manager = _get_integration_manager()
    rule = AlarmReactionRule(
        rule_id=request.get("rule_id", ""),
        source_device_id=request.get("source_device_id", ""),
        alarm_severity=request.get("alarm_severity", ""),
        action=request.get("action", "stop_device"),
        target_device_id=request.get("target_device_id", ""),
        action_params=request.get("action_params", {}),
        enabled=request.get("enabled", True),
    )
    manager.add_alarm_reaction_rule(rule)
    return {"ok": True, "rule_id": rule.rule_id}


@router.delete("/alarm-rules/{rule_id}")
async def delete_alarm_reaction_rule(rule_id: str):
    manager = _get_integration_manager()
    manager.remove_alarm_reaction_rule(rule_id)
    return {"ok": True}
