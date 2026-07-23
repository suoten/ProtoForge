"""Simulation enhancement API routes: snapshot, timeseries, replay, script test."""

import asyncio
import csv
import io
import json
import logging
import math
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from protoforge.api.v1._helpers import _get_database, _get_engine
from protoforge.api.v1.auth import require_operator, require_viewer

router = APIRouter()
logger = logging.getLogger(__name__)


# ─── 设备快照导入/导出 (Fix 4 + Fix 7) ──────────────────────────────────────


@router.post("/devices/{device_id}/import-snapshot")
async def import_device_snapshot(
    device_id: str,
    body: dict[str, Any],
    _user: dict[str, Any] = Depends(require_operator),
):
    """导入设备快照数据，批量设置点位初始值。

    请求体格式::

        {
            "point_values": {
                "temperature": 25.0,
                "pressure": 1.0,
                "motor_speed": 1500
            }
        }
    """
    engine = _get_engine()
    try:
        success = await engine.import_device_snapshot(device_id, body)
        return {"status": "ok" if success else "partial", "device_id": device_id}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        logger.exception("Failed to import snapshot for device %s: %s", device_id, e)
        raise HTTPException(status_code=500, detail=f"Failed to import snapshot: {e}") from e


@router.post("/devices/{device_id}/snapshots")
async def save_device_snapshot(
    device_id: str,
    body: dict[str, Any] | None = None,
    _user: dict[str, Any] = Depends(require_operator),
):
    """保存设备当前运行时状态快照到数据库。"""
    engine = _get_engine()
    name = (body or {}).get("name", "")
    try:
        snapshot_id = await engine.save_device_snapshot(device_id, name)
        return {"snapshot_id": snapshot_id, "device_id": device_id}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        logger.exception("Failed to save snapshot for device %s: %s", device_id, e)
        raise HTTPException(status_code=500, detail=f"Failed to save snapshot: {e}") from e


@router.get("/devices/{device_id}/snapshots")
async def list_device_snapshots(
    device_id: str,
    _user: dict[str, Any] = Depends(require_viewer),
):
    """列出设备的所有快照。"""
    db = _get_database()
    try:
        snapshots = await db.load_device_snapshots(device_id)
        return {"snapshots": snapshots}
    except Exception as e:
        logger.exception("Failed to list snapshots for device %s: %s", device_id, e)
        raise HTTPException(status_code=500, detail=f"Failed to list snapshots: {e}") from e


@router.get("/devices/{device_id}/snapshots/{snapshot_id}")
async def get_device_snapshot(
    device_id: str,
    snapshot_id: str,
    _user: dict[str, Any] = Depends(require_viewer),
):
    """获取单个设备快照。"""
    db = _get_database()
    try:
        snapshot = await db.load_device_snapshot(snapshot_id)
        if not snapshot:
            raise HTTPException(status_code=404, detail="Snapshot not found")
        return snapshot
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to get snapshot %s: %s", snapshot_id, e)
        raise HTTPException(status_code=500, detail=f"Failed to get snapshot: {e}") from e


@router.delete("/devices/{device_id}/snapshots/{snapshot_id}")
async def delete_device_snapshot(
    device_id: str,
    snapshot_id: str,
    _user: dict[str, Any] = Depends(require_operator),
):
    """删除设备快照。"""
    db = _get_database()
    try:
        await db.delete_device_snapshot(snapshot_id)
        return {"status": "ok"}
    except Exception as e:
        logger.exception("Failed to delete snapshot %s: %s", snapshot_id, e)
        raise HTTPException(status_code=500, detail=f"Failed to delete snapshot: {e}") from e


# ─── 时序数据查询与导出 (Fix 3 + Fix 6) ──────────────────────────────────────


@router.get("/devices/{device_id}/timeseries")
async def query_timeseries(
    device_id: str,
    point_name: str | None = Query(None),
    start_time: float | None = Query(None),
    end_time: float | None = Query(None),
    limit: int = Query(1000, ge=1, le=10000),
    _user: dict[str, Any] = Depends(require_viewer),
):
    """查询设备时序数据记录。"""
    db = _get_database()
    try:
        rows = await db.query_timeseries(
            device_id, point_name, start_time, end_time, limit,
        )
        return {"data": rows, "count": len(rows)}
    except Exception as e:
        logger.exception("Failed to query timeseries for device %s: %s", device_id, e)
        raise HTTPException(status_code=500, detail=f"Failed to query timeseries: {e}") from e


@router.get("/devices/{device_id}/export-data")
async def export_timeseries(
    device_id: str,
    format: str = Query("csv", pattern="^(csv|json)$"),
    point_name: str | None = Query(None),
    start_time: float | None = Query(None),
    end_time: float | None = Query(None),
    limit: int = Query(10000, ge=1, le=100000),
    _user: dict[str, Any] = Depends(require_viewer),
):
    """导出设备时序数据为 CSV 或 JSON 文件。"""
    db = _get_database()
    try:
        rows = await db.query_timeseries(
            device_id, point_name, start_time, end_time, limit,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to query timeseries: {e}") from e

    if format == "json":
        content = json.dumps(rows, ensure_ascii=False, indent=2)
        return StreamingResponse(
            io.BytesIO(content.encode("utf-8")),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{device_id}_timeseries.json"'},
        )
    else:
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["device_id", "point_name", "value", "quality", "timestamp"])
        for row in rows:
            writer.writerow([
                row.get("device_id", ""),
                row.get("point_name", ""),
                row.get("value", ""),
                row.get("quality", ""),
                row.get("timestamp", ""),
            ])
        content = output.getvalue()
        return StreamingResponse(
            io.BytesIO(content.encode("utf-8-sig")),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{device_id}_timeseries.csv"'},
        )


