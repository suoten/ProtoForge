"""Modbus 主站（v1.9.0）— 主动拨出轮询真实从站。

支持三种链路（``protocol_config.mode``）：

  - ``tcp``           Modbus TCP（FramerSocket，默认端口 502）
  - ``rtu_over_tcp``  RTU over TCP（FramerSocket 链路上的 FramerRTU，串口服务器场景）
  - ``rtu``           串口 RTU（``serial_port``=COM3//dev/ttyUSB0，FramerRTU）

点位地址复用从站实现 ``parse_modbus_address`` 的全部记法
（HR100 / IR100 / C100 / DI100 / 4x / 3x / 0x / 1x / 40001…6 位 PLC 记法）。
多寄存器数据类型（float32/int32/…）按 ModbusDataStore 相同的**大端序**
拼装，保证主站读到的值与 ProtoForge 自身从站回环一致。

轮询按"同区连续地址"合并为批量读取（保持寄存器/输入寄存器单次 ≤125，
线圈/离散量单次 ≤1968），一个扫描周期内尽量少发请求。
"""

from __future__ import annotations

import asyncio
import logging
import struct
from typing import Any

from protoforge.models.device import DeviceConfig, PointConfig
from protoforge.protocols.master.base import MasterBase
from protoforge.protocols.modbus._common import parse_modbus_address, point_area, point_reg_count

logger = logging.getLogger(__name__)

_MAX_READ_REGS = 125       # FC03/FC04 单次上限（规范 0x7D）
_MAX_READ_BITS = 1968      # FC01/FC02 单次上限（规范 0x7D0）

_AREA_TO_FC = {"holding": 3, "input": 4, "coil": 1, "discrete": 2}


class ModbusMasterServer(MasterBase):
    """Modbus TCP/RTU 主站：拨出连接真实从站并按扫描周期轮询。"""

    protocol_name = "modbus_master"
    protocol_display_name = "Modbus Master (TCP/RTU)"
    protocol_description = "主动连接真实 Modbus 从站（TCP/RTU），轮询点位并支持写远端寄存器"
    protocol_version = "1.0.0"

    def get_config_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "mode": {"type": "string", "default": "tcp",
                         "enum": ["tcp", "rtu_over_tcp", "rtu"],
                         "description": "链路模式：tcp / rtu_over_tcp / rtu(串口)"},
                "host": {"type": "string", "default": "192.168.1.100",
                         "description": "真实从站 IP"},
                "port": {"type": "integer", "default": 502,
                         "description": "从站 TCP 端口"},
                "serial_port": {"type": "string", "default": "",
                                "description": "rtu 模式串口（COM3 / /dev/ttyUSB0）"},
                "baudrate": {"type": "integer", "default": 9600,
                             "description": "rtu 模式波特率"},
            },
        }

    # -- 连接 ------------------------------------------------------------

    async def _connect(self, cfg: dict[str, Any]) -> Any:
        from pymodbus.client import AsyncModbusSerialClient, AsyncModbusTcpClient
        from pymodbus.framer import FramerType

        mode = str(cfg.get("mode", "tcp")).lower()
        timeout = self._timeout_of(cfg)
        if mode == "rtu":
            serial_port = cfg.get("serial_port")
            if not serial_port:
                raise ValueError("modbus_master rtu 模式需要 protocol_config.serial_port")
            client = AsyncModbusSerialClient(
                str(serial_port), framer=FramerType.RTU,
                baudrate=int(cfg.get("baudrate", 9600)),
                timeout=timeout, retries=1,
            )
        else:
            host = cfg.get("host")
            if not host:
                raise ValueError("modbus_master 需要 protocol_config.host")
            framer = FramerType.RTU if mode == "rtu_over_tcp" else FramerType.SOCKET
            client = AsyncModbusTcpClient(
                str(host), framer=framer,
                port=int(cfg.get("port", 502)),
                timeout=timeout, retries=1,
            )
        if not await client.connect():
            raise ConnectionError(f"Modbus 主站连接失败 {cfg.get('host') or cfg.get('serial_port')}")
        return client

    async def _close_conn(self, conn: Any) -> None:
        try:
            conn.close()
            # FIXED: 让 pymodbus 内部的 reconnect 任务处理取消，避免事件循环
            # 关闭时残留 "Task was destroyed but it is pending"
            await asyncio.sleep(0)
        except Exception as e:
            logger.debug("%s close conn error: %s", tag, e)

    # -- 轮询 ------------------------------------------------------------

    async def _poll_once(self, conn: Any, device_id: str,
                         cfg: dict[str, Any], points: list) -> dict[str, Any]:
        slave = int(cfg.get("slave_id", cfg.get("unit_id", 1)))
        values: dict[str, Any] = {}
        for batch in self._plan_reads(points):
            raw = await self._read_batch(conn, slave, batch)
            for pt, offset in batch.points:
                count = point_reg_count(pt)
                chunk = raw[offset:offset + count]
                values[pt.name] = _decode(pt, chunk)
        return values

    def _plan_reads(self, points: list[PointConfig]) -> list["_ReadBatch"]:
        """同区连续地址合并为一次读取（按起始地址排序后贪心成段）。"""
        entries: list[tuple[str, int, PointConfig]] = []
        for pt in points:
            try:
                area = point_area(pt)
                addr = parse_modbus_address(pt.address)[0]
            except ValueError:
                continue  # 地址不合法的点位本轮跳过（质量标记由基类处理）
            entries.append((area, addr, pt))
        entries.sort(key=lambda e: (e[0], e[1]))

        batches: list[_ReadBatch] = []
        for area, addr, pt in entries:
            count = point_reg_count(pt)
            limit = _MAX_READ_BITS if area in ("coil", "discrete") else _MAX_READ_REGS
            placed = False
            if batches:
                last = batches[-1]
                # 与上一段同区且紧邻 → 尝试并入（含总长上限）
                gap = addr - (last.start + last.count)
                if last.area == area and 0 <= gap and last.count + gap + count <= limit:
                    if gap:
                        last.gap_points.append((gap, last.start + last.count))
                    last.count += gap + count
                    last.points.append((pt, last.count - count))
                    placed = True
            if not placed:
                batches.append(_ReadBatch(area=area, fc=_AREA_TO_FC[area],
                                          start=addr, count=count, points=[(pt, 0)]))
        return batches

    async def _read_batch(self, conn: Any, slave: int, batch: "_ReadBatch") -> list[int]:
        fc = batch.fc
        if fc == 1:
            rr = await conn.read_coils(batch.start, count=batch.count, device_id=slave)
        elif fc == 2:
            rr = await conn.read_discrete_inputs(batch.start, count=batch.count, device_id=slave)
        elif fc == 3:
            rr = await conn.read_holding_registers(batch.start, count=batch.count, device_id=slave)
        else:
            rr = await conn.read_input_registers(batch.start, count=batch.count, device_id=slave)
        if rr is None or rr.isError():
            raise IOError(f"Modbus 读取失败 FC={fc} addr={batch.start} count={batch.count}: {rr}")
        if fc in (1, 2):
            bits = rr.bits[:batch.count] if hasattr(rr, "bits") else []
            return [int(b) for b in bits] + [0] * (batch.count - len(bits))
        regs = list(rr.registers or [])
        if len(regs) < batch.count:
            regs += [0] * (batch.count - len(regs))
        return regs

    # -- 写远端 ----------------------------------------------------------

    async def _write_remote(self, conn: Any, device_id: str, cfg: dict[str, Any],
                            point_name: str, value: Any) -> bool:
        device_cfg = self._device_configs.get(device_id)
        if device_cfg is None:
            return False
        pt = next((p for p in device_cfg.points if p.name == point_name), None)
        if pt is None:
            return False
        slave = int(cfg.get("slave_id", cfg.get("unit_id", 1)))
        addr = parse_modbus_address(pt.address)[0]
        area = point_area(pt)
        dt = pt.data_type.value

        if dt == "bool":
            if area == "coil":
                rr = await conn.write_coil(addr, bool(value), device_id=slave)
            else:  # bool 落在寄存器区（auto 规则下不该发生，兼容处理）
                rr = await conn.write_register(addr, int(bool(value)), device_id=slave)
        elif dt in ("int16", "uint16"):
            rr = await conn.write_register(addr, int(value) & 0xFFFF, device_id=slave)
        else:
            raw = _encode(pt, value)
            rr = await conn.write_registers(addr, raw, device_id=slave)
        return not (rr is None or rr.isError())


