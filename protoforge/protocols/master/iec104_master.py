"""IEC 60870-5-104 主站（v1.9.0）— 拨出连接真实调度/从站 RTU。

客户端链路（与 ProtoForge 自身 IEC104 从站及标准主站语义一致）：

  1. TCP 连接（默认 2404）
  2. U-格式 STARTDT_ACT(0x07) → STARTDT_CON(0x0B)
  3. 每个扫描周期发送总召 C_IC_NA_1（TI=100, COT=6, QOI=20），
     逐帧收集监视方向数据直到 ACTTERM(COT=10)：
       M_SP_NA(1) 遥信 → bool
       M_DP_NA(3) 双点遥信 → int
       M_ME_NA(9) 归一化遥测 → raw（/32767 归一）
       M_ME_NB(11) 标度化遥测 → int16
       M_ME_NC(13) 短浮点遥测 → float32
  4. 遥控 C_SC_NA_1(45)/遥调 C_SE_NC_1(50) 直接执行（S/E=0），
     等待 ACTCON + ACTTERM 双确认

帧格式：APDU = 0x68 + len(1) + 控制域(4) [+ ASDU]；
I-格式控制域 = pack("<HH", vs<<1, vr<<1)（小端）；
ASDU 头 = TI(1)+VSQ(1)+COT(1)+OA(1)+CA(2 小端)；IOA 固定 3 字节小端。
TESTFR_ACT(0x43) 到达时回 TESTFR_CON(0x83)，收到 S-格式跳过。
"""

from __future__ import annotations

import asyncio
import struct
from typing import Any

from protoforge.models.device import PointConfig
from protoforge.protocols.master.base import MasterBase

# U-格式 / 链路常量（与 server.py 保持一致）
U_STARTDT_ACT = 0x07
U_STARTDT_CON = 0x0B
U_TESTFR_ACT = 0x43
U_TESTFR_CON = 0x83

TI_SINGLE_POINT = 1
TI_DOUBLE_POINT = 3
TI_MEASURED_NORM = 9
TI_MEASURED_SCALED = 11
TI_MEASURED_FLOAT = 13
TI_SINGLE_CMD = 45
TI_SETPOINT_FLOAT = 50
TI_INTERROGATION = 100

COT_ACTCONFIRM = 7
COT_ACTTERM = 10


class _IEC104Conn:
    """104 主站连接：I-格式序号维护 + APDU 收发。"""

    __slots__ = ("reader", "writer", "vs", "vr", "timeout", "ca")

    def __init__(self, reader: asyncio.StreamReader,
                 writer: asyncio.StreamWriter, timeout: float, ca: int):
        self.reader = reader
        self.writer = writer
        self.vs = 0
        self.vr = 0
        self.timeout = timeout
        self.ca = ca

    async def send_i(self, asdu: bytes) -> None:
        control = struct.pack("<HH", self.vs << 1, self.vr << 1)
        self.vs = (self.vs + 1) & 0x7FFF
        self.writer.write(bytes([0x68, 4 + len(asdu)]) + control + asdu)
        await self.writer.drain()

    async def send_u(self, c1: int) -> None:
        self.writer.write(bytes([0x68, 4, c1, 0, 0, 0]))
        await self.writer.drain()

    async def recv_apdu(self) -> bytes:
        head = await asyncio.wait_for(self.reader.readexactly(2), timeout=self.timeout)
        if head[0] != 0x68:
            raise IOError(f"104 APDU 起始字节错误: {head.hex(' ')}")
        return await asyncio.wait_for(
            self.reader.readexactly(head[1]), timeout=self.timeout)

    async def recv_i(self) -> bytes:
        """收下一个 I-帧的 ASDU；期间应答 TESTFR_ACT、跳过 S/U 帧。"""
        while True:
            apdu = await self.recv_apdu()
            if apdu[0] & 0x01 == 0:  # I-格式
                self.vr = (self.vr + 1) & 0x7FFF
                return apdu[4:]
            if apdu[0] & 0x03 == 0x03:  # U-格式
                if apdu[0] == U_TESTFR_ACT:
                    await self.send_u(U_TESTFR_CON)
                continue
            # S-格式：跳过


def _parse_asdu(asdu: bytes) -> tuple[int, int, int, int, int, int]:
    """解析 ASDU 固定头，返回 (ti, num, cot, oa, ca, obj_offset)。"""
    ti = asdu[0]
    num = asdu[1] & 0x7F
    cot = asdu[2] & 0x3F
    ca = struct.unpack("<H", asdu[4:6])[0]
    return ti, num, cot, asdu[3], ca, 6


