"""最小 cron 表达式匹配（v1.10.0 定时测试）。

支持标准 5 字段：分 时 日 月 周；``*``、``*/n``、``a-b``、``a,b,c``。
不实现 @daily 等宏（配置里写标准 5 字段）。解析失败抛 ValueError，
让配置错误在保存时暴露而非静默不触发。
"""

from __future__ import annotations

import time
from datetime import datetime


def parse_cron_field(field: str, low: int, high: int) -> set[int]:
    field = field.strip()
    if not field:
        raise ValueError("empty cron field")
    values: set[int] = set()
    for part in field.split(","):
        part = part.strip()
        if "/" in part:
            base, step_s = part.split("/", 1)
            step = int(step_s)
            if step <= 0:
                raise ValueError(f"cron step must be positive: {part}")
        else:
            base, step = part, 1
        if base == "*" or base == "":
            start, end = low, high
        elif "-" in base:
            a, b = base.split("-", 1)
            start, end = int(a), int(b)
        else:
            start = end = int(base)
        if start < low or end > high or start > end:
            raise ValueError(f"cron field out of range [{low},{high}]: {part}")
        values.update(range(start, end + 1, step))
    return values


def parse_cron(expr: str) -> list[set[int]]:
    """解析 5 字段 cron → [分钟, 小时, 日, 月, 周] 的允许值集合。"""
    fields = expr.split()
    if len(fields) != 5:
        raise ValueError(f"cron expression must have 5 fields: {expr!r}")
    return [
        parse_cron_field(fields[0], 0, 59),
        parse_cron_field(fields[1], 0, 23),
        parse_cron_field(fields[2], 1, 31),
        parse_cron_field(fields[3], 1, 12),
        parse_cron_field(fields[4], 0, 6),
    ]


def cron_matches(expr: str, dt: datetime | None = None) -> bool:
    """给定时刻是否命中 cron（dt 缺省取当前本地时间）。"""
    sets = parse_cron(expr)
    dt = dt or datetime.now()
    return (dt.minute in sets[0] and dt.hour in sets[1] and dt.day in sets[2]
            and dt.month in sets[3] and dt.isoweekday() % 7 in sets[4])


def is_due(expr: str, last_run: float, now: float | None = None) -> bool:
    """调度判断：上次运行之后的每个整分钟命中点只触发一次。

    检查 (last_run, now] 区间内的整分钟是否有命中——停机补跑最多回看
    1440 分钟（1 天），避免长期停机后的触发风暴。
    """
    now = now if now is not None else time.time()
    try:
        sets = parse_cron(expr)
    except ValueError:
        return False
    start = int(last_run // 60) + 1 if last_run > 0 else int(now // 60)
    end = int(now // 60)
    if end - start > 1440:
        start = end - 1
    for minute_ts in range(start, end + 1):
        dt = datetime.fromtimestamp(minute_ts * 60)
        if (dt.minute in sets[0] and dt.hour in sets[1] and dt.day in sets[2]
                and dt.month in sets[3] and dt.isoweekday() % 7 in sets[4]):
            return True
    return False
