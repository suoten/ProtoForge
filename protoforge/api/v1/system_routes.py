"""System management API routes (settings, backup, network status)."""

import json
import logging
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from protoforge.api.v1._helpers import _get_database, _get_engine, _get_template_manager
from protoforge.api.v1.auth import require_admin, require_viewer

router = APIRouter()
logger = logging.getLogger(__name__)


def _get_version() -> str:
    try:
        from importlib.metadata import version as pkg_version
        return pkg_version("protoforge")
    except Exception as e:
        logger.debug("Failed to get package version: %s", e)
    try:
        import protoforge
        return getattr(protoforge, "__version__", "0.1.0")
    except Exception:
        return "0.1.0"  # FIXED: 内联fallback版本号，删除冗余_FALLBACK_VERSION常量


@router.post("/setup/demo")
async def setup_demo(_user: dict[str, Any] = Depends(require_admin)):
    engine = _get_engine()
    tm = _get_template_manager()
    from protoforge.core.demo import seed_demo_data
    try:
        await seed_demo_data(engine, tm)
        devices = engine.get_all_device_ids()
        scenarios = engine.get_all_scenario_configs()
        return {
            "status": "ok",
            "message": "Demo data created",
            "device_count": len(devices),
            "scenario_count": len(scenarios),
        }
    except HTTPException:
        raise  # FIXED: 防止 HTTPException 被 except Exception 吞掉重新包装为 500
    except Exception as e:
        logger.exception("Failed to setup demo: %s", e)
        from protoforge.core.defaults import get_friendly_error
        raise HTTPException(status_code=500, detail=get_friendly_error(str(e))) from e


@router.get("/setup/status")
async def setup_status(_user: dict[str, Any] = Depends(require_viewer)):
    try:
        engine = _get_engine()
        devices = engine.get_all_device_ids()
        scenarios = engine.get_all_scenario_configs()
        protocols_running = sum(1 for p in engine.get_all_protocol_servers().values() if p.status.value == "running")
        return {
            "initialized": len(devices) > 0,
            "demo_initialized": len(devices) > 0,
            "device_count": len(devices),
            "scenario_count": len(scenarios),
            "protocols_running": protocols_running,
            "templates_available": len(_get_template_manager().list_templates()),
        }
    except HTTPException:
        raise  # FIXED: 防止 HTTPException 被 except Exception 吞掉重新包装为 500
    except Exception as e:
        logger.exception("Failed to get setup status: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to get system status: {e}") from e


@router.get("/settings")
async def get_settings(_user: dict[str, Any] = Depends(require_admin)):
    try:
        from protoforge.config import get_all_settings_dict
        return get_all_settings_dict()
    except HTTPException:
        raise  # FIXED: 防止 HTTPException 被 except Exception 吞掉重新包装为 500
    except Exception as e:
        logger.exception("Failed to get settings: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to get settings: {e}") from e


_ALLOWED_SETTINGS_KEYS = {
    "port", "demo_mode", "log_level", "cors_origins", "min_password_length",
    "rate_limit_max_requests", "rate_limit_window_seconds",
    "rate_limit_auth_max_requests", "rate_limit_auth_window_seconds",
    "edgelite_url", "edgelite_username", "edgelite_password",
    "influxdb_url", "influxdb_token", "influxdb_org", "influxdb_bucket",
    "protoforge_public_host", "protocol_ports",
    "forward_enabled", "forward_interval",
    "tick_interval",
}