@router.post("/simulation/timeseries-recording")
async def configure_timeseries_recording(
    body: dict[str, Any],
    _user: dict[str, Any] = Depends(require_operator),
):
    """配置时序数据记录间隔。

    请求体::

        {"interval": 5.0}  // 5秒记录一次，0=禁用
    """
    engine = _get_engine()
    interval = float(body.get("interval", 0))
    if interval < 0 or math.isinf(interval) or math.isnan(interval):
        raise HTTPException(status_code=400, detail="interval must be a non-negative finite number")
    engine.configure_timeseries_recording(interval)
    return {"status": "ok", "interval": interval}


# ─── 从数据库回放历史数据 (Fix 10) ──────────────────────────────────────────


@router.post("/devices/{device_id}/replay-from-db")
async def replay_from_database(
    device_id: str,
    body: dict[str, Any] | None = None,
    _user: dict[str, Any] = Depends(require_operator),
):
    """从数据库时序数据创建回放源。

    请求体::

        {
            "point_name": "temperature",  // 可选，不指定则回放所有点位
            "start_time": 1234567890,    // 可选
            "end_time": 1234567990,      // 可选
            "limit": 5000,               // 可选
            "speed": 1.0,                // 回放速度
            "loop": false                // 是否循环
        }
    """
    engine = _get_engine()
    db = _get_database()
    cfg = body or {}

    try:
        rows = await db.query_timeseries(
            device_id,
            point_name=cfg.get("point_name"),
            start_time=cfg.get("start_time"),
            end_time=cfg.get("end_time"),
            limit=cfg.get("limit", 5000),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to query timeseries: {e}") from e

    if not rows:
        raise HTTPException(status_code=404, detail="No timeseries data found for the given criteria")

    # 转换为 TimeSeriesReplay 所需的长格式
    records = []
    for row in rows:
        records.append({
            "ts": row.get("timestamp", 0),
            "device_id": row.get("device_id", device_id),
            "point": row.get("point_name", ""),
            "value": _coerce_value(row.get("value", "")),
        })

    from protoforge.core.timeseries_replay import TimeSeriesReplay
    replay = TimeSeriesReplay(
        source=records,
        speed=cfg.get("speed", 1.0),
        loop=cfg.get("loop", False),
    )

    # 直接执行回放：将数据写入设备
    replay.start()
    written = 0
    while True:
        frame = replay.next_points()
        if frame is None:
            break
        for dev_id, point_name, value in frame:
            try:
                await engine.write_device_point(dev_id, point_name, value)
                written += 1
            except Exception as e:
                logger.debug("Replay write failed for %s.%s: %s", dev_id, point_name, e)

    return {"status": "ok", "frames": replay.frame_count, "points_written": written}


def _coerce_value(value_str: str) -> Any:
    """将字符串值转换为合适的类型。"""
    if value_str is None:
        return None
    s = str(value_str).strip()
    if s == "":
        return None
    low = s.lower()
    if low in ("true", "false"):
        return low == "true"
    try:
        return int(s)
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        pass
    return s


# ─── 数据生成公式测试 (Fix 11) ──────────────────────────────────────────────


@router.post("/simulation/test-script")
async def test_generator_script(
    body: dict[str, Any],
    _user: dict[str, Any] = Depends(require_viewer),
):
    """测试数据生成脚本表达式，返回计算结果。

    请求体::

        {
            "script": "result = sin(elapsed * 0.1) * 50 + 50",
            "elapsed": 10.0,
            "min_value": 0,
            "max_value": 100,
            "point_name": "test_point",
            "point_address": "HR100"
        }
    """
    from protoforge.core.generator import ScriptEngine

    script = body.get("script", "result = 0")
    if not script or not isinstance(script, str):
        raise HTTPException(status_code=400, detail="script is required and must be a string")

    context = {
        "elapsed": float(body.get("elapsed", 0)),
        "min_value": body.get("min_value"),
        "max_value": body.get("max_value"),
        "point_name": body.get("point_name", ""),
        "point_address": body.get("point_address", ""),
    }

    try:
        engine = ScriptEngine()
        value = engine.execute(script, context)
        return {
            "result": value,
            "script": script,
            "context": context,
        }
    except Exception as e:
        return {
            "result": None,
            "error": str(e),
            "script": script,
        }


# ─── 故障注入规则预设模板 (Fix 12) ──────────────────────────────────────────


FAULT_PRESET_TEMPLATES: list[dict[str, Any]] = [
    {
        "id": "sensor-drift",
        "name": "传感器漂移",
        "description": "传感器读数缓慢偏移，模拟传感器老化",
        "fault_type": "sensor_drift",
        "parameters": {"drift_rate": 0.1, "max_drift": 5.0},
        "trigger_mode": "manual",
        "target_point": "*",
    },
    {
        "id": "sensor-noise",
        "name": "传感器噪声",
        "description": "传感器读数叠加随机噪声",
        "fault_type": "sensor_noise",
        "parameters": {"noise_amplitude": 2.0, "noise_type": "gaussian"},
        "trigger_mode": "manual",
        "target_point": "*",
    },
    {
        "id": "sensor-stuck",
        "name": "传感器卡死",
        "description": "传感器读数冻结在当前值，不再更新",
        "fault_type": "sensor_stuck",
        "parameters": {},
        "trigger_mode": "manual",
        "target_point": "*",
    },
    {
        "id": "communication-loss",
        "name": "通信中断",
        "description": "设备通信完全中断，不响应任何请求",
        "fault_type": "communication_loss",
        "parameters": {"delay_ms": 0},
        "trigger_mode": "manual",
        "target_point": "*",
    },
    {
        "id": "device-failure",
        "name": "设备故障",
        "description": "设备完全故障，进入 ERROR 状态，输出安全值",
        "fault_type": "device_failure",
        "parameters": {},
        "trigger_mode": "manual",
        "target_point": "*",
    },
    {
        "id": "value-offset",
        "name": "值偏移",
        "description": "所有读数叠加固定偏移量",
        "fault_type": "value_offset",
        "parameters": {"offset": 10.0},
        "trigger_mode": "manual",
        "target_point": "*",
    },
    {
        "id": "value-saturation",
        "name": "值饱和",
        "description": "读数被限制在指定范围内",
        "fault_type": "value_saturation",
        "parameters": {"min_saturation": 0, "max_saturation": 100},
        "trigger_mode": "manual",
        "target_point": "*",
    },
    {
        "id": "intermittent-signal-loss",
        "name": "间歇性信号丢失",
        "description": "周期性信号丢失，模拟接触不良",
        "fault_type": "intermittent",
        "parameters": {"probability": 0.1, "interval_ms": 1000},
        "trigger_mode": "periodic",
        "target_point": "*",
    },
    {
        "id": "calibration-error",
        "name": "校准误差",
        "description": "读数乘以固定系数，模拟校准偏差",
        "fault_type": "calibration_error",
        "parameters": {"scale_factor": 1.05},
        "trigger_mode": "manual",
        "target_point": "*",
    },
]


@router.get("/simulation/fault-templates")
async def list_fault_templates(_user: dict[str, Any] = Depends(require_viewer)):
    """获取故障注入规则预设模板列表。"""
    return {"templates": FAULT_PRESET_TEMPLATES}


@router.get("/simulation/fault-templates/{template_id}")
async def get_fault_template(
    template_id: str,
    _user: dict[str, Any] = Depends(require_viewer),
):
    """获取单个故障注入模板。"""
    for t in FAULT_PRESET_TEMPLATES:
        if t["id"] == template_id:
            return t
    raise HTTPException(status_code=404, detail=f"Fault template not found: {template_id}")


# ─── 仿真 vs 真实设备自动对比 (Fix 5) ──────────────────────────────────────


@router.post("/devices/{device_id}/compare")
async def compare_device_with_snapshot(
    device_id: str,
    body: dict[str, Any] | None = None,
    _user: dict[str, Any] = Depends(require_viewer),
):
    """对比仿真设备当前值与真实设备快照数据，生成偏差报告。

    请求体::\n

        {
            "snapshot_id": "uuid-of-snapshot",   // 可选，不指定则用最新快照
            "point_names": ["temp", "pressure"]   // 可选，不指定则对比所有点位
        }

    返回::

        {
            "device_id": "device_001",
            "snapshot_id": "uuid",
            "timestamp": 1234567890.0,
            "points": [
                {
                    "name": "temperature",
                    "simulated": 25.3,
                    "real": 25.0,
                    "absolute_error": 0.3,
                    "relative_error": 0.012,
                    "within_tolerance": true
                }
            ],
            "summary": {
                "point_count": 5,
                "within_tolerance": 4,
                "out_of_tolerance": 1,
                "mae": 0.52,          // Mean Absolute Error
                "rmse": 0.78,         // Root Mean Square Error
                "max_error": 1.5,
                "max_error_point": "pressure",
                "overall_pass": false
            }
        }
    """
    engine = _get_engine()
    db = _get_database()
    cfg = body or {}

    # 获取设备实例
    instance = engine.get_device_instance(device_id)
    if not instance:
        raise HTTPException(status_code=404, detail=f"Device not found: {device_id}")

    # 获取快照
    snapshot_id = cfg.get("snapshot_id")
    if snapshot_id:
        snapshot = await db.load_device_snapshot(snapshot_id)
        if not snapshot:
            raise HTTPException(status_code=404, detail="Snapshot not found")
    else:
        snapshots = await db.load_device_snapshots(device_id)
        if not snapshots:
            raise HTTPException(status_code=404, detail="No snapshots found for device")
        snapshot = snapshots[0]

    real_values = snapshot.get("point_values", {})
    if not isinstance(real_values, dict):
        raise HTTPException(status_code=400, detail="Invalid snapshot format: point_values must be a dict")

    # 获取仿真值
    sim_points = instance.read_all_points()
    sim_map = {p.name: p.value for p in sim_points}

    # 筛选对比点位
    point_filter = cfg.get("point_names")
    if point_filter and isinstance(point_filter, list):
        all_points = set(point_filter)
    else:
        all_points = set(sim_map.keys()) | set(real_values.keys())

    # 容差配置（默认 5%）
    tolerance_pct = float(cfg.get("tolerance_pct", 5.0)) / 100.0
    tolerance_abs = float(cfg.get("tolerance_abs", 0.0))

    point_results = []
    abs_errors = []
    sq_errors = []
    max_error = 0.0
    max_error_point = ""

    for name in sorted(all_points):
        sim_val = sim_map.get(name)
        real_val = real_values.get(name)

        if sim_val is None or real_val is None:
            point_results.append({
                "name": name,
                "simulated": sim_val,
                "real": real_val,
                "absolute_error": None,
                "relative_error": None,
                "within_tolerance": False,
                "skipped": True,
            })
            continue

        # 转换为 float 进行比较
        try:
            sim_f = float(sim_val)
            real_f = float(real_val)
        except (ValueError, TypeError):
            # 非数值类型，做字符串比较
            match = str(sim_val) == str(real_val)
            point_results.append({
                "name": name,
                "simulated": sim_val,
                "real": real_val,
                "absolute_error": 0.0 if match else 1.0,
                "relative_error": 0.0 if match else 1.0,
                "within_tolerance": match,
            })
            continue

        abs_err = abs(sim_f - real_f)
        rel_err = abs_err / abs(real_f) if abs(real_f) > 1e-10 else (abs_err if abs_err > 0 else 0.0)
        within = abs_err <= tolerance_abs or rel_err <= tolerance_pct

        point_results.append({
            "name": name,
            "simulated": sim_f,
            "real": real_f,
            "absolute_error": round(abs_err, 6),
            "relative_error": round(rel_err, 6),
            "within_tolerance": within,
        })

        abs_errors.append(abs_err)
        sq_errors.append(abs_err * abs_err)
        if abs_err > max_error:
            max_error = abs_err
            max_error_point = name

    within_count = sum(1 for r in point_results if r.get("within_tolerance") and not r.get("skipped"))
    out_count = sum(1 for r in point_results if not r.get("within_tolerance") and not r.get("skipped"))
    total_compared = within_count + out_count

    mae = sum(abs_errors) / len(abs_errors) if abs_errors else 0.0
    rmse = math.sqrt(sum(sq_errors) / len(sq_errors)) if sq_errors else 0.0

    return {
        "device_id": device_id,
        "snapshot_id": snapshot.get("id", ""),
        "timestamp": snapshot.get("timestamp", 0),
        "points": point_results,
        "summary": {
            "point_count": total_compared,
            "within_tolerance": within_count,
            "out_of_tolerance": out_count,
            "mae": round(mae, 6),
            "rmse": round(rmse, 6),
            "max_error": round(max_error, 6),
            "max_error_point": max_error_point,
            "overall_pass": out_count == 0,
        },
    }


@router.post("/devices/{device_id}/compare-timeseries")
async def compare_device_with_timeseries(
    device_id: str,
    body: dict[str, Any],
    _user: dict[str, Any] = Depends(require_viewer),
):
    """对比仿真设备当前值与历史时序数据的平均值，生成偏差报告。

    请求体::\n

        {
            "start_time": 1234567890,
            "end_time": 1234567990,
            "point_names": ["temp", "pressure"],  // 可选
            "aggregation": "avg"  // avg/min/max/last
        }
    """
    engine = _get_engine()
    db = _get_database()

    instance = engine.get_device_instance(device_id)
    if not instance:
        raise HTTPException(status_code=404, detail=f"Device not found: {device_id}")

    start_time = body.get("start_time")
    end_time = body.get("end_time")
    if not start_time or not end_time:
        raise HTTPException(status_code=400, detail="start_time and end_time are required")

    aggregation = body.get("aggregation", "avg")
    point_filter = body.get("point_names")

    # 查询时序数据
    rows = await db.query_timeseries(
        device_id,
        point_name=None,
        start_time=start_time,
        end_time=end_time,
        limit=10000,
    )

    if not rows:
        raise HTTPException(status_code=404, detail="No timeseries data found in the specified range")

    # 按点位分组并计算聚合值
    grouped: dict[str, list[float]] = {}
    for row in rows:
        pn = row.get("point_name", "")
        if point_filter and pn not in point_filter:
            continue
        try:
            val = float(row.get("value", ""))
            grouped.setdefault(pn, []).append(val)
        except (ValueError, TypeError):
            continue

    # 计算聚合
    real_map: dict[str, float] = {}
    for pn, values in grouped.items():
        if not values:
            continue
        if aggregation == "min":
            real_map[pn] = min(values)
        elif aggregation == "max":
            real_map[pn] = max(values)
        elif aggregation == "last":
            real_map[pn] = values[-1]
        else:  # avg
            real_map[pn] = sum(values) / len(values)

    # 获取仿真值
    sim_points = instance.read_all_points()
    sim_map = {p.name: p.value for p in sim_points}

    # 对比
    tolerance_pct = float(body.get("tolerance_pct", 5.0)) / 100.0
    tolerance_abs = float(body.get("tolerance_abs", 0.0))

    point_results = []
    abs_errors = []
    sq_errors = []
    max_error = 0.0
    max_error_point = ""

    for name in sorted(set(sim_map.keys()) | set(real_map.keys())):
        sim_val = sim_map.get(name)
        real_val = real_map.get(name)

        if sim_val is None or real_val is None:
            point_results.append({
                "name": name,
                "simulated": sim_val,
                "real": real_val,
                "absolute_error": None,
                "relative_error": None,
                "within_tolerance": False,
                "skipped": True,
            })
            continue

        try:
            sim_f = float(sim_val)
            real_f = float(real_val)
        except (ValueError, TypeError):
            continue

        abs_err = abs(sim_f - real_f)
        rel_err = abs_err / abs(real_f) if abs(real_f) > 1e-10 else (abs_err if abs_err > 0 else 0.0)
        within = abs_err <= tolerance_abs or rel_err <= tolerance_pct

        point_results.append({
            "name": name,
            "simulated": sim_f,
            "real": round(real_f, 6),
            "absolute_error": round(abs_err, 6),
            "relative_error": round(rel_err, 6),
            "within_tolerance": within,
            "sample_count": len(grouped.get(name, [])),
        })

        abs_errors.append(abs_err)
        sq_errors.append(abs_err * abs_err)
        if abs_err > max_error:
            max_error = abs_err
            max_error_point = name

    within_count = sum(1 for r in point_results if r.get("within_tolerance") and not r.get("skipped"))
    out_count = sum(1 for r in point_results if not r.get("within_tolerance") and not r.get("skipped"))
    total_compared = within_count + out_count

    mae = sum(abs_errors) / len(abs_errors) if abs_errors else 0.0
    rmse = math.sqrt(sum(sq_errors) / len(sq_errors)) if sq_errors else 0.0

    return {
        "device_id": device_id,
        "aggregation": aggregation,
        "time_range": {"start": start_time, "end": end_time},
        "points": point_results,
        "summary": {
            "point_count": total_compared,
            "within_tolerance": within_count,
            "out_of_tolerance": out_count,
            "mae": round(mae, 6),
            "rmse": round(rmse, 6),
            "max_error": round(max_error, 6),
            "max_error_point": max_error_point,
            "overall_pass": out_count == 0,
        },
    }


# ─── P2: 批量对比 + 持续漂移监控 + 导出 ──────────────────────────────────────

# 全局漂移监控器实例
_drift_monitors: dict[str, dict[str, Any]] = {}


@router.post("/devices/batch-compare")
async def batch_compare_devices(
    body: dict[str, Any],
    _user: dict[str, Any] = Depends(require_viewer),
):
    """批量对比多个仿真设备与各自最新快照，生成汇总报告。

    请求体::\n

        {
            "device_ids": ["dev_001", "dev_002"],
            "tolerance_pct": 5.0,
            "tolerance_abs": 0.0
        }
    """
    engine = _get_engine()
    db = _get_database()
    device_ids = body.get("device_ids", [])
    if not device_ids:
        all_ids = engine.get_all_device_ids()
        device_ids = all_ids

    tolerance_pct = float(body.get("tolerance_pct", 5.0)) / 100.0
    tolerance_abs = float(body.get("tolerance_abs", 0.0))

    results = []
    passed = 0
    failed = 0

    for dev_id in device_ids:
        instance = engine.get_device_instance(dev_id)
        if not instance:
            results.append({"device_id": dev_id, "error": "Device not found", "overall_pass": False})
            failed += 1
            continue

        snapshots = await db.load_device_snapshots(dev_id)
        if not snapshots:
            results.append({"device_id": dev_id, "error": "No snapshots found", "overall_pass": False})
            failed += 1
            continue

        snapshot = snapshots[0]
        real_values = snapshot.get("point_values", {})
        sim_points = instance.read_all_points()
        sim_map = {p.name: p.value for p in sim_points}

        abs_errors = []
        for name in sorted(set(sim_map.keys()) | set(real_values.keys())):
            sim_val = sim_map.get(name)
            real_val = real_values.get(name)
            if sim_val is None or real_val is None:
                continue
            try:
                abs_err = abs(float(sim_val) - float(real_val))
                abs_errors.append(abs_err)
            except (ValueError, TypeError):
                continue

        mae = sum(abs_errors) / len(abs_errors) if abs_errors else 0.0
        max_err = max(abs_errors) if abs_errors else 0.0
        overall_pass = max_err <= tolerance_abs or (mae / max(abs(max_err), 1e-10)) <= tolerance_pct

        results.append({
            "device_id": dev_id,
            "snapshot_id": snapshot.get("id", ""),
            "point_count": len(abs_errors),
            "mae": round(mae, 6),
            "max_error": round(max_err, 6),
            "overall_pass": overall_pass,
        })
        if overall_pass:
            passed += 1
        else:
            failed += 1

    return {
        "total_devices": len(device_ids),
        "passed": passed,
        "failed": failed,
        "results": results,
    }


@router.post("/devices/{device_id}/drift-monitor/start")
async def start_drift_monitor(
    device_id: str,
    body: dict[str, Any],
    _user: dict[str, Any] = Depends(require_operator),
):
    """启动持续漂移监控 — 周期性自动对比仿真值与最新快照。"""
    if device_id in _drift_monitors:
        raise HTTPException(status_code=409, detail="Drift monitor already running for this device")

    interval = float(body.get("interval_seconds", 60))
    tolerance_pct = float(body.get("tolerance_pct", 5.0)) / 100.0

    monitor_state: dict[str, Any] = {
        "device_id": device_id,
        "interval": interval,
        "tolerance_pct": tolerance_pct,
        "running": True,
        "history": [],
        "task": None,
    }

    async def _monitor_loop():
        engine = _get_engine()
        db = _get_database()
        while monitor_state["running"]:
            try:
                await asyncio.sleep(interval)
                instance = engine.get_device_instance(device_id)
                if not instance:
                    continue
                snapshots = await db.load_device_snapshots(device_id)
                if not snapshots:
                    continue
                snapshot = snapshots[0]
                real_values = snapshot.get("point_values", {})
                sim_points = instance.read_all_points()
                sim_map = {p.name: p.value for p in sim_points}

                abs_errors = []
                for name in sorted(set(sim_map.keys()) | set(real_values.keys())):
                    sim_val = sim_map.get(name)
                    real_val = real_values.get(name)
                    if sim_val is None or real_val is None:
                        continue
                    try:
                        abs_err = abs(float(sim_val) - float(real_val))
                        abs_errors.append(abs_err)
                    except (ValueError, TypeError):
                        continue

                mae = sum(abs_errors) / len(abs_errors) if abs_errors else 0.0
                max_err = max(abs_errors) if abs_errors else 0.0
                entry = {
                    "timestamp": time.time(),
                    "mae": round(mae, 6),
                    "max_error": round(max_err, 6),
                    "point_count": len(abs_errors),
                    "overall_pass": max_err <= tolerance_pct,
                }
                monitor_state["history"].append(entry)
                if len(monitor_state["history"]) > 1000:
                    monitor_state["history"] = monitor_state["history"][-1000:]
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning("Drift monitor error for %s: %s", device_id, e)
                await asyncio.sleep(5)

    monitor_state["task"] = asyncio.create_task(_monitor_loop())
    _drift_monitors[device_id] = monitor_state
    logger.info("Drift monitor started for device %s (interval=%ds)", device_id, interval)
    return {"status": "started", "device_id": device_id, "interval": interval}


@router.post("/devices/{device_id}/drift-monitor/stop")
async def stop_drift_monitor(
    device_id: str,
    _user: dict[str, Any] = Depends(require_operator),
):
    """停止持续漂移监控。"""
    monitor = _drift_monitors.pop(device_id, None)
    if not monitor:
        raise HTTPException(status_code=404, detail="No drift monitor running for this device")
    monitor["running"] = False
    task = monitor.get("task")
    if task and not task.done():
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    return {"status": "stopped", "device_id": device_id}


@router.get("/devices/{device_id}/drift-monitor/history")
async def get_drift_history(
    device_id: str,
    limit: int = Query(100, ge=1, le=1000),
    _user: dict[str, Any] = Depends(require_viewer),
):
    """获取漂移监控历史记录。"""
    monitor = _drift_monitors.get(device_id)
    if not monitor:
        raise HTTPException(status_code=404, detail="No drift monitor for this device")
    history = monitor.get("history", [])
    return {
        "device_id": device_id,
        "running": monitor.get("running", False),
        "interval": monitor.get("interval", 0),
        "total_records": len(history),
        "history": history[-limit:],
    }


@router.get("/devices/{device_id}/compare/export")
async def export_comparison_report(
    device_id: str,
    format: str = Query("csv", pattern="^(csv|json)$"),
    _user: dict[str, Any] = Depends(require_viewer),
):
    """导出设备对比报告 (CSV 或 JSON)。"""
    engine = _get_engine()
    db = _get_database()

    instance = engine.get_device_instance(device_id)
    if not instance:
        raise HTTPException(status_code=404, detail=f"Device not found: {device_id}")

    snapshots = await db.load_device_snapshots(device_id)
    if not snapshots:
        raise HTTPException(status_code=404, detail="No snapshots found for device")

    snapshot = snapshots[0]
    real_values = snapshot.get("point_values", {})
    sim_points = instance.read_all_points()
    sim_map = {p.name: p.value for p in sim_points}

    rows = []
    for name in sorted(set(sim_map.keys()) | set(real_values.keys())):
        sim_val = sim_map.get(name)
        real_val = real_values.get(name)
        abs_err = None
        rel_err = None
        try:
            abs_err = round(abs(float(sim_val) - float(real_val)), 6)
            real_f = float(real_val)
            rel_err = round(abs_err / abs(real_f), 6) if abs(real_f) > 1e-10 else 0.0
        except (ValueError, TypeError):
            pass
        rows.append({
            "point_name": name,
            "simulated": sim_val,
            "real": real_val,
            "absolute_error": abs_err,
            "relative_error": rel_err,
        })

    if format == "csv":
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=["point_name", "simulated", "real", "absolute_error", "relative_error"])
        writer.writeheader()
        writer.writerows(rows)
        return StreamingResponse(
            io.BytesIO(output.getvalue().encode("utf-8")),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename=comparison_{device_id}.csv"},
        )
    else:
        return {
            "device_id": device_id,
            "snapshot_id": snapshot.get("id", ""),
            "timestamp": snapshot.get("timestamp", 0),
            "points": rows,
        }


