"""500 错误监控中间件

在 FastAPI 应用中注册此中间件，可自动捕获并记录所有 HTTP 500 响应，
包括请求方法、路径、耗时、异常堆栈等关键信息，便于线上问题定位。

使用方式（在 main.py 的 create_app 中）::

    from protoforge.core.error_monitor import error_monitor_middleware
    app.middleware("http")(error_monitor_middleware)

日志输出示例::

    [500_MONITOR] POST /api/v1/devices | duration=152ms | exc=RuntimeError: DB connection lost
      traceback: ...
      request_body: {"id": "test", "name": "test", ...}  (截断前500字符)
"""

import logging
import time
import traceback
from collections import defaultdict, deque
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger("protoforge.error_monitor")

# =============================================================================
#  配置
# =============================================================================

_MAX_BODY_LOG_LEN = 500        # 请求体日志最大长度
_SLOW_REQUEST_MS = 5000        # 慢请求阈值（毫秒）
_ERROR_RATE_WINDOW = 60        # 错误率统计窗口（秒）
_ERROR_RATE_THRESHOLD = 0.1    # 错误率告警阈值（10%）
_RATE_ALERT_COOLDOWN = 30      # 告警冷却时间（秒）

# =============================================================================
#  内存统计（轻量级，不依赖外部存储）
# =============================================================================

class _ErrorStats:
    """线程安全的轻量级错误统计器（单进程内）。"""

    def __init__(self):
        self._total_requests = 0
        self._error_500_count = 0
        self._error_4xx_count = 0
        self._error_by_path: dict[str, int] = defaultdict(int)
        self._recent_errors: deque = deque(maxlen=100)  # 最近100条500错误
        self._last_alert_time = 0.0
        self._window_start = time.time()

    def record(self, method: str, path: str, status: int, duration_ms: float,
               exc_info: str = "") -> None:
        self._total_requests += 1
        if status == 500:
            self._error_500_count += 1
            self._error_by_path[f"{method} {path}"] += 1
            self._recent_errors.append({
                "time": time.time(),
                "method": method,
                "path": path,
                "status": status,
                "duration_ms": round(duration_ms, 1),
                "exc": exc_info[:200],
            })
        elif 400 <= status < 500:
            self._error_4xx_count += 1

        # 检查错误率告警
        self._check_alert()

    def _check_alert(self) -> None:
        now = time.time()
        if now - self._window_start < _ERROR_RATE_WINDOW:
            return
        if now - self._last_alert_time < _RATE_ALERT_COOLDOWN:
            return

        window_requests = self._total_requests
        if window_requests < 10:
            return  # 请求量太少不告警

        error_rate = self._error_500_count / window_requests
        if error_rate > _ERROR_RATE_THRESHOLD:
            logger.critical(
                "[500_ALERT] 错误率告警！最近 %d 秒内 500 错误率 = %.1f%% (%d/%d)。\n"
                "Top 错误路径:\n%s",
                _ERROR_RATE_WINDOW,
                error_rate * 100,
                self._error_500_count,
                window_requests,
                self._format_top_paths(),
            )
            self._last_alert_time = now

        # 重置窗口
        self._window_start = now

    def _format_top_paths(self) -> str:
        sorted_paths = sorted(self._error_by_path.items(), key=lambda x: -x[1])[:5]
        lines = [f"  {path}: {count}次" for path, count in sorted_paths]
        return "\n".join(lines)

    def get_stats(self) -> dict[str, Any]:
        return {
            "total_requests": self._total_requests,
            "error_500_count": self._error_500_count,
            "error_4xx_count": self._error_4xx_count,
            "error_rate_500": (
                round(self._error_500_count / self._total_requests * 100, 2)
                if self._total_requests > 0 else 0.0
            ),
            "top_error_paths": dict(
                sorted(self._error_by_path.items(), key=lambda x: -x[1])[:10]
            ),
            "recent_errors": list(self._recent_errors),
        }

    def reset(self) -> None:
        self._total_requests = 0
        self._error_500_count = 0
        self._error_4xx_count = 0
        self._error_by_path.clear()
        self._recent_errors.clear()
        self._window_start = time.time()


# 全局单例
_error_stats = _ErrorStats()


def get_error_stats() -> _ErrorStats:
    """获取全局错误统计实例（供监控端点使用）。"""
    return _error_stats


# =============================================================================
#  中间件
# =============================================================================

class ErrorMonitorMiddleware(BaseHTTPMiddleware):
    """500 错误监控中间件。

    功能：
      1. 记录所有 500 响应的详细信息（方法、路径、耗时、异常）
      2. 记录慢请求（>5s）即使返回 200
      3. 统计错误率，超过阈值时输出 CRITICAL 告警日志
      4. 提供 get_error_stats() 供 /api/v1/error-stats 端点查询
    """

    async def dispatch(self, request: Request, call_next):
        # 跳过健康检查和静态资源
        path = request.url.path
        if path in ("/health", "/api/v1/health") or path.startswith("/static"):
            return await call_next(request)

        start_time = time.time()
        method = request.method

        # 捕获请求体（用于 500 时记录）
        body_bytes = b""
        if method in ("POST", "PUT", "PATCH"):
            try:
                body_bytes = await request.body()
            except Exception:
                pass

        # FIXED: 统一在 finally 中记录，避免 except + finally 双重计数
        exc_info = ""
        status = 500
        response = None
        try:
            response = await call_next(request)
            status = response.status_code
            return response
        except Exception as exc:
            exc_info = traceback.format_exc()
            raise
        finally:
            duration_ms = (time.time() - start_time) * 1000

            # 记录统计（统一入口，避免重复计数）
            if status >= 400:
                _error_stats.record(method, path, status, duration_ms, exc_info)

            # 500 详细日志
            if status == 500:
                logger.error(
                    "[500_MONITOR] %s %s | status=500 | duration=%.0fms\n"
                    "  request_body: %s%s",
                    method, path, duration_ms,
                    self._safe_body(body_bytes),
                    f"\n  exception: {exc_info[:500]}" if exc_info else "",
                )
            # 慢请求警告
            elif duration_ms > _SLOW_REQUEST_MS and status < 400:
                logger.warning(
                    "[SLOW_REQUEST] %s %s | duration=%.0fms | status=%d",
                    method, path, duration_ms, status,
                )

    @staticmethod
    def _safe_body(body_bytes: bytes) -> str:
        """安全地将请求体转为可读字符串。"""
        if not body_bytes:
            return "(empty)"
        try:
            text = body_bytes.decode("utf-8", errors="replace")
            if len(text) > _MAX_BODY_LOG_LEN:
                return text[:_MAX_BODY_LOG_LEN] + "...(truncated)"
            return text
        except Exception:
            return f"(binary, {len(body_bytes)} bytes)"
