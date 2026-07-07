"""网络特性仿真模块。

模拟工业网络通信中的延迟、抖动、丢包和带宽限制等特性，
使协议服务器的响应更接近真实工业网络环境。

支持按协议类型配置不同的网络特性参数，也可以全局配置。

典型用法::

    from protoforge.core.network_sim import NetworkSimulator

    sim = NetworkSimulator(
        latency_ms=5.0,
        jitter_ms=1.0,
        packet_loss_rate=0.001,
    )
    # 在发送响应前
    await sim.delay()  # 模拟网络延迟
    if sim.should_drop():
        return  # 模拟丢包，不响应
"""

from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class NetworkProfile:
    """网络特性配置。

    :param latency_ms: 平均延迟 (ms)
    :param jitter_ms: 延迟抖动 (ms)，实际延迟 = latency ± jitter
    :param packet_loss_rate: 丢包率 (0-1)，如 0.001 表示 0.1%
    :param bandwidth_kbps: 带宽限制 (kbps)，0 表示不限
    :param connection_drop_rate: 连接断开率 (0-1)，每次连接检查时评估
    :param max_connections: 最大并发连接数，0 表示不限
    """

    latency_ms: float = 0.0
    jitter_ms: float = 0.0
    packet_loss_rate: float = 0.0
    bandwidth_kbps: float = 0.0
    connection_drop_rate: float = 0.0
    max_connections: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "latency_ms": self.latency_ms,
            "jitter_ms": self.jitter_ms,
            "packet_loss_rate": self.packet_loss_rate,
            "bandwidth_kbps": self.bandwidth_kbps,
            "connection_drop_rate": self.connection_drop_rate,
            "max_connections": self.max_connections,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> NetworkProfile:
        return cls(
            latency_ms=float(data.get("latency_ms", 0.0)),
            jitter_ms=float(data.get("jitter_ms", 0.0)),
            packet_loss_rate=float(data.get("packet_loss_rate", 0.0)),
            bandwidth_kbps=float(data.get("bandwidth_kbps", 0.0)),
            connection_drop_rate=float(data.get("connection_drop_rate", 0.0)),
            max_connections=int(data.get("max_connections", 0)),
        )


# 预定义的网络环境配置
PRESET_PROFILES: dict[str, NetworkProfile] = {
    "ideal": NetworkProfile(latency_ms=0, jitter_ms=0, packet_loss_rate=0),
    "lan": NetworkProfile(latency_ms=1.0, jitter_ms=0.5, packet_loss_rate=0.0001),
    "wan": NetworkProfile(latency_ms=20.0, jitter_ms=5.0, packet_loss_rate=0.001),
    "wireless": NetworkProfile(latency_ms=50.0, jitter_ms=15.0, packet_loss_rate=0.005),
    "satellite": NetworkProfile(latency_ms=300.0, jitter_ms=50.0, packet_loss_rate=0.01),
    "degraded": NetworkProfile(latency_ms=100.0, jitter_ms=30.0, packet_loss_rate=0.02, connection_drop_rate=0.001),
}


class NetworkSimulator:
    """网络特性仿真器。

    提供延迟模拟、丢包模拟和连接断开模拟。

    :param profile: 网络特性配置
    :param enabled: 是否启用网络仿真
    """

    def __init__(
        self,
        profile: NetworkProfile | None = None,
        enabled: bool = False,
    ):
        self._profile = profile or NetworkProfile()
        self._enabled = enabled
        self._current_connections: int = 0
        self._stats: dict[str, Any] = {
            "total_requests": 0,
            "dropped_packets": 0,
            "dropped_connections": 0,
            "total_delay_ms": 0.0,
        }

    @property
    def enabled(self) -> bool:
        return self._enabled

    def enable(self) -> None:
        self._enabled = True

    def disable(self) -> None:
        self._enabled = False

    def set_profile(self, profile: NetworkProfile | str) -> None:
        """设置网络特性配置。

        :param profile: NetworkProfile 实例或预定义名称 ("ideal"/"lan"/"wan"/...)
        """
        if isinstance(profile, str):
            profile = PRESET_PROFILES.get(profile, NetworkProfile())
        self._profile = profile

    @property
    def profile(self) -> NetworkProfile:
        return self._profile

    async def delay(self) -> None:
        """模拟网络延迟（异步）。

        根据 latency_ms 和 jitter_ms 计算延迟时间并等待。
        """
        if not self._enabled or self._profile.latency_ms <= 0:
            return

        latency = self._profile.latency_ms
        if self._profile.jitter_ms > 0:
            latency += random.gauss(0, self._profile.jitter_ms)
        latency = max(0, latency)

        self._stats["total_delay_ms"] += latency
        self._stats["total_requests"] += 1

        await asyncio.sleep(latency / 1000.0)

    def should_drop(self) -> bool:
        """检查当前请求是否应被丢弃（模拟丢包）。

        :return: True 表示应丢弃
        """
        if not self._enabled or self._profile.packet_loss_rate <= 0:
            return False
        drop = random.random() < self._profile.packet_loss_rate
        if drop:
            self._stats["dropped_packets"] += 1
        return drop

    def should_drop_connection(self) -> bool:
        """检查连接是否应被断开。

        :return: True 表示应断开连接
        """
        if not self._enabled or self._profile.connection_drop_rate <= 0:
            return False
        drop = random.random() < self._profile.connection_drop_rate
        if drop:
            self._stats["dropped_connections"] += 1
        return drop

    def can_accept_connection(self) -> bool:
        """检查是否可以接受新连接。

        :return: True 表示可以接受
        """
        if not self._enabled or self._profile.max_connections <= 0:
            return True
        return self._current_connections < self._profile.max_connections

    def on_connect(self) -> None:
        """记录新连接。"""
        self._current_connections += 1

    def on_disconnect(self) -> None:
        """记录连接断开。"""
        self._current_connections = max(0, self._current_connections - 1)

    def get_stats(self) -> dict[str, Any]:
        """返回网络仿真统计信息。"""
        stats = dict(self._stats)
        stats["current_connections"] = self._current_connections
        stats["avg_delay_ms"] = (
            stats["total_delay_ms"] / stats["total_requests"]
            if stats["total_requests"] > 0
            else 0.0
        )
        stats["enabled"] = self._enabled
        stats["profile"] = self._profile.to_dict()
        return stats

    def reset_stats(self) -> None:
        """重置统计信息。"""
        self._stats = {
            "total_requests": 0,
            "dropped_packets": 0,
            "dropped_connections": 0,
            "total_delay_ms": 0.0,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self._enabled,
            "profile": self._profile.to_dict(),
            "stats": self.get_stats(),
        }