# ─── P3: 从录制数据生成仿真配置 + 自动参数校准 ──────────────────────────────


def _analyze_timeseries(values: list[float]) -> dict[str, Any]:
    """分析时序数据特征，返回统计指标。

    :param values: 数值列表
    :return: 包含 mean, std, min, max, range, trend, is_periodic 等特征的字典
    """
    if not values:
        return {"mean": 0, "std": 0, "min": 0, "max": 0, "range": 0}

    n = len(values)
    mean = sum(values) / n
    variance = sum((v - mean) ** 2 for v in values) / n
    std = math.sqrt(variance)
    vmin = min(values)
    vmax = max(values)
    value_range = vmax - vmin

    # 趋势检测：线性回归斜率
    if n > 2:
        x_mean = (n - 1) / 2
        y_mean = mean
        numerator = sum((i - x_mean) * (v - y_mean) for i, v in enumerate(values))
        denominator = sum((i - x_mean) ** 2 for i in range(n))
        slope = numerator / denominator if denominator > 0 else 0
    else:
        slope = 0

    # 周期性检测：自相关
    is_periodic = False
    estimated_frequency = 0.1
    if n > 10 and std > 0:
        # 简化自相关：检查 lag=1 和 lag=n/4 的相关系数
        lag = max(1, n // 4)
        if lag < n:
            corr_sum = sum(
                (values[i] - mean) * (values[i + lag] - mean)
                for i in range(n - lag)
            )
            corr = corr_sum / (variance * n) if variance > 0 else 0
            is_periodic = corr > 0.5  # 自相关系数 > 0.5 表示有周期性
            if is_periodic and lag > 0:
                estimated_frequency = 1.0 / (lag * 2)  # 估计频率

    # 变化率分析
    diffs = [abs(values[i] - values[i - 1]) for i in range(1, n)] if n > 1 else [0]
    avg_diff = sum(diffs) / len(diffs) if diffs else 0

    return {
        "mean": round(mean, 6),
        "std": round(std, 6),
        "min": vmin,
        "max": vmax,
        "range": round(value_range, 6),
        "slope": round(slope, 8),
        "is_periodic": is_periodic,
        "estimated_frequency": round(estimated_frequency, 6),
        "avg_change_rate": round(avg_diff, 6),
        "cv": round(std / abs(mean), 6) if abs(mean) > 1e-10 else 0,  # 变异系数
    }


def _select_generator_type(analysis: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """根据时序数据特征选择最佳生成器类型和参数。

    :param analysis: _analyze_timeseries 返回的特征字典
    :return: (generator_type, generator_config)
    """
    std = analysis.get("std", 0)
    mean = analysis.get("mean", 0)
    slope = analysis.get("slope", 0)
    is_periodic = analysis.get("is_periodic", False)
    cv = analysis.get("cv", 0)
    value_range = analysis.get("range", 0)
    avg_change_rate = analysis.get("avg_change_rate", 0)
    freq = analysis.get("estimated_frequency", 0.1)

    # 决策逻辑：
    if abs(slope) > 0.001 and not is_periodic:
        # 有明显趋势 → INCREMENT
        step = abs(slope)
        gen_type = "increment"
        gen_config = {
            "step": round(step, 6),
            "min": analysis.get("min", 0),
            "max": analysis.get("max", 100),
            "frequency": 0.1,
        }
    elif is_periodic and std > 0.01:
        # 有周期性 → SINE
        amplitude = value_range / 2 if value_range > 0 else std
        gen_type = "sine"
        gen_config = {
            "amplitude": round(amplitude, 6),
            "offset": round(mean, 6),
            "frequency": freq,
            "phase": 0,
            "noise": round(std * 0.1, 6),  # 10% 标准差作为噪声
        }
    elif avg_change_rate > std * 0.5 and cv > 0.1:
        # 变化率大且变异系数高 → RANDOM_WALK
        gen_type = "random_walk"
        gen_config = {
            "step_size": round(avg_change_rate, 6),
            "min": analysis.get("min", 0),
            "max": analysis.get("max", 100),
            "noise": round(std * 0.1, 6),
        }
    elif std > 0.01:
        # 有一定波动 → RANDOM
        gen_type = "random"
        gen_config = {
            "min": round(mean - 2 * std, 6),
            "max": round(mean + 2 * std, 6),
            "noise": round(std * 0.1, 6),
        }
    else:
        # 基本稳定 → FIXED
        gen_type = "fixed"
        gen_config = {}

    return gen_type, gen_config


@router.post("/simulation/generate-config-from-recording")
async def generate_config_from_recording(
    body: dict[str, Any],
    _user: dict[str, Any] = Depends(require_operator),
):
    """从真实设备录制数据生成仿真配置。

    分析历史时序数据，自动选择最佳生成器类型和参数。

    请求体::\n

        {
            "device_id": "real_device_001",
            "start_time": 1234567890,
            "end_time": 1234657890,
            "protocol": "modbus_tcp",
            "device_name": "Simulated Pump",
            "sample_count": 1000
        }

    返回::\n

        {
            "device_config": {
                "id": "auto_generated_xxx",
                "name": "Simulated Pump",
                "protocol": "modbus_tcp",
                "points": [
                    {
                        "name": "temperature",
                        "data_type": "float32",
                        "generator_type": "sine",
                        "generator_config": {"amplitude": 5, "offset": 25, ...},
                        ...
                    }
                ]
            },
            "analysis": {
                "temperature": {"mean": 25, "std": 2, "is_periodic": true, ...},
                ...
            }
        }
    """
    db = _get_database()
    device_id = body.get("device_id", "")
    if not device_id:
        raise HTTPException(status_code=400, detail="device_id is required")

    start_time = body.get("start_time")
    end_time = body.get("end_time")
    if not start_time or not end_time:
        raise HTTPException(status_code=400, detail="start_time and end_time are required")

    protocol = body.get("protocol", "modbus_tcp")
    device_name = body.get("device_name", f"Auto-Generated from {device_id}")

    # 查询时序数据
    rows = await db.query_timeseries(
        device_id=device_id,
        start_time=start_time,
        end_time=end_time,
    )

    if not rows:
        raise HTTPException(status_code=404, detail="No timeseries data found for the given time range")

    # 按点位分组
    point_data: dict[str, list[float]] = {}
    for row in rows:
        point_name = row.get("point_name", "")
        value = row.get("value")
        if point_name and value is not None:
            try:
                point_data.setdefault(point_name, []).append(float(value))
            except (ValueError, TypeError):
                continue

    if not point_data:
        raise HTTPException(status_code=404, detail="No numeric data found in timeseries")

    # 为每个点位分析数据并生成配置
    points_config = []
    analysis_results = {}
    for point_name, values in point_data.items():
        analysis = _analyze_timeseries(values)
        gen_type, gen_config = _select_generator_type(analysis)
        analysis_results[point_name] = analysis

        # 推断数据类型
        if all(isinstance(v, bool) or v in (0, 1) for v in values):
            data_type = "bool"
        elif all(v == int(v) for v in values):
            if all(-32768 <= v <= 32767 for v in values):
                data_type = "int16"
            else:
                data_type = "int32"
        else:
            data_type = "float32"

        point_cfg = {
            "name": point_name,
            "data_type": data_type,
            "address": str(len(points_config) + 1),
            "generator_type": gen_type,
            "generator_config": gen_config,
            "min_value": analysis.get("min"),
            "max_value": analysis.get("max"),
            "access": "rw",
        }
        if gen_type == "fixed":
            point_cfg["fixed_value"] = analysis.get("mean", 0)

        points_config.append(point_cfg)

    generated_id = f"auto_{device_id}_{int(time.time())}"

    return {
        "device_config": {
            "id": generated_id,
            "name": device_name,
            "protocol": protocol,
            "points": points_config,
        },
        "analysis": analysis_results,
        "data_points_analyzed": sum(len(v) for v in point_data.values()),
        "point_count": len(points_config),
    }


@router.post("/devices/{device_id}/auto-calibrate")
async def auto_calibrate_device(
    device_id: str,
    body: dict[str, Any],
    _user: dict[str, Any] = Depends(require_operator),
):
    """自动校准设备生成器参数，使仿真值更接近真实设备数据。

    通过对比仿真值与真实快照数据，自动调整生成器参数（offset, amplitude, noise等）。

    请求体::\n

        {
            "snapshot_id": "uuid",           // 可选，不指定则用最新快照
            "max_iterations": 10,           // 最大迭代次数
            "tolerance_pct": 5.0,           // 目标容差
            "auto_apply": false             // 是否自动应用校准结果
        }
    """
    engine = _get_engine()
    db = _get_database()

    instance = engine.get_device_instance(device_id)
    if not instance:
        raise HTTPException(status_code=404, detail=f"Device not found: {device_id}")

    # 获取快照
    snapshot_id = body.get("snapshot_id")
    if snapshot_id:
        snapshot = await db.load_device_snapshot(snapshot_id)
        if not snapshot:
            raise HTTPException(status_code=404, detail="Snapshot not found")
    else:
        snapshots = await db.load_device_snapshots(device_id)
        if not snapshots:
            raise HTTPException(status_code=404, detail="No snapshots found for device")
        snapshot = snapshots[0]

    real_values = snapshot.get("point_values", {})
    max_iterations = int(body.get("max_iterations", 10))
    tolerance_pct = float(body.get("tolerance_pct", 5.0)) / 100.0
    auto_apply = bool(body.get("auto_apply", False))

    # 获取当前仿真值
    sim_points = instance.read_all_points()
    sim_map = {p.name: p.value for p in sim_points}

    calibration_results = []
    for name in sorted(set(sim_map.keys()) | set(real_values.keys())):
        sim_val = sim_map.get(name)
        real_val = real_values.get(name)
        if sim_val is None or real_val is None:
            calibration_results.append({
                "name": name,
                "simulated": sim_val,
                "real": real_val,
                "calibrated": False,
                "error": "Missing value",
            })
            continue

        try:
            sim_f = float(sim_val)
            real_f = float(real_val)
        except (ValueError, TypeError):
            calibration_results.append({
                "name": name,
                "simulated": sim_val,
                "real": real_val,
                "calibrated": False,
                "error": "Non-numeric value",
            })
            continue

        abs_err = abs(sim_f - real_f)
        rel_err = abs_err / abs(real_f) if abs(real_f) > 1e-10 else abs_err

        # 获取当前点位配置
        point_cfg = instance._point_configs.get(name)
        if not point_cfg:
            calibration_results.append({
                "name": name,
                "simulated": sim_f,
                "real": real_f,
                "absolute_error": round(abs_err, 6),
                "relative_error": round(rel_err, 6),
                "calibrated": False,
                "error": "Point config not found",
            })
            continue

        # 计算校准参数
        gen_type = str(point_cfg.generator_type) if hasattr(point_cfg, "generator_type") else "fixed"
        gen_config = dict(point_cfg.generator_config or {}) if hasattr(point_cfg, "generator_config") else {}

        # 根据生成器类型调整参数
        calibrated = False
        adjustments = {}

        if gen_type in ("sine", "triangle", "sawtooth", "square"):
            # 调整 offset 使均值接近真实值
            old_offset = gen_config.get("offset", 0)
            new_offset = real_f
            gen_config["offset"] = round(new_offset, 6)
            adjustments["offset"] = {"old": old_offset, "new": round(new_offset, 6)}
            calibrated = True

        elif gen_type in ("random", "random_walk"):
            # 调整 min/max 范围
            old_min = gen_config.get("min", point_cfg.min_value or 0)
            old_max = gen_config.get("max", point_cfg.max_value or 100)
            new_min = real_f - abs_err
            new_max = real_f + abs_err
            gen_config["min"] = round(new_min, 6)
            gen_config["max"] = round(new_max, 6)
            adjustments["min"] = {"old": old_min, "new": round(new_min, 6)}
            adjustments["max"] = {"old": old_max, "new": round(new_max, 6)}
            calibrated = True

        elif gen_type in ("fixed", "constant"):
            # 调整固定值
            adjustments["fixed_value"] = {"old": sim_f, "new": real_f}
            calibrated = True

        elif gen_type == "increment":
            # 调整 min/max
            old_min = gen_config.get("min", 0)
            old_max = gen_config.get("max", 100)
            new_min = real_f - (old_max - old_min) / 2
            new_max = real_f + (old_max - old_min) / 2
            gen_config["min"] = round(new_min, 6)
            gen_config["max"] = round(new_max, 6)
            adjustments["min"] = {"old": old_min, "new": round(new_min, 6)}
            adjustments["max"] = {"old": old_max, "new": round(new_max, 6)}
            calibrated = True

        # 计算校准后预期误差
        expected_error = abs_err * 0.1 if calibrated else abs_err  # 校准后预期减少90%误差

        calibration_results.append({
            "name": name,
            "simulated": sim_f,
            "real": real_f,
            "absolute_error": round(abs_err, 6),
            "relative_error": round(rel_err, 6),
            "calibrated": calibrated,
            "adjustments": adjustments,
            "expected_error_after": round(expected_error, 6),
            "generator_type": gen_type,
            "new_generator_config": gen_config if calibrated else None,
        })

        # 自动应用校准
        if auto_apply and calibrated:
            try:
                if hasattr(point_cfg, "generator_config"):
                    point_cfg.generator_config = gen_config
                if gen_type in ("fixed", "constant"):
                    if hasattr(point_cfg, "fixed_value"):
                        point_cfg.fixed_value = real_f
                if hasattr(point_cfg, "min_value"):
                    point_cfg.min_value = gen_config.get("min", point_cfg.min_value)
                if hasattr(point_cfg, "max_value"):
                    point_cfg.max_value = gen_config.get("max", point_cfg.max_value)
                instance._point_configs[name] = point_cfg
            except Exception as e:
                logger.warning("Failed to apply calibration for %s: %s", name, e)

    # 统计
    total = len(calibration_results)
    calibrated_count = sum(1 for r in calibration_results if r.get("calibrated"))
    within_tol = sum(1 for r in calibration_results if r.get("relative_error", 1) <= tolerance_pct)

    return {
        "device_id": device_id,
        "snapshot_id": snapshot.get("id", ""),
        "auto_applied": auto_apply,
        "summary": {
            "total_points": total,
            "calibrated": calibrated_count,
            "within_tolerance": within_tol,
            "out_of_tolerance": total - within_tol,
        },
        "results": calibration_results,
    }
