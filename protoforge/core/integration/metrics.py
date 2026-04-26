import logging
import time
from typing import Any

logger = logging.getLogger(__name__)


class IntegrationMetrics:
    def __init__(self):
        self.connection_status: str = "disconnected"
        self.connected_since: float = 0.0
        self.last_heartbeat_at: float = 0.0
        self.push_success_count: int = 0
        self.push_failure_count: int = 0
        self.sync_event_count: int = 0
        self.data_backhaul_count: int = 0
        self.alarm_forward_count: int = 0
        self._push_latencies: list[float] = []
        self._max_latencies: int = 100

    def record_push_success(self, latency_ms: float = 0.0) -> None:
        self.push_success_count += 1
        if latency_ms > 0:
            self._push_latencies.append(latency_ms)
            if len(self._push_latencies) > self._max_latencies:
                self._push_latencies = self._push_latencies[-self._max_latencies:]

    def record_push_failure(self) -> None:
        self.push_failure_count += 1

    def record_sync_event(self) -> None:
        self.sync_event_count += 1

    def record_data_backhaul(self) -> None:
        self.data_backhaul_count += 1

    def record_alarm_forward(self) -> None:
        self.alarm_forward_count += 1

    def set_connected(self) -> None:
        self.connection_status = "connected"
        self.connected_since = time.time()

    def set_disconnected(self) -> None:
        self.connection_status = "disconnected"
        self.connected_since = 0.0

    def update_heartbeat(self) -> None:
        self.last_heartbeat_at = time.time()

    @property
    def avg_push_latency_ms(self) -> float:
        if not self._push_latencies:
            return 0.0
        return sum(self._push_latencies) / len(self._push_latencies)

    def to_dict(self) -> dict[str, Any]:
        return {
            "connection_status": self.connection_status,
            "connected_since": self.connected_since,
            "last_heartbeat_at": self.last_heartbeat_at,
            "push_success_count": self.push_success_count,
            "push_failure_count": self.push_failure_count,
            "sync_event_count": self.sync_event_count,
            "data_backhaul_count": self.data_backhaul_count,
            "alarm_forward_count": self.alarm_forward_count,
            "avg_push_latency_ms": round(self.avg_push_latency_ms, 2),
        }
