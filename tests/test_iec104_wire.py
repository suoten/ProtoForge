"""IEC 60870-5-104 wire-level regression tests against a spec-compliant mini master.

Root cause regression: the server used to encode COT as 2 bytes (standard: 1 byte),
shifting every following field by +1 byte for compliant masters — CA displayed as
256x, IOA shifted left 8 bits (x256), float values garbled (user report via QTester104).

The mini master in this file parses/encodes strictly per IEC 60870-5-104:
  ASDU header: TI(1) + VSQ(1) + COT(1) + OA(1) + CA(2 LE)
  information object: IOA(3 LE, full 8-bit groups) + payload
"""

import asyncio
import struct

import pytest

from protoforge.models.device import DeviceConfig, PointConfig
from protoforge.protocols.iec104.server import IEC104Server

HOST = "127.0.0.1"
PORT = 11804
CA = 1


# ---------------------------------------------------------------------------
# mini master: strict 104 wire helpers
# ---------------------------------------------------------------------------

class MiniMaster:
    def __init__(self, reader, writer):
        self.reader = reader
        self.writer = writer
        self.vs = 0
        self.vr = 0

    async def send_i(self, asdu: bytes) -> None:
        control = struct.pack("<HH", self.vs << 1, self.vr << 1)
        self.vs += 1
        self.writer.write(bytes([0x68, 4 + len(asdu)]) + control + asdu)
        await self.writer.drain()

    async def send_u(self, c1: int) -> None:
        self.writer.write(bytes([0x68, 4, c1, 0, 0, 0]))
        await self.writer.drain()

    async def startdt(self) -> None:
        await self.send_u(0x07)
        c1 = (await self._apdu())[0]
        assert c1 == 0x0B, f"expected STARTDT con, got {c1:#x}"

    async def _apdu(self) -> bytes:
        head = await asyncio.wait_for(self.reader.readexactly(2), timeout=5)
        assert head[0] == 0x68
        return await asyncio.wait_for(self.reader.readexactly(head[1]), timeout=5)

    async def recv_i(self) -> bytes:
        """Return the ASDU payload of the next I-frame APDU (skipping S/U frames)."""
        while True:
            apdu = await self._apdu()
            if apdu[0] & 0x01 == 0:
                return apdu[4:]
            # S-format（确认帧）或 U-format（链路保活）——跳过继续等 I 帧

    @staticmethod
    def parse_asdu_header(asdu: bytes):
        """Strict parse: returns (ti, vsq, cot, oa, ca) — COT must be 1 byte."""
        ti, vsq = asdu[0], asdu[1]
        cot = asdu[2] & 0x3F
        oa = asdu[3]
        ca = struct.unpack("<H", asdu[4:6])[0]
        return ti, vsq, cot, oa, ca


def build_cmd_asdu(ti: int, ioa: int, payload: bytes, ca: int = CA, cot: int = 6) -> bytes:
    asdu = bytearray([ti, 1, cot, 0]) + struct.pack("<H", ca)
    asdu += bytes([ioa & 0xFF, (ioa >> 8) & 0xFF, (ioa >> 16) & 0xFF]) + payload
    return bytes(asdu)


def build_device() -> DeviceConfig:
    return DeviceConfig(
        id="dev-104",
        name="IEC104 Test",
        protocol="iec104",
        points=[
            PointConfig(name="bus_voltage", address="1", data_type="float32"),
            PointConfig(name="feeder_current", address="2", data_type="float32"),
            PointConfig(name="breaker_1_status", address="3", data_type="bool"),
        ],
    )


async def start_server(server: IEC104Server):
    await server.create_device(build_device())
    await server.start({"host": HOST, "port": PORT, "common_address": CA, "scan_interval": 0.2})
    await asyncio.sleep(0.15)
    return server


async def stop_server(server: IEC104Server):
    await server.stop()


# ---------------------------------------------------------------------------
# tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_monitor_frame_layout_strict():
    """M_ME_NC_1 frame must parse per spec: CA=1, IOA=2, float intact (no +1 shift)."""
    server = await start_server(IEC104Server())
    try:
        await server.sync_point_value("dev-104", "feeder_current", 19.787)
        reader, writer = await asyncio.open_connection(HOST, PORT)
        master = MiniMaster(reader, writer)
        await master.startdt()

        await server.sync_point_value("dev-104", "feeder_current", 19.787)
        # 周期上送按点位顺序发送，找到 feeder_current（IOA=2）那一帧
        for _ in range(10):
            asdu = await master.recv_i()
            ioa = asdu[6] | asdu[7] << 8 | asdu[8] << 16
            if ioa == 2:
                break
        else:
            pytest.fail("feeder_current frame not received")
        ti, vsq, cot, oa, ca = MiniMaster.parse_asdu_header(asdu)
        assert ti == 13  # M_ME_NC_1
        assert ca == CA, f"CA must be {CA}, got {ca} (x256 shift regression)"
        assert oa == 0
        assert cot == 1  # cyclic
        # APDU 长度检查：4 control + 6 header + 3 IOA + 5 payload = 18 = 0x12
        assert ioa == 2, f"IOA must be 2, got {ioa} (x256 shift regression)"
        value = struct.unpack("<f", asdu[9:13])[0]
        assert abs(value - 19.787) < 0.01, f"float garbled: {value}"
        writer.close()
    finally:
        await stop_server(server)