class IEC104MasterServer(MasterBase):
    """IEC 104 主站：STARTDT + 周期总召 + 遥控/遥调。"""

    protocol_name = "iec104_master"
    protocol_display_name = "IEC 104 Master"
    protocol_description = "主动连接真实 IEC 60870-5-104 从站，总召遥测遥信并支持遥控遥调"
    protocol_version = "1.0.0"

    def get_config_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "host": {"type": "string", "default": "192.168.1.100",
                         "description": "从站/RTU IP 地址"},
                "port": {"type": "integer", "default": 2404,
                         "description": "IEC 104 TCP 端口"},
                "common_address": {"type": "integer", "default": 1,
                                   "description": "ASDU 公共地址 CA"},
            },
        }

    # -- 连接 ------------------------------------------------------------

    async def _connect(self, cfg: dict[str, Any]) -> Any:
        host = cfg.get("host")
        if not host:
            raise ValueError("iec104_master 需要 protocol_config.host")
        port = int(cfg.get("port", 2404))
        timeout = self._timeout_of(cfg)
        ca = int(cfg.get("common_address", 1))
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(str(host), port), timeout=timeout)
        conn = _IEC104Conn(reader, writer, timeout, ca)
        try:
            await conn.send_u(U_STARTDT_ACT)
            deadline = asyncio.get_event_loop().time() + timeout
            while True:
                apdu = await asyncio.wait_for(
                    conn.recv_apdu(), timeout=max(0.1, deadline - asyncio.get_event_loop().time()))
                if apdu[0] & 0x03 == 0x03:
                    if apdu[0] == U_STARTDT_ACT:
                        await conn.send_u(U_TESTFR_CON)
                    if apdu[0] == U_STARTDT_CON:
                        break
                    continue
                if apdu[0] & 0x01 == 0:
                    conn.vr = (conn.vr + 1) & 0x7FFF
        except Exception:
            writer.close()
            raise
        return conn

    async def _close_conn(self, conn: Any) -> None:
        try:
            conn.writer.close()
            await asyncio.wait_for(conn.writer.wait_closed(), timeout=2)
        except Exception:
            pass

    # -- 轮询 ------------------------------------------------------------

    async def _poll_once(self, conn: Any, device_id: str,
                         cfg: dict[str, Any], points: list) -> dict[str, Any]:
        values: dict[str, Any] = {}
        # 总召：C_IC_NA_1 ACT（QOI=20）
        gi = bytearray([TI_INTERROGATION, 0x01, 6, 0]) + struct.pack("<H", conn.ca)
        gi += bytes([0x00, 0x00, 0x00, 0x14])  # IOA=0 + QOI=20
        await conn.send_i(bytes(gi))

        timeout = conn.timeout * 3
        while True:
            asdu = await asyncio.wait_for(conn.recv_i(), timeout=timeout)
            ti, num, cot, _oa, _ca, offset = _parse_asdu(asdu)
            if ti == TI_INTERROGATION and cot in (COT_ACTCONFIRM, COT_ACTTERM):
                if cot == COT_ACTTERM:
                    break
                continue
            if ti in (TI_SINGLE_POINT, TI_DOUBLE_POINT, TI_MEASURED_NORM,
                      TI_MEASURED_SCALED, TI_MEASURED_FLOAT):
                for _ in range(num):
                    if offset + 3 > len(asdu):
                        break
                    ioa = asdu[offset] | asdu[offset + 1] << 8 | asdu[offset + 2] << 16
                    offset += 3
                    payload = asdu[offset:offset + 5]
                    values.update(self._decode_monitor(ioa, ti, payload, points))
                    obj_size = {TI_SINGLE_POINT: 1, TI_DOUBLE_POINT: 1,
                                TI_MEASURED_NORM: 3, TI_MEASURED_SCALED: 3,
                                TI_MEASURED_FLOAT: 5}.get(ti, 1)
                    offset += obj_size
        return values

    def _decode_monitor(self, ioa: int, ti: int, payload: bytes,
                        points: list) -> dict[str, Any]:
        """IOA → 点位映射 + 值解码（仅采集设备配置里登记过的 IOA）。"""
        pt = next((p for p in points
                   if p.address.lstrip() == str(ioa)), None)
        if pt is None:
            return {}
        if ti == TI_SINGLE_POINT:
            return {pt.name: bool(payload[0] & 0x01)}
        if ti == TI_DOUBLE_POINT:
            return {pt.name: int(payload[0] & 0x03)}
        if ti == TI_MEASURED_NORM:
            raw = struct.unpack("<h", payload[0:2])[0]
            return {pt.name: raw / 32767.0}
        if ti == TI_MEASURED_SCALED:
            return {pt.name: struct.unpack("<h", payload[0:2])[0]}
        if ti == TI_MEASURED_FLOAT:
            return {pt.name: struct.unpack("<f", payload[0:4])[0]}
        return {}

    # -- 写远端（遥控/遥调） ----------------------------------------------

    async def _write_remote(self, conn: Any, device_id: str, cfg: dict[str, Any],
                            point_name: str, value: Any) -> bool:
        device_cfg = self._device_configs.get(device_id)
        if device_cfg is None:
            return False
        pt = next((p for p in device_cfg.points if p.name == point_name), None)
        if pt is None:
            return False
        ioa = int(str(pt.address).strip())
        if pt.data_type.value == "bool":
            ti, payload = TI_SINGLE_CMD, bytes([0x01 if value else 0x00])
        elif pt.data_type.value in ("float32", "float64"):
            ti, payload = TI_SETPOINT_FLOAT, struct.pack("<f", float(value)) + b"\x00"
        else:
            # 标度化遥调 C_SE_NB_1（TI=49，3 字节: 值2 + QOS1）
            ti = 49
            payload = struct.pack("<h", int(value)) + b"\x00"
        asdu = bytearray([ti, 0x01, 6, 0]) + struct.pack("<H", conn.ca)
        asdu += bytes([ioa & 0xFF, (ioa >> 8) & 0xFF, (ioa >> 16) & 0xFF]) + payload
        await conn.send_i(bytes(asdu))

        # 等待 ACTCON + ACTTERM 双确认（期间吸收监视帧）
        acked, terminated = False, False
        deadline = asyncio.get_event_loop().time() + conn.timeout * 3
        while not (acked and terminated):
            remain = deadline - asyncio.get_event_loop().time()
            if remain <= 0:
                raise TimeoutError(f"104 命令确认超时 IOA={ioa} acked={acked} term={terminated}")
            asdu_in = await asyncio.wait_for(conn.recv_i(), timeout=remain)
            ti_in, _num, cot_in, _oa, ca_in, _off = _parse_asdu(asdu_in)
            if ti_in == ti and ca_in == conn.ca and cot_in == COT_ACTCONFIRM:
                acked = True
            elif ti_in == ti and cot_in == COT_ACTTERM:
                terminated = True
        return True