class _ReadBatch:
    """一次批量读取计划：同区一段连续地址 + 段内各点位偏移。"""

    __slots__ = ("area", "fc", "start", "count", "points", "gap_points")

    def __init__(self, area: str, fc: int, start: int, count: int,
                 points: list[tuple[PointConfig, int]]):
        self.area = area
        self.fc = fc
        self.start = start
        self.count = count
        self.points = points
        self.gap_points: list[tuple[int, int]] = []  # (gap, 填充起点)


# ---------------------------------------------------------------------------
#  寄存器编解码（大端序，与 ModbusDataStore.set_32bit_point 一致）
# ---------------------------------------------------------------------------

def _decode(pt: PointConfig, regs: list[int]) -> Any:
    dt = pt.data_type.value
    if dt == "bool":
        return bool(regs[0])
    if dt == "int16":
        return struct.unpack(">h", struct.pack(">H", regs[0] & 0xFFFF))[0]
    if dt == "uint16":
        return regs[0] & 0xFFFF
    if dt == "float32":
        return _unpack(">f", regs, 2)
    if dt == "int32":
        return _unpack(">i", regs, 2)
    if dt == "uint32":
        return _unpack(">I", regs, 2)
    if dt == "float64":
        return _unpack(">d", regs, 4)
    if dt == "string":
        raw = b"".join(struct.pack(">H", r & 0xFFFF) for r in regs)
        return raw.split(b"\x00")[0].decode("utf-8", errors="replace")
    return regs[0]


def _encode(pt: PointConfig, value: Any) -> list[int]:
    dt = pt.data_type.value
    if dt == "float32":
        return list(struct.unpack(">2H", struct.pack(">f", float(value))))
    if dt == "int32":
        return list(struct.unpack(">2H", struct.pack(">i", int(value))))
    if dt == "uint32":
        return list(struct.unpack(">2H", struct.pack(">I", int(value) & 0xFFFFFFFF)))
    if dt == "float64":
        return list(struct.unpack(">4H", struct.pack(">d", float(value))))
    if dt == "string":
        raw = str(value).encode("utf-8")[:64]
        raw += b"\x00" * (64 - len(raw))
        return list(struct.unpack(">32H", raw))
    return [int(value) & 0xFFFF]


def _unpack(fmt: str, regs: list[int], nregs: int) -> Any:
    data = b"".join(struct.pack(">H", r & 0xFFFF) for r in regs[:nregs])
    return struct.unpack(fmt, data)[0]