@pytest.mark.asyncio
async def test_apdu_length_matches_standard():
    """APDU length byte must equal 4 + 6 + obj — catches 2-byte COT regressions."""
    server = await start_server(IEC104Server())
    try:
        reader, writer = await asyncio.open_connection(HOST, PORT)
        master = MiniMaster(reader, writer)
        await master.startdt()
        await server.sync_point_value("dev-104", "breaker_1_status", True)
        # 找到 M_SP_NA_1（TI 1）那一帧
        for _ in range(10):
            asdu = await master.recv_i()
            if asdu[0] == 1:
                break
        else:
            pytest.fail("M_SP_NA_1 frame not received")
        ti, _vsq, _cot, _oa, ca = MiniMaster.parse_asdu_header(asdu)
        assert ti == 1 and ca == CA
        # M_SP_NA_1 ASDU: 6 header + 3 IOA + 1 payload = 10（APDU = 14 = 0x0E，标准报文长度）
        assert len(asdu) == 10
        writer.close()
    finally:
        await stop_server(server)


@pytest.mark.asyncio
async def test_general_interrogation_flow():
    """C_IC_NA_1 ACT -> CON(QOI echoed) -> per-point COT=20 -> ACTTERM."""
    server = await start_server(IEC104Server())
    try:
        reader, writer = await asyncio.open_connection(HOST, PORT)
        master = MiniMaster(reader, writer)
        await master.startdt()
        await master.send_i(build_cmd_asdu(100, 0, b"\x14"))  # QOI=20

        con = await master.recv_i()
        ti, _vsq, cot, _oa, ca = MiniMaster.parse_asdu_header(con)
        assert (ti, cot, ca) == (100, 7, CA)
        assert con[9] == 20  # QOI right after header(6)+IOA(3)

        got = {}
        for _ in range(3):
            d = await master.recv_i()
            dti, _v, dcot, _o, dca = MiniMaster.parse_asdu_header(d)
            assert dcot == 20 and dca == CA
            ioa = d[6] | d[7] << 8 | d[8] << 16
            got[ioa] = dti
        assert got == {1: 13, 2: 13, 3: 1}

        term = await master.recv_i()
        assert MiniMaster.parse_asdu_header(term)[:3] == (100, 1, 10)
        writer.close()
    finally:
        await stop_server(server)


@pytest.mark.asyncio
async def test_direct_command_c_sc_na_1():
    """C_SC_NA_1 (TI 45) direct operate: point updated, CON + ACTTERM echoed."""
    server = await start_server(IEC104Server())
    try:
        reader, writer = await asyncio.open_connection(HOST, PORT)
        master = MiniMaster(reader, writer)
        await master.startdt()
        await master.send_i(build_cmd_asdu(45, 3, b"\x01"))  # SCO=01 on

        con = await master.recv_i()
        assert MiniMaster.parse_asdu_header(con)[:3] == (45, 1, 7)
        term = await master.recv_i()
        assert MiniMaster.parse_asdu_header(term)[:3] == (45, 1, 10)

        vals = {pv.name: pv.value for pv in await server.read_points("dev-104")}
        assert vals["breaker_1_status"] in (True, 1)
        writer.close()
    finally:
        await stop_server(server)


@pytest.mark.asyncio
async def test_time_tagged_command_c_sc_ta_1():
    """C_SC_TA_1 (TI 58, QTester104 default command type) must operate the point."""
    server = await start_server(IEC104Server())
    try:
        reader, writer = await asyncio.open_connection(HOST, PORT)
        master = MiniMaster(reader, writer)
        await master.startdt()
        payload = b"\x01" + b"\x00" * 7  # SCO=01 + CP56Time2a placeholder
        await master.send_i(build_cmd_asdu(58, 3, payload))

        con = await master.recv_i()
        assert MiniMaster.parse_asdu_header(con)[:3] == (58, 1, 7)
        assert con[-8:] == payload  # ack echoes the full object incl. time tag
        term = await master.recv_i()
        assert MiniMaster.parse_asdu_header(term)[:3] == (58, 1, 10)

        vals = {pv.name: pv.value for pv in await server.read_points("dev-104")}
        assert vals["breaker_1_status"] in (True, 1)
        writer.close()
    finally:
        await stop_server(server)


@pytest.mark.asyncio
async def test_select_before_operate():
    """S/E bit select must not apply the value; execute must."""
    server = await start_server(IEC104Server())
    try:
        reader, writer = await asyncio.open_connection(HOST, PORT)
        master = MiniMaster(reader, writer)
        await master.startdt()
        await master.send_i(build_cmd_asdu(45, 3, b"\x81"))  # SCO=01 + S/E bit
        con = await master.recv_i()
        assert MiniMaster.parse_asdu_header(con)[:3] == (45, 1, 7)
        vals = {pv.name: pv.value for pv in await server.read_points("dev-104")}
        assert not vals["breaker_1_status"]

        await master.send_i(build_cmd_asdu(45, 3, b"\x01"))  # execute
        await master.recv_i()  # con
        await master.recv_i()  # term
        vals = {pv.name: pv.value for pv in await server.read_points("dev-104")}
        assert vals["breaker_1_status"] in (True, 1)
        writer.close()
    finally:
        await stop_server(server)


@pytest.mark.asyncio
async def test_ioa_full_24bit():
    """IOA third octet must use all 8 bits (was masked to 0x0F)."""
    from protoforge.protocols.iec104.server import IEC104Server as S
    assert S._encode_ioa(0x0F0102) == bytes([0x02, 0x01, 0x0F])
    assert S._decode_ioa(bytes([0x02, 0x01, 0xF0])) == 0xF00102