@router.put("/settings")
async def update_settings(updates: dict[str, Any], _user: dict[str, Any] = Depends(require_admin)):
    filtered = {k: v for k, v in updates.items() if k in _ALLOWED_SETTINGS_KEYS}
    if not filtered:
        raise HTTPException(status_code=400, detail="No valid settings keys provided")
    try:
        from protoforge.config import ConfigValidationError, get_all_settings_dict
        from protoforge.config import update_settings as _update_settings
        changed = _update_settings(filtered)

        # 热更新 IntegrationManager：当 EdgeLite 连接配置变更时，自动重新配置并重连
        edgelite_keys = {"edgelite_url", "edgelite_username", "edgelite_password"}
        if edgelite_keys & set(filtered.keys()):
            try:
                from protoforge.config import get_settings
                from protoforge.core.registry import get_integration_manager
                mgr = get_integration_manager()
                settings = get_settings()
                # 先停止旧连接
                await mgr.stop()
                # 重新配置
                mgr.configure(
                    edgelite_url=settings.edgelite_url,
                    username=settings.edgelite_username,
                    password=settings.edgelite_password,
                )
                # 重新启动连接
                await mgr.start()
                logger.info("IntegrationManager hot-reloaded after settings update")
            except RuntimeError:
                pass  # IntegrationManager 未初始化
            except Exception as e:
                logger.warning("Failed to hot-reload IntegrationManager: %s", e)

        return {"status": "ok", "changed": changed, "current": get_all_settings_dict()}
    except HTTPException:
        raise  # FIXED: 防止 HTTPException 被 except Exception 吞掉重新包装为 500
    except ConfigValidationError as e:
        raise HTTPException(status_code=422, detail="; ".join(e.errors)) from e
    except Exception as e:
        logger.exception("Failed to update settings: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to update settings: {e}") from e


@router.get("/audit")
async def query_audit_log(
    username: str | None = None,
    action: str | None = None,
    resource_type: str | None = None,
    start_time: float | None = None,
    end_time: float | None = None,
    limit: int = 100,
    offset: int = 0,
    _user: dict[str, Any] = Depends(require_admin),
):
    try:
        if limit < 1 or limit > 10000:
            limit = min(max(limit, 1), 10000)
        if offset < 0:
            offset = 0
        from protoforge.core.audit import audit_logger
        entries, total = await audit_logger.query(
            username=username, action=action, resource_type=resource_type,
            start_time=start_time, end_time=end_time,
            limit=limit, offset=offset,
        )
        return {"entries": entries, "total": total}
    except HTTPException:
        raise  # FIXED: 防止 HTTPException 被 except Exception 吞掉重新包装为 500
    except Exception as e:
        logger.exception("Failed to query audit log: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to query audit log: {e}") from e


@router.get("/audit/stats")
async def get_audit_stats(_user: dict[str, Any] = Depends(require_admin)):
    try:
        from protoforge.core.audit import audit_logger
        return await audit_logger.get_stats()
    except HTTPException:
        raise  # FIXED: 防止 HTTPException 被 except Exception 吞掉重新包装为 500
    except Exception as e:
        logger.exception("Failed to get audit stats: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to get audit stats: {e}") from e


@router.delete("/audit/{entry_id}")
async def delete_audit_entry(entry_id: int, _user: dict[str, Any] = Depends(require_admin)):
    raise HTTPException(status_code=403, detail="Audit log entries cannot be deleted. Audit logs are append-only for compliance.")


@router.delete("/audit")
async def clear_audit_log(
    before: float | None = None,
    _user: dict[str, Any] = Depends(require_admin),
):
    raise HTTPException(status_code=403, detail="Audit log cannot be cleared. Audit logs are append-only for compliance.")


@router.get("/backup")
async def export_backup(_user: dict[str, Any] = Depends(require_admin)):
    try:
        from fastapi.responses import Response
        db = _get_database()
        if db is None:
            raise HTTPException(status_code=503, detail="Database not initialized, cannot export backup")
        data = await db.export_all()
        backup = {
            "version": _get_version(),
            "timestamp": time.time(),
            "data": data,
        }
        content = json.dumps(backup, ensure_ascii=False, indent=2).encode("utf-8")
        return Response(
            content=content,
            media_type="application/json",
            headers={"Content-Disposition": f"attachment; filename=protoforge_backup_{int(time.time())}.json"},
        )
    except HTTPException:
        raise  # FIXED: 防止 HTTPException(503) 被 except Exception 吞掉重新包装为 500
    except Exception as e:
        logger.exception("Failed to export backup: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to export backup: {e}") from e


