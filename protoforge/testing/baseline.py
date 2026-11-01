"""数据基线与回归对比（v1.10.0）。

基线快照 = 指定设备点位的当前值 + 容差声明，存 JSON 文件（可进 Git）：
    data/baselines/<name>.json

对比报告逐点判定：|actual - baseline| ≤ tolerance（数值）/ 相等（bool/str），
产出可作回归结论附件的明细（通过率、超差点清单、绝对偏差）。
全部入口为 async（需在事件循环内调用：API 协程/pytest-asyncio）。
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def baselines_dir() -> Path:
    from protoforge.core.paths import app_root
    d = app_root() / "data" / "baselines"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---------------------------------------------------------------------------
# 持久化
# ---------------------------------------------------------------------------

def save_baseline(name: str, snapshot: dict[str, Any]) -> Path:
    path = baselines_dir() / f"{_safe_name(name)}.json"
    path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_baseline(name: str) -> dict[str, Any]:
    path = baselines_dir() / f"{_safe_name(name)}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def list_baselines() -> list[dict[str, Any]]:
    out = []
    for p in sorted(baselines_dir().glob("*.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            out.append({
                "name": p.stem,
                "captured_at": data.get("captured_at", 0),
                "device_count": len(data.get("devices", [])),
            })
        except Exception as e:
            logger.debug("skip malformed baseline %s: %s", p.name, e)
    return out


def delete_baseline(name: str) -> bool:
    path = baselines_dir() / f"{_safe_name(name)}.json"
    if path.exists():
        path.unlink()
        return True
    return False


# ---------------------------------------------------------------------------
# 快照
# ---------------------------------------------------------------------------

async def capture_baseline_async(engine, device_ids: list[str],
                                 default_tolerance: float = 0.0,
                                 tolerances: dict[str, float] | None = None) -> dict[str, Any]:
    """抓取当前点位值作为基线快照（dict，调用方负责持久化）。

    tolerances: {点定位: 容差}，键支持 ``device/point`` 或 ``point``；
    ``point`` 形式作用于全部同名点位；未命中用 default_tolerance。
    """
    tolerances = tolerances or {}
    devices_out: list[dict[str, Any]] = []
    for device_id in device_ids:
        instance = engine.get_device_instance(device_id)
        if instance is None:
            continue
        points_out: list[dict[str, Any]] = []
        try:
            pvs = await engine.read_device_points(device_id)
        except Exception as e:
            logger.debug("baseline read points %s failed: %s", device_id, e)
            pvs = []
        for pv in pvs:
            tol = tolerances.get(f"{device_id}/{pv.name}",
                                 tolerances.get(pv.name, default_tolerance))
            points_out.append({
                "point": pv.name,
                "value": _jsonable(pv.value),
                "tolerance": float(tol),
            })
        devices_out.append({
            "device_id": device_id,
            "protocol": instance.config.protocol,
            "points": points_out,
        })
    return {
        "api_version": "protoforge.io/v1",
        "kind": "Baseline",
        "captured_at": time.time(),
        "default_tolerance": float(default_tolerance),
        "devices": devices_out,
    }


# ---------------------------------------------------------------------------
# 对比
# ---------------------------------------------------------------------------

@dataclass
class PointDiff:
    device_id: str
    point: str
    baseline: Any
    actual: Any
    delta: float | None      # 数值型绝对偏差；非数值为 None
    tolerance: float
    ok: bool
    reason: str = ""         # missing / type_mismatch / out_of_tolerance

    def to_dict(self) -> dict[str, Any]:
        return {
            "device_id": self.device_id, "point": self.point,
            "baseline": self.baseline, "actual": self.actual,
            "delta": self.delta, "tolerance": self.tolerance,
            "ok": self.ok, "reason": self.reason,
        }


@dataclass
class CompareReport:
    baseline_name: str
    entries: list[PointDiff] = field(default_factory=list)
    compared_at: float = field(default_factory=time.time)

    @property
    def total(self) -> int:
        return len(self.entries)

    @property
    def passed(self) -> int:
        return sum(1 for e in self.entries if e.ok)

    @property
    def violations(self) -> list[PointDiff]:
        return [e for e in self.entries if not e.ok]

    @property
    def pass_rate(self) -> float:
        return round(self.passed / self.total, 4) if self.total else 1.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "baseline_name": self.baseline_name,
            "compared_at": self.compared_at,
            "total": self.total,
            "passed": self.passed,
            "failed": self.total - self.passed,
            "pass_rate": self.pass_rate,
            "ok": len(self.violations) == 0,
            "violations": [v.to_dict() for v in self.violations],
            "entries": [e.to_dict() for e in self.entries],
        }


async def compare_baseline_async(engine, name: str,
                                 baseline: dict[str, Any] | None = None) -> CompareReport:
    """当前引擎值 vs 基线：逐点判定容差，产出回归结论报告。"""
    snapshot = baseline if baseline is not None else load_baseline(name)
    report = CompareReport(baseline_name=name)

    actual_map: dict[tuple[str, str], Any] = {}
    for device_id in {d["device_id"] for d in snapshot.get("devices", [])}:
        try:
            pvs = await engine.read_device_points(device_id)
        except Exception as e:
            logger.debug("baseline compare read %s failed: %s", device_id, e)
            pvs = []
        for pv in pvs:
            actual_map[(device_id, pv.name)] = pv.value

    for dev in snapshot.get("devices", []):
        device_id = dev["device_id"]
        for bp in dev.get("points", []):
            point = bp["point"]
            base_v = bp.get("value")
            tol = float(bp.get("tolerance", 0.0))
            key = (device_id, point)
            if key not in actual_map:
                report.entries.append(PointDiff(
                    device_id, point, base_v, None, None, tol, False, "missing"))
                continue
            act_v = actual_map[key]
            delta = _numeric_delta(base_v, act_v)
            if delta is None:
                same = base_v == act_v
                report.entries.append(PointDiff(
                    device_id, point, base_v, act_v, None, tol, same,
                    "" if same else "type_mismatch"))
            else:
                ok = delta <= tol + 1e-9
                report.entries.append(PointDiff(
                    device_id, point, base_v, act_v, round(delta, 6), tol, ok,
                    "" if ok else "out_of_tolerance"))
    return report


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _numeric_delta(base_v: Any, act_v: Any) -> float | None:
    try:
        b, a = float(base_v), float(act_v)
    except (TypeError, ValueError):
        return None
    # bool 与数值混比视为类型不匹配（True==1 会让基线失真）
    if isinstance(base_v, bool) or isinstance(act_v, bool):
        return None
    return abs(a - b)


def _jsonable(v: Any) -> Any:
    if isinstance(v, (int, float, str, bool)) or v is None:
        return v
    try:
        return float(v)
    except (TypeError, ValueError):
        return str(v)


def _safe_name(name: str) -> str:
    cleaned = "".join(ch for ch in name if ch.isalnum() or ch in "-_.")
    return cleaned or "baseline"
