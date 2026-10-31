"""主站模式基础框架（v1.9.0）。

主站（Master/Client）与既有协议服务器（Slave/Server 侧）方向相反：
**主动拨出**连接真实从站设备，按扫描周期轮询点位，把远端值写入本地
点位存储——于是：

- 主站设备出现在设备列表，点位显示真实设备的实时值；
- SCADA/上位机可通过 ProtoForge 自身的任意协议服务器读取这些值
  （协议转换/透传能力随之免费获得）；
- 测试引擎的既有断言体系可直接对主站设备点位做"读从站 → 断言 → 记录"，
  固件回归自动化无需新增测试步骤类型。

子类只需实现三个协议相关方法：

  - ``_connect(cfg)``                       建立并返回连接对象（失败抛异常）
  - ``_poll_once(conn, cfg, points)``       执行一轮轮询，返回 {点名: 值}
  - ``_write_remote(conn, device_id, cfg, point, v)``  写远端单点（可选）

基类负责：按设备的 scan_interval 驱动轮询任务、连接失败重连退避、
点位值与质量（good/bad）存储、轮询统计（成功/失败/最后错误）、优雅停止。
外部取消（wait_for 超时等）不吞——沿用 v1.8.1 的取消传播语义。
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from protoforge.models.device import DeviceConfig, PointValue
from protoforge.protocols.base import ProtocolServer, ProtocolStatus


class MasterBase(ProtocolServer):
    """主站轮询框架基类。子类协议名以 ``_master`` 结尾。"""

    _DEFAULT_SCAN_INTERVAL = 1.0
    _MIN_SCAN_INTERVAL = 0.1
    _MAX_SCAN_INTERVAL = 3600.0
    _DEFAULT_TIMEOUT = 3.0
    _RECONNECT_DELAY = 3.0

    def __init__(self):
        super().__init__()
        self._device_configs: dict[str, DeviceConfig] = {}
        self._poll_tasks: dict[str, asyncio.Task] = {}
        self._conns: dict[str, Any] = {}
        self._values: dict[str, dict[str, Any]] = {}
        self._quality: dict[str, dict[str, str]] = {}
        self._stats: dict[str, dict[str, Any]] = {}
        self._stopping = False

    # -- 子类实现 ---------------------------------------------------------

    async def _connect(self, cfg: dict[str, Any]) -> Any:
        """建立到远端从站的连接，返回连接对象。失败抛异常。"""
        raise NotImplementedError

    async def _close_conn(self, conn: Any) -> None:
        """关闭连接对象（子类按需覆写，默认无操作）。"""
        return None

    async def _poll_once(self, conn: Any, device_id: str,
                         cfg: dict[str, Any], points: list) -> dict[str, Any]:
        """执行一轮轮询，返回 {点名: 值}。子类必须实现。"""
        raise NotImplementedError

    async def _write_remote(self, conn: Any, device_id: str, cfg: dict[str, Any],
                            point_name: str, value: Any) -> bool:
        """写远端单点。子类按需实现，默认不支持。"""
        return False

    # -- 引擎接口 ---------------------------------------------------------

    async def start(self, config: dict[str, Any]) -> None:
        """主站不监听端口；start 仅置运行态（真正的拨出在 create_device）。"""
        self._status = ProtocolStatus.RUNNING
        self._stopping = False

    async def stop(self) -> None:
        self._stopping = True
        for device_id, task in list(self._poll_tasks.items()):
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        for device_id, conn in list(self._conns.items()):
            try:
                await self._close_conn(conn)
            except Exception:
                pass
        self._poll_tasks.clear()
        self._conns.clear()
        self._status = ProtocolStatus.STOPPED

    async def create_device(self, device_config: DeviceConfig) -> str:
        device_id = device_config.id
        self._device_configs[device_id] = device_config
        self._update_default_device(device_id)
        cfg = dict(device_config.protocol_config or {})
        if device_id not in self._values:
            self._values[device_id] = {}
            self._quality[device_id] = {}
            self._stats[device_id] = {
                "last_poll_ts": 0.0, "poll_ok": 0, "poll_err": 0,
                "last_error": "", "connected": False,
                "scan_interval": self._scan_interval_of(cfg),
            }
        if device_id not in self._poll_tasks or self._poll_tasks[device_id].done():
            self._poll_tasks[device_id] = asyncio.create_task(
                self._poll_loop(device_id, cfg),
                name=f"{self.protocol_name}-poll-{device_id}",
            )
        return device_id

    async def remove_device(self, device_id: str) -> None:
        task = self._poll_tasks.pop(device_id, None)
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        conn = self._conns.pop(device_id, None)
        if conn is not None:
            try:
                await self._close_conn(conn)
            except Exception:
                pass
        self._values.pop(device_id, None)
        self._quality.pop(device_id, None)
        self._stats.pop(device_id, None)
        self._device_configs.pop(device_id, None)
        self._clear_default_device(device_id)

    async def read_points(self, device_id: str) -> list[PointValue]:
        vals = self._values.get(device_id, {})
        qual = self._quality.get(device_id, {})
        cfg = self._device_configs.get(device_id)
        if not cfg:
            return []
        ts = self._stats.get(device_id, {}).get("last_poll_ts", 0.0)
        out: list[PointValue] = []
        for p in cfg.points:
            v = vals.get(p.name, p.fixed_value if p.fixed_value is not None else 0)
            out.append(PointValue(
                name=p.name, value=v,
                timestamp=ts,
                quality=qual.get(p.name, "good" if ts else "bad"),
                simulated=True,
            ))
        return out

    async def write_point(self, device_id: str, point_name: str, value: Any) -> bool:
        device_cfg = self._device_configs.get(device_id)
        if not device_cfg:
            return False
        conn = self._conns.get(device_id)
        if conn is None:
            return False
        point = next((p for p in device_cfg.points if p.name == point_name), None)
        if point is None:
            return False
        try:
            return await self._write_remote(
                conn, device_id, dict(device_cfg.protocol_config or {}), point_name, value)
        except Exception as e:
            self._stats[device_id]["last_error"] = f"write: {e}"
            return False

    def get_master_status(self, device_id: str) -> dict[str, Any]:
        """主站轮询状态（API/前端展示用）：连通性、轮询统计、最后错误。"""
        st = dict(self._stats.get(device_id, {}))
        st["connected"] = device_id in self._conns
        return st

    # -- 轮询循环 ---------------------------------------------------------

    def _scan_interval_of(self, cfg: dict[str, Any]) -> float:
        v = float(cfg.get("scan_interval", self._DEFAULT_SCAN_INTERVAL))
        return min(self._MAX_SCAN_INTERVAL, max(self._MIN_SCAN_INTERVAL, v))

    def _timeout_of(self, cfg: dict[str, Any]) -> float:
        return float(cfg.get("timeout", self._DEFAULT_TIMEOUT))

    async def _poll_loop(self, device_id: str, cfg: dict[str, Any]) -> None:
        scan = self._scan_interval_of(cfg)
        timeout = self._timeout_of(cfg)
        backoff = self._RECONNECT_DELAY
        points = self._device_configs.get(device_id)
        points = points.points if points else []
        while not self._stopping and device_id in self._device_configs:
            try:
                conn = self._conns.get(device_id)
                if conn is None:
                    conn = await asyncio.wait_for(self._connect(cfg), timeout=timeout)
                    self._conns[device_id] = conn
                    self._stats[device_id]["connected"] = True
                    self._log_debug("outbound", "master_connect",
                                    f"master connected to {cfg.get('host')}:{cfg.get('port', '')}",
                                    device_id=device_id)
                values = await asyncio.wait_for(
                    self._poll_once(conn, device_id, cfg, points),
                    timeout=timeout * 3,
                )
                for name, v in values.items():
                    self._values.setdefault(device_id, {})[name] = v
                    self._quality.setdefault(device_id, {})[name] = "good"
                st = self._stats[device_id]
                st["last_poll_ts"] = time.time()
                st["poll_ok"] = st.get("poll_ok", 0) + 1
                st["last_error"] = ""
                backoff = self._RECONNECT_DELAY
                await self._after_poll(device_id, values)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                st = self._stats.setdefault(device_id, {})
                st["poll_err"] = st.get("poll_err", 0) + 1
                # TimeoutError 的 str() 为空——补类型名保证 last_error 可读
                err_text = f"{type(e).__name__}: {e}" if not str(e) else str(e)
                st["last_error"] = err_text[:200]
                st["connected"] = False
                for p in points:
                    self._quality.setdefault(device_id, {})[p.name] = "bad"
                self._log_debug("system", "master_poll_error",
                                f"master poll error: {e}", device_id=device_id)
                conn = self._conns.pop(device_id, None)
                if conn is not None:
                    try:
                        await self._close_conn(conn)
                    except Exception:
                        pass
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60.0)
                continue
            await asyncio.sleep(scan)

    async def _after_poll(self, device_id: str, values: dict[str, Any]) -> None:
        """每轮成功后的钩子（如向引擎写回调传播）。默认无操作。"""
        return None
