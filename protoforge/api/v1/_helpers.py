"""Shared helper utilities for API v1 route handlers."""

import logging
from typing import Any

logger = logging.getLogger(__name__)


def _get_engine():
    from protoforge.engine.registry import get_engine
    return get_engine()


def _get_template_manager():
    from protoforge.engine.registry import get_template_manager
    return get_template_manager()


def _get_log_bus():
    from protoforge.engine.registry import get_log_bus
    return get_log_bus()


def _get_database():
    from protoforge.engine.registry import get_database
    return get_database()


async def _trigger_webhook_safe(event: str, payload: dict[str, Any]) -> None:
    try:
        from protoforge.integrations.webhook import webhook_manager
        await webhook_manager.trigger(event, payload)
    except Exception as e:
        logger.warning("Webhook trigger failed for event '%s': %s", event, e)


def ensure_no_point_overlap(protocol: str, points: Any) -> None:
    """校验设备/模板点位在 Modbus 存储区上是否地址重叠，重叠则抛 ValueError。

    覆盖所有设备创建/更新入口（创建、quick-create、批量、克隆、CSV 导入、更新）
    及模板保存入口。重叠会导致固定值失效、读出乱值等几乎无法排查的问题，
    必须在保存时拦截并给出明确的冲突明细。

    :param protocol: 协议名（仅 modbus_tcp / modbus_rtu 需要校验）
    :param points: 点位配置列表（PointConfig 或等价 dict 均可）
    :raises ValueError: 存在地址重叠时，消息为可读的冲突明细
    """
    if not protocol or not str(protocol).startswith("modbus"):
        return
    if not points:
        return
    from protoforge.models.device import PointConfig
    from protoforge.protocols.modbus._common import find_overlapping_points

    # 兼容 dict 形式的点位（模板 update 等场景）
    normalized: list[Any] = []
    for pt in points:
        if isinstance(pt, dict):
            try:
                normalized.append(PointConfig(**{k: v for k, v in pt.items()
                                                 if k in PointConfig.model_fields}))
            except Exception:
                continue
        else:
            normalized.append(pt)

    conflicts = find_overlapping_points(normalized)
    if conflicts:
        raise ValueError("检测到同设备点位地址重叠（多字节类型占多个寄存器，重叠会互相覆盖数据）: "
                         + "；".join(conflicts))