@router.post("/backup/restore")
async def import_backup(payload: dict[str, Any], _user: dict[str, Any] = Depends(require_admin)):
    try:
        db = _get_database()
        data = payload.get("data", {})
        if not isinstance(data, dict):
            raise HTTPException(status_code=400, detail="Backup 'data' must be a dictionary")
        if not data:
            raise HTTPException(status_code=400, detail="Backup file contains no data. Please add devices or scenario configurations in the system first, then export and re-upload the backup file.")
        restored = await db.import_all(data)
        return {"status": "ok", "restored": restored}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to import backup: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to restore backup: {e}") from e


@router.get("/error-stats")
async def get_error_stats(_user: dict[str, Any] = Depends(require_admin)):
    """获取 500 错误监控统计数据。

    返回总请求数、500 错误数、4xx 错误数、错误率、Top 错误路径和最近错误列表。
    """
    try:
        from protoforge.core.error_monitor import get_error_stats as _get_stats
        return _get_stats().get_stats()
    except HTTPException:
        raise  # FIXED: 防止 HTTPException 被 except Exception 吞掉重新包装为 500
    except Exception as e:
        logger.exception("Failed to get error stats: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to get error stats: {e}") from e


@router.post("/error-stats/reset")
async def reset_error_stats(_user: dict[str, Any] = Depends(require_admin)):
    """重置 500 错误监控统计数据。"""
    try:
        from protoforge.core.error_monitor import get_error_stats as _get_stats
        _get_stats().reset()
        return {"status": "ok"}
    except HTTPException:
        raise  # FIXED: 防止 HTTPException 被 except Exception 吞掉重新包装为 500
    except Exception as e:
        logger.exception("Failed to reset error stats: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to reset error stats: {e}") from e


# ── 协议地址格式指引 ──

