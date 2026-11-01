"""环境即代码（v1.10.0）：声明式 YAML 清单的 export / apply / diff。

清manifest 覆盖设备的完整声明：协议、协议配置、点位（名称/地址/类型/
生成器/单位/只读）。YAML 文件天然进 Git、可 review、可复现——

    protoforge env export  > env.yaml      # 从运行中的服务导出
    protoforge env apply   env.yaml        # 1 分钟重建整套环境
    protoforge env diff    env.yaml        # 当前环境 vs 清单

manifest 格式::

    api_version: protoforge.io/v1
    kind: Environment
    metadata:
      name: my-factory
    devices:
      - id: sensor-001
        name: 温度传感器
        protocol: modbus_tcp
        protocol_config: {host: 0.0.0.0, port: 5020, slave_id: 1}
        points:
          - {name: temp, address: HR0, data_type: float32,
             generator_type: sine, generator_config: {min: 20, max: 30}}
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

MANIFEST_API_VERSION = "protoforge.io/v1"
MANIFEST_KIND = "Environment"

# DeviceConfig → manifest 的字段白名单（按序输出，YAML 可 review）
_POINT_FIELDS = (
    "name", "address", "data_type", "unit", "description", "access",
    "generator_type", "generator_config", "gen_interval",
    "min_value", "max_value", "fixed_value",
)
_DEVICE_FIELDS = ("id", "name", "protocol", "protocol_config")


# ---------------------------------------------------------------------------
# export
# ---------------------------------------------------------------------------

def export_manifest(engine, name: str = "exported-env") -> dict[str, Any]:
    """从运行中的引擎导出 manifest（dict，调用方负责 YAML 序列化）。"""
    devices: list[dict[str, Any]] = []
    for device_id in engine.get_all_device_ids():
        instance = engine.get_device_instance(device_id)
        if instance is None:
            continue
        cfg = instance.config
        entry: dict[str, Any] = {}
        for f in _DEVICE_FIELDS:
            v = getattr(cfg, f, None)
            if v not in (None, "", {}):
                entry[f] = v
        points = []
        for p in cfg.points:
            pt = {}
            for f in _POINT_FIELDS:
                v = getattr(p, f, None)
                if v in (None, "", [], {}):
                    continue
                if f == "generator_type":
                    v = v.value if hasattr(v, "value") else v
                if f == "data_type":
                    v = v.value if hasattr(v, "value") else v
                pt[f] = v
            points.append(pt)
        entry["points"] = points
        devices.append(entry)

    return {
        "api_version": MANIFEST_API_VERSION,
        "kind": MANIFEST_KIND,
        "metadata": {"name": name, "device_count": len(devices)},
        "devices": devices,
    }


# ---------------------------------------------------------------------------
# diff
# ---------------------------------------------------------------------------

@dataclass
class DiffEntry:
    kind: str          # added / removed / changed
    device_id: str
    detail: str = ""
    fields: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "device_id": self.device_id,
                "detail": self.detail, "fields": self.fields}


def _point_key(p: Any) -> str:
    return str(p.get("name") if isinstance(p, dict) else p.name)


def _normalize_point(p: Any) -> dict[str, Any]:
    """点位统一为 dict 视图（兼容 manifest dict 与 PointConfig 对象）。"""
    if isinstance(p, dict):
        out = {f: p.get(f) for f in _POINT_FIELDS if p.get(f) not in (None, "", [], {})}
        gt = out.get("generator_type")
        out["generator_type"] = getattr(gt, "value", gt)
        dt = out.get("data_type")
        out["data_type"] = getattr(dt, "value", dt)
        return out
    out = {}
    for f in _POINT_FIELDS:
        v = getattr(p, f, None)
        if v in (None, "", [], {}):
            continue
        out[f] = getattr(v, "value", v)
    return out


def diff_manifest(engine, manifest: dict[str, Any]) -> list[DiffEntry]:
    """当前引擎状态 vs 清单：added（清单有引擎无）/ removed / changed。"""
    current: dict[str, dict[str, Any]] = {}
    for device_id in engine.get_all_device_ids():
        instance = engine.get_device_instance(device_id)
        if instance is None:
            continue
        cfg = instance.config
        current[device_id] = {
            "name": cfg.name,
            "protocol": cfg.protocol,
            "protocol_config": dict(cfg.protocol_config or {}),
            "points": [_normalize_point(p) for p in cfg.points],
        }

    wanted: dict[str, dict[str, Any]] = {}
    for d in manifest.get("devices", []):
        wanted[d.get("id", "")] = {
            "name": d.get("name", ""),
            "protocol": d.get("protocol", ""),
            "protocol_config": dict(d.get("protocol_config") or {}),
            "points": [_normalize_point(p) for p in d.get("points", [])],
        }

    entries: list[DiffEntry] = []
    for device_id, w in wanted.items():
        if device_id not in current:
            entries.append(DiffEntry("added", device_id, "清单中存在，引擎中缺失"))
            continue
        c = current[device_id]
        changed: list[str] = []
        if c["protocol"] != w["protocol"]:
            changed.append(f"protocol: {c['protocol']} → {w['protocol']}")
        if c["name"] != w["name"]:
            changed.append(f"name: {c['name']} → {w['name']}")
        if c["protocol_config"] != w["protocol_config"]:
            changed.append("protocol_config")
        c_pts = {_point_key(p): p for p in c["points"]}
        w_pts = {_point_key(p): p for p in w["points"]}
        for pn in w_pts:
            if pn not in c_pts:
                changed.append(f"point+{pn}")
        for pn in c_pts:
            if pn not in w_pts:
                changed.append(f"point-{pn}")
        for pn in w_pts:
            if pn in c_pts and c_pts[pn] != w_pts[pn]:
                diff_fields = [f for f in w_pts[pn] if c_pts[pn].get(f) != w_pts[pn].get(f)]
                changed.append(f"point~{pn}({','.join(diff_fields)})")
        if changed:
            entries.append(DiffEntry("changed", device_id, "; ".join(changed)))

    for device_id in current:
        if device_id not in wanted:
            entries.append(DiffEntry("removed", device_id, "引擎中存在，清单中缺失"))
    return entries


# ---------------------------------------------------------------------------
# apply
# ---------------------------------------------------------------------------

@dataclass
class ApplyReport:
    created: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    failed: list[dict[str, str]] = field(default_factory=list)
    dry_run: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "dry_run": self.dry_run,
            "created": self.created,
            "updated": self.updated,
            "failed": self.failed,
            "total": len(self.created) + len(self.updated) + len(self.failed),
        }


async def apply_manifest(engine, manifest: dict[str, Any], dry_run: bool = False,
                         start_devices: bool = True) -> ApplyReport:
    """把清单应用到引擎：逐设备 create_device + start_device。

    已存在的设备按清单重建（先停再删再建），保证协议/点位变更生效。
    单设备失败只记录到 report.failed，不中断其余设备（部分成功语义）。
    必须在事件循环内调用（API 协程/测试）。
    """
    from protoforge.models.device import DeviceConfig, PointConfig

    report = ApplyReport(dry_run=dry_run)
    for d in manifest.get("devices", []):
        device_id = str(d.get("id") or "")
        if not device_id or not d.get("protocol"):
            report.failed.append({"device_id": device_id, "error": "缺少 id 或 protocol"})
            continue
        try:
            points = [PointConfig(**_normalize_point(p)) for p in d.get("points", [])]
            new_cfg = DeviceConfig(
                id=device_id,
                name=d.get("name", device_id),
                protocol=d["protocol"],
                protocol_config=dict(d.get("protocol_config") or {}),
                points=points,
            )
            existed = engine.get_device_instance(device_id) is not None
            if existed:
                try:
                    await engine.stop_device(device_id)
                except Exception as e:
                    logger.debug("env apply: stop_device %s error: %s", device_id, e)
                await engine.remove_device(device_id)
            await engine.create_device(new_cfg)
            if start_devices:
                await engine.start_device(device_id)
            (report.updated if existed else report.created).append(device_id)
        except Exception as e:
            logger.warning("env apply: device %s failed: %s", device_id, e)
            report.failed.append({"device_id": device_id, "error": f"{type(e).__name__}: {e}"})
    return report