_PROTOCOL_GUIDES: dict[str, dict[str, Any]] = {
    "s7": {
        "protocol_name": "Siemens S7 (S7Comm)",
        "address_format": "区域前缀 + 大小前缀 + 偏移量",
        "supported_areas": [
            {
                "area": "DB (数据块)",
                "formats": ["DB{n}.DBD{offset}", "DB{n}.DBW{offset}", "DB{n}.DBB{offset}", "DB{n}.DBX{offset}.{bit}"],
                "examples": ["DB1.DBD0", "DB1.DBW2", "DB1.DBB4", "DB1.DBX0.0", "DB2.DBD10"],
                "description": "数据块区域，{n}为DB号，D=双字(4字节)，W=字(2字节)，B=字节，X=位",
                "note": "S7-1200/1500优化块访问需在 protocol_config 中设置 optimized_db: true，系统会自动加2字节偏移",
            },
            {
                "area": "M (标记位/中间存储器)",
                "formats": ["M{offset}.{bit}", "MB{offset}", "MW{offset}", "MD{offset}"],
                "examples": ["M0.0", "MB0", "MW2", "MD4"],
                "description": "位存储区，用于中间运算结果。D=双字，W=字，B=字节",
            },
            {
                "area": "I (输入区)",
                "formats": ["I{offset}.{bit}", "IB{offset}", "IW{offset}", "ID{offset}"],
                "examples": ["I0.0", "IB0", "IW0", "ID4"],
                "description": "物理输入区，对应PLC的输入映像区。德语表示为 E(如 EW0)",
            },
            {
                "area": "Q (输出区)",
                "formats": ["Q{offset}.{bit}", "QB{offset}", "QW{offset}", "QD{offset}"],
                "examples": ["Q0.0", "QB0", "QW0", "QD4"],
                "description": "物理输出区，对应PLC的输出映像区。德语表示为 A(如 AW0)",
            },
            {
                "area": "T (定时器)",
                "formats": ["T{n}"],
                "examples": ["T1", "T5"],
                "description": "定时器区域，{n}为定时器编号",
            },
            {
                "area": "C (计数器)",
                "formats": ["C{n}"],
                "examples": ["C1", "C5"],
                "description": "计数器区域，{n}为计数器编号。德语表示为 Z(如 Z1)",
            },
        ],
        "data_types": ["bool", "int16", "uint16", "int32", "uint32", "float32", "float64", "string"],
        "protocol_config": {
            "rack": "机架号(默认0)",
            "slot": "槽号(S7-1200=1, S7-300=2, S7-1500=1)",
            "optimized_db": "布尔值，S7-1200/1500优化块访问设为true",
        },
        "tips": [
            "S7-1200/1500使用优化块访问时，DB数据区开头有2字节系统头，设置 optimized_db: true 可自动处理偏移",
            "同一DB块中的点位偏移不能重叠，建议按数据类型大小对齐(int32/float32对齐到4字节边界)",
            "M区域的偏移范围通常为0-255字节，I/Q区域为0-255字节",
            "使用德语地址格式(E/A/Z)与英语格式(I/Q/C)等效，系统自动识别",
        ],
    },
    "modbus": {
        "protocol_name": "Modbus TCP/RTU",
        "address_format": "功能码 + 偏移地址",
        "supported_areas": [
            {
                "area": "线圈 (Coil)",
                "formats": ["{address}"],
                "examples": ["0", "1", "100"],
                "description": "功能码01(读)/05(写单个)/0F(写多个)，地址范围0-65535",
            },
            {
                "area": "离散输入 (Discrete Input)",
                "formats": ["{address}"],
                "examples": ["10001", "10002"],
                "description": "功能码02(读)，只读，地址范围10001-19999",
            },
            {
                "area": "输入寄存器 (Input Register)",
                "formats": ["{address}"],
                "examples": ["30001", "30002"],
                "description": "功能码04(读)，只读，地址范围30001-39999",
            },
            {
                "area": "保持寄存器 (Holding Register)",
                "formats": ["{address}"],
                "examples": ["40001", "40002", "40010"],
                "description": "功能码03(读)/06(写单个)/10(写多个)，地址范围40001-49999",
            },
        ],
        "data_types": ["bool", "int16", "uint16", "int32", "uint32", "float32", "float64", "string"],
        "protocol_config": {
            "host": "监听地址(默认0.0.0.0)",
            "port": "Modbus TCP端口(默认502)",
            "slave_id": "从站地址(默认1)",
        },
        "tips": [
            "32位浮点数占用2个连续寄存器，地址需+2递增",
            "字符串类型使用多个连续寄存器存储，长度取决于字符串长度",
            "Modbus地址格式支持PDU格式(0-based)和PLC格式(5位数字前缀)",
        ],
    },
    "ab": {
        "protocol_name": "Rockwell AB EtherNet/IP (CIP)",
        "address_format": "标签名 (Tag-based)",
        "supported_areas": [
            {
                "area": "标签 (Tag)",
                "formats": ["{tag_name}", "{tag_name}.{member}", "{tag_name}[{index}]"],
                "examples": ["MyTag", "Motor.Speed", "Array[0]"],
                "description": "AB协议使用标签名寻址，而非地址偏移。支持基本标签、结构体成员、数组元素",
            },
        ],
        "data_types": ["bool", "int16", "uint16", "int32", "uint32", "float32", "float64", "string"],
        "protocol_config": {
            "host": "监听地址(默认0.0.0.0)",
            "port": "EtherNet/IP端口(默认44818)",
        },
        "tips": [
            "AB协议使用标签名(Tag Name)而非数字地址，每个点位name字段即为标签名",
            "标签名区分大小写，需与PLC中定义一致",
            "结构体类型使用点号访问成员(如 Motor.Speed)",
            "数组类型使用方括号索引(如 Array[0])",
        ],
    },
    "opcua": {
        "protocol_name": "OPC UA",
        "address_format": "NodeID",
        "supported_areas": [
            {
                "area": "节点 (Node)",
                "formats": [
                    "ns={namespace};s={string_identifier}",
                    "ns={namespace};i={numeric_identifier}",
                ],
                "examples": [
                    "ns=2;s=Temperature",
                    "ns=2;s=RoomTemp",
                    "ns=2;i=100",
                    "ns=3;s=MyVariable",
                ],
                "description": "OPC UA使用NodeID寻址。字符串标识符(s=)最常用，数字标识符(i=)适合程序化访问。建议在模板中显式指定address为ns=2;s=YourNodeName格式。",
            },
        ],
        "data_types": ["bool", "int16", "uint16", "int32", "uint32", "float32", "float64", "string"],
        "protocol_config": {
            "host": "监听地址(默认0.0.0.0)",
            "port": "OPC UA端口(默认4840)",
            "security_mode": "安全模式(None/Sign/SignAndEncrypt)",
            "security_policy": "安全策略(None/Basic128Rsa15/Basic256Sha256/Aes128Sha256RsaOaep/Aes256Sha256RsaPss)",
            "namespace": "设备命名空间URI(默认protoforge，映射到命名空间索引2)",
        },
        "tips": [
            "NodeID格式: ns={命名空间};s={字符串标识符} 最常用，如 ns=2;s=Temperature",
            "数字标识符格式: ns={命名空间};i={数字}，如 ns=2;i=100",
            "命名空间0为OPC UA标准命名空间，1为服务器命名空间，2为ProtoForge默认用户命名空间",
            "模板中address字段应使用 ns=2;s=YourNodeName 格式，确保客户端能按此NodeID找到节点",
            "若不指定address，系统将使用point.name作为字符串标识符，命名空间为2",
            "安全策略设为None时为明文传输，生产环境建议使用Basic256Sha256",
        ],
    },
    "mqtt": {
        "protocol_name": "MQTT",
        "address_format": "Topic",
        "supported_areas": [
            {
                "area": "主题 (Topic)",
                "formats": ["{topic_path}"],
                "examples": ["sensor/temperature", "device/status", "factory/line1/speed"],
                "description": "MQTT使用主题(Topic)进行消息路由，支持多级路径(用/分隔)",
            },
        ],
        "data_types": ["bool", "int16", "uint16", "int32", "uint32", "float32", "float64", "string", "json"],
        "protocol_config": {
            "host": "监听地址(默认0.0.0.0)",
            "port": "MQTT端口(默认1883, TLS=8883)",
            "qos": "服务质量等级(0/1/2)",
        },
        "tips": [
            "MQTT点位的address字段即为订阅/发布的Topic",
            "支持通配符: + 匹配单层, # 匹配多层(仅用于订阅)",
            "JSON类型点位可将整个JSON对象作为值发布",
        ],
    },
}


@router.get("/protocol-guide")
async def get_protocol_guide(protocol: str | None = None, _user: dict[str, Any] = Depends(require_viewer)):
    """获取各协议的地址格式指引和测试点定义说明。

    Args:
        protocol: 可选，指定协议名。不指定则返回所有协议的指引。

    Returns:
        协议地址格式说明，包括支持的区域、地址格式、示例、数据类型和配置参数。
    """
    if protocol:
        guide = _PROTOCOL_GUIDES.get(protocol)
        if not guide:
            raise HTTPException(status_code=404, detail=f"No guide available for protocol '{protocol}'. Supported: {', '.join(_PROTOCOL_GUIDES.keys())}")
        return {"protocol": protocol, **guide}
    return {"protocols": _PROTOCOL_GUIDES}


@router.get("/protocol-guide/supported")
async def list_supported_protocols(_user: dict[str, Any] = Depends(require_viewer)):
    """列出所有有地址格式指引的协议。"""
    return {"protocols": list(_PROTOCOL_GUIDES.keys())}
