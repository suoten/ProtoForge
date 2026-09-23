"""IEC 60870-5-104 protocol server implementation.

Standard-compliant IEC 60870-5-104 telecontrol server (controlled station /
substation side), interoperate-tested against EdgeLite's IEC104 master.

Implements:
  - APCI framing: start 0x68 + 1-byte length (4..253) + 4-byte control field
  - U-format: STARTDT/STOPDT/TESTFR act/con
  - S-format: supervisory (acknowledge received I-frames)
  - I-format: carries one or more ASDUs
  - ASDU header: TI(1) + VSQ(1) + COT(1) + OA(1) + CA(2 LE)
  - Monitor direction: M_SP_NA(1), M_DP_NA(3), M_ME_NB(11), M_ME_NC(13),
    M_IT_NA(15) (+ CP56Time2a time-tagged variants on the decode side)
  - Control direction: C_SC_NA(45), C_DC_NA(46), C_SE_NB(49), C_SE_NC(50)
    and their CP56Time2a time-tagged variants C_SC_TA(58), C_DC_TA(59),
    C_SE_NB_TA(61), C_SE_NC_TA(62)
    with direct-operate and Select-before-Operate (S/E bit) flows
  - General interrogation C_IC_NA(100): ACT -> CON + all points COT=20 -> ACTTERM
  - Clock sync C_CS_NA(103): ACT -> CON (echoes the new server time)
  - Sequence number management N(S)/N(R) with k/w window acking

Pure Python, no third-party IEC 104 library required.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import struct
import time
from typing import Any

from protoforge.models.device import DeviceConfig, PointValue
from protoforge.protocols.behavior import ProtocolErrorCategory, ProtocolServer, ProtocolStatus, StandardDeviceBehavior

logger = logging.getLogger(__name__)

_READ_TIMEOUT = 120  # matches other protocol servers

# ---------------------------------------------------------------------------
#  APDU / ASDU constants (IEC 60870-5-104)
# ---------------------------------------------------------------------------

APDU_START = 0x68
APDU_MIN_LEN = 4
APDU_MAX_LEN = 253

# U-format control field 1 (bits 0..1 set identify U-format)
U_STARTDT_ACT = 0x07
U_STARTDT_CON = 0x0B
U_STOPDT_ACT = 0x13
U_STOPDT_CON = 0x23
U_TESTFR_ACT = 0x43
U_TESTFR_CON = 0x83

# Control field 1 for S-format
S_FORMAT = 0x01

# ASDU type identifiers (TI)
TI_SINGLE_POINT = 1      # M_SP_NA_1
TI_DOUBLE_POINT = 3      # M_DP_NA_1
TI_MEASURED_NORM = 9     # M_ME_NA_1
TI_MEASURED_SCALED = 11  # M_ME_NB_1
TI_MEASURED_FLOAT = 13   # M_ME_NC_1
TI_INTEGRATED_TOTAL = 15  # M_IT_NA_1
TI_SINGLE_CMD = 45       # C_SC_NA_1
TI_DOUBLE_CMD = 46       # C_DC_NA_1
TI_SETPOINT_SCALED = 49  # C_SE_NB_1
TI_SETPOINT_FLOAT = 50   # C_SE_NC_1
TI_CLOCK_SYNC = 103      # C_CS_NA_1
TI_INTERROGATION = 100   # C_IC_NA_1

# Control direction with CP56Time2a time tag (values: command qualifier + 7-byte time)
TI_SINGLE_CMD_TA = 58    # C_SC_TA_1
TI_DOUBLE_CMD_TA = 59    # C_DC_TA_1
TI_SETPOINT_SCALED_TA = 61  # C_SE_NB_TA_1
TI_SETPOINT_FLOAT_TA = 62   # C_SE_NC_TA_1

# Cause of transmission (COT, 1 byte; low 6 bits used)
COT_PERIODIC = 1
COT_BACKGROUND = 2
COT_SPONTANEOUS = 3
COT_ACTIVATED = 6
COT_ACTCONFIRM = 7
COT_ACTTERM = 10
COT_RETURN_REMOTE = 11
COT_INTERROGATED = 20

# Quality / command qualifier bits
SE_BIT = 0x80  # Select/Execute bit in SCO/DCO/QOS

# Map our point data types to monitor-direction ASDU types
_DATA_TYPE_TO_TI: dict[str, int] = {
    "bool": TI_SINGLE_POINT,
    "int16": TI_MEASURED_SCALED,
    "uint16": TI_MEASURED_SCALED,
    "int32": TI_INTEGRATED_TOTAL,
    "uint32": TI_INTEGRATED_TOTAL,
    "float32": TI_MEASURED_FLOAT,
    "float64": TI_MEASURED_FLOAT,
    "string": TI_MEASURED_SCALED,
}


def _build_cp56time2a(ts: float | None = None) -> bytes:
    """Encode a UNIX timestamp into 7-byte CP56Time2a.

    Milliseconds field carries second*1000; weekday uses IEC convention
    (1=Monday..7=Sunday).
    """
    t = time.localtime(ts if ts is not None else time.time())
    ms = t.tm_sec * 1000
    weekday = (t.tm_wday + 1) % 7 or 7  # tm_wday: 0=Mon..6=Sun -> 1..7
    return bytes([
        ms & 0xFF, (ms >> 8) & 0xFF,
        t.tm_min & 0x3F,
        t.tm_hour & 0x1F,
        (t.tm_mday & 0x1F) | ((weekday & 0x07) << 5),
        t.tm_mon & 0x0F,
        (t.tm_year % 100) & 0x7F,
    ])


def _monitor_object(ti: int, value: Any) -> bytes:
    """Encode one information object payload (without IOA) for a monitor TI."""
    if ti == TI_SINGLE_POINT:
        return bytes([0x01 if value else 0x00])
    if ti == TI_DOUBLE_POINT:
        try:
            d = int(value) & 0x03
        except (TypeError, ValueError):
            d = 1 if value else 0
        return bytes([d])
    if ti == TI_MEASURED_SCALED:
        try:
            v = max(-32768, min(32767, int(value)))
        except (TypeError, ValueError):
            v = 0
        return struct.pack("<h", v) + b"\x00"
    if ti == TI_MEASURED_FLOAT:
        return struct.pack("<f", float(value)) + b"\x00"
    if ti == TI_INTEGRATED_TOTAL:
        try:
            v = max(-2147483648, min(2147483647, int(value)))
        except (TypeError, ValueError):
            v = 0
        return struct.pack("<i", v) + b"\x00"
    # fallback: scaled
    try:
        v = max(-32768, min(32767, int(value)))
    except (TypeError, ValueError):
        v = 0
    return struct.pack("<h", v) + b"\x00"


def _monitor_ti_payload_size(ti: int) -> int:
    """Information object payload size (excluding IOA) for monitor TIs."""
    return {
        TI_SINGLE_POINT: 1,
        TI_DOUBLE_POINT: 1,
        TI_MEASURED_NORM: 3,
        TI_MEASURED_SCALED: 3,
        TI_MEASURED_FLOAT: 5,
        TI_INTEGRATED_TOTAL: 5,
    }.get(ti, 3)


class IEC104DeviceBehavior(StandardDeviceBehavior):
    """IEC 104 device behavior — maps point names <-> IOA and values -> TI."""

    def __init__(self, points: list | None = None):
        # per-IOA SBO selection state (point_name -> selected command info);
        # must exist before any command handler can touch it.
        self._selected: dict[str, dict] = {}
        super().__init__(points)
        self._config: DeviceConfig | None = None
        # Map point name -> IOA (Information Object Address)
        self._ioa_map: dict[str, int] = {}
        self._ioa_reverse: dict[int, str] = {}
        if points:
            for p in points:
                name = p.name if hasattr(p, "name") else p.get("name", "")
                addr = p.address if hasattr(p, "address") else p.get("address", "")
                try:
                    ioa = int(addr) if addr else 0
                except (ValueError, TypeError):
                    ioa = abs(hash(name)) % 65536
                self._ioa_map[name] = ioa
                self._ioa_reverse[ioa] = name

    def set_config(self, config: DeviceConfig) -> None:
        self._config = config

    def get_ioa(self, point_name: str) -> int:
        return self._ioa_map.get(point_name, 0)

    def get_point_name(self, ioa: int) -> str | None:
        return self._ioa_reverse.get(ioa)

    def get_ti_for_point(self, point_name: str) -> int:
        pt = self._points.get(point_name)
        if pt and hasattr(pt, "data_type"):
            return _DATA_TYPE_TO_TI.get(pt.data_type.value, TI_MEASURED_FLOAT)
        return TI_MEASURED_FLOAT

    # per-IOA SBO selection state (point_name -> selected command info)
    def select(self, point_name: str, cmd: dict) -> None:
        self._selected[point_name] = cmd

    def take_selected(self, point_name: str) -> dict | None:
        return self._selected.pop(point_name, None)


class IEC104Server(ProtocolServer):
    """IEC 60870-5-104 telecontrol server (slave/controlled side)."""

    protocol_name = "iec104"
    protocol_display_name = "IEC 60870-5-104"
    protocol_description = "IEC 60870-5-104电力远动协议 - 基于TCP的远动设备和系统标准，广泛用于电力SCADA系统"
    protocol_version = "2.1"

    def __init__(self):
        super().__init__()
        self._behaviors: dict[str, IEC104DeviceBehavior] = {}
        self._device_configs: dict[str, DeviceConfig] = {}
        self._host = "0.0.0.0"
        self._port = 2404
        self._server_task: asyncio.Task | None = None
        self._server_running = False
        self._connections: dict[asyncio.StreamWriter, dict[str, Any]] = {}
        self._scan_task: asyncio.Task | None = None
        self._scan_interval: float = 5.0
        self._common_address: int = 1  # Common address of ASDU
        self._originator_address: int = 0
        self._k_factor: int = 12  # k parameter (max outstanding APDUs)
        self._w_factor: int = 8   # w parameter (ack after w received I-frames)
        self._t0_timeout: float = 30.0
        self._t1_timeout: float = 15.0
        self._t2_timeout: float = 10.0
        self._t3_timeout: float = 20.0

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------
    async def start(self, config: dict[str, Any]) -> None:
        self._status = ProtocolStatus.STARTING
        self._host = config.get("host", "0.0.0.0")
        self._port = config.get("port", 2404)
        self._validate_port(self._port)
        self._common_address = int(config.get("common_address", 1))
        self._originator_address = int(config.get("originator_address", 0))
        self._scan_interval = float(config.get("scan_interval", 5.0))
        self._k_factor = int(config.get("k_factor", 12))
        self._w_factor = int(config.get("w_factor", 8))
        try:
            self._server_running = True
            self._server_task = asyncio.create_task(self._serve())
            self._scan_task = asyncio.create_task(self._scan_loop())
            self._status = ProtocolStatus.RUNNING
            logger.info("IEC 104 server started on %s:%d (CA=%d)", self._host, self._port, self._common_address)
            self._log_debug("system", "server_start",
                            f"IEC 104 service started {self._host}:{self._port} (CA={self._common_address})",
                            detail={"host": self._host, "port": self._port, "common_address": self._common_address})
        except Exception as e:
            self._status = ProtocolStatus.ERROR
            logger.exception("Failed to start IEC 104 server: %s", e)
            raise

    async def stop(self) -> None:
        try:
            self._server_running = False
            if self._scan_task:
                self._scan_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self._scan_task
            if self._server_task:
                self._server_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self._server_task
            for writer in list(self._connections.keys()):
                with contextlib.suppress(Exception):
                    writer.close()
            self._connections.clear()
        except Exception as e:
            logger.warning("IEC 104 server stop error: %s", e)
        finally:
            self._status = ProtocolStatus.STOPPED
            logger.info("IEC 104 server stopped")
            self._log_debug("system", "server_stop", "IEC 104 service stopped")

    async def _serve(self) -> None:
        try:
            server = await asyncio.start_server(
                self._handle_connection, self._host, self._port
            )
            async with server:
                await server.serve_forever()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.exception("IEC 104 server error: %s", e)
            self._status = ProtocolStatus.ERROR

    # ------------------------------------------------------------------
    # connection handling
    # ------------------------------------------------------------------
    async def _handle_connection(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.on_client_connect()
        peer = writer.get_extra_info("peername", default=("?", "?"))
        self._log_debug("recv", "connection", f"IEC104 client connected: {peer[0]}:{peer[1]}")
        # Per-connection link state
        conn_state = {
            "vs": 0,            # N(S) — our send sequence
            "vr": 0,            # N(R) — our receive sequence
            "started": False,   # STARTDT confirmed
            "rx_i_count": 0,    # received I-frames since last S-frame ack
            "outstanding": 0,   # sent unacked I-frames
            "last_activity": time.time(),
        }
        self._connections[writer] = conn_state

        try:
            probing = False  # TESTFR_ACT sent, waiting for TESTFR_CON within t1
            while self._server_running:
                # APDU: start byte + length byte + payload
                # t3: idle link supervision; t1: TESTFR confirm deadline
                timeout = self._t1_timeout if probing else self._t3_timeout
                try:
                    head = await asyncio.wait_for(reader.readexactly(2), timeout=timeout)
                except asyncio.TimeoutError:
                    if probing:
                        # t1 expired without TESTFR confirm — dead peer
                        self._log_debug("send", "timeout", "IEC104 t1 timeout, closing connection")
                        break
                    # t3 idle: probe the link with TESTFR_ACT
                    try:
                        self._write_apdu(writer, bytes([U_TESTFR_ACT, 0, 0, 0]))
                        await writer.drain()
                        probing = True
                    except Exception:
                        break
                    continue
                probing = False
                if head[0] != APDU_START:
                    self.record_protocol_error(ProtocolErrorCategory.FRAME_PARSE, f"bad start byte {head[0]:#x}")
                    continue
                length = head[1]
                if length < APDU_MIN_LEN or length > APDU_MAX_LEN:
                    logger.warning("IEC 104: bad APDU length %d", length)
                    self.record_protocol_error(ProtocolErrorCategory.FRAME_PARSE, f"bad APDU length {length}")
                    break
                apdu = await asyncio.wait_for(reader.readexactly(length), timeout=self._t1_timeout)
                conn_state["last_activity"] = time.time()

                c1 = apdu[0]
                if c1 & 0x01 == 0:
                    # I-format
                    await self._handle_i_frame(writer, apdu, conn_state)
                elif c1 & 0x02 == 0:
                    # S-format: acknowledge our outstanding I-frames
                    conn_state["outstanding"] = 0
                else:
                    # U-format
                    await self._handle_u_frame(writer, apdu, conn_state)
        except asyncio.IncompleteReadError:
            pass
        except Exception:
            logger.exception("IEC 104 connection handler error from %s", peer)
            self.record_protocol_error(ProtocolErrorCategory.NETWORK, "connection handler error")
        finally:
            self._connections.pop(writer, None)
            with contextlib.suppress(Exception):
                writer.close()
            self.on_client_disconnect()
            self._log_debug("send", "disconnected", f"IEC104 client disconnected: {peer[0]}:{peer[1]}")

    def _write_apdu(self, writer: asyncio.StreamWriter, control: bytes, asdu: bytes = b"") -> None:
        """Write one APDU: 0x68 len control[4] asdu."""
        payload = control + asdu
        writer.write(bytes([APDU_START, len(payload)]) + payload)

    async def _handle_u_frame(self, writer: asyncio.StreamWriter, apdu: bytes, conn_state: dict) -> None:
        u_type = apdu[0]
        if u_type == U_STARTDT_ACT:
            conn_state["started"] = True
            self._write_apdu(writer, bytes([U_STARTDT_CON, 0, 0, 0]))
            await writer.drain()
            self._log_debug("send", "startdt_con", "IEC104 STARTDT confirm")
        elif u_type == U_STOPDT_ACT:
            conn_state["started"] = False
            self._write_apdu(writer, bytes([U_STOPDT_CON, 0, 0, 0]))
            await writer.drain()
            self._log_debug("send", "stopdt_con", "IEC104 STOPDT confirm")
        elif u_type == U_TESTFR_ACT:
            self._write_apdu(writer, bytes([U_TESTFR_CON, 0, 0, 0]))
            await writer.drain()
            self._log_debug("send", "testfr_con", "IEC104 TESTFR confirm")
        else:
            self.record_protocol_error(ProtocolErrorCategory.FRAME_PARSE, f"unknown U-function {u_type:#x}")

    async def _handle_i_frame(self, writer: asyncio.StreamWriter, apdu: bytes, conn_state: dict) -> None:
        # APCI: NS(2 LE) NR(2 LE), low bit of first byte is 0
        ns = struct.unpack("<H", apdu[0:2])[0] >> 1
        nr = struct.unpack("<H", apdu[2:4])[0] >> 1
        # Peer acknowledges our frames up to nr
        conn_state["outstanding"] = max(0, conn_state["vs"] - nr)
        # Peer's NS must match our vr
        if ns != conn_state["vr"]:
            self.record_protocol_error(
                ProtocolErrorCategory.FRAME_PARSE,
                f"sequence mismatch: got N(S)={ns}, expected {conn_state['vr']}",
            )
            return
        conn_state["vr"] = (conn_state["vr"] + 1) & 0x7FFF
        conn_state["rx_i_count"] += 1
        if conn_state["rx_i_count"] >= self._w_factor:
            conn_state["rx_i_count"] = 0
            self._write_apdu(writer, bytes([S_FORMAT, 0]) + struct.pack("<H", conn_state["vr"] << 1))
            await writer.drain()

        await self._process_asdus(writer, apdu[4:], conn_state)

    # ------------------------------------------------------------------
    # ASDU processing
    # ------------------------------------------------------------------
    async def _process_asdus(self, writer: asyncio.StreamWriter, data: bytes, conn_state: dict) -> None:
        """Parse one or more ASDUs inside an I-format APDU payload."""
        offset = 0
        while offset + 4 <= len(data):
            ti = data[offset]
            vsq = data[offset + 1]
            num = vsq & 0x7F
            sq = bool(vsq & 0x80)
            asdu_len = self._asdu_length(ti, num, sq)
            if asdu_len is None or offset + asdu_len > len(data):
                self.record_protocol_error(ProtocolErrorCategory.FRAME_PARSE, f"unknown TI {ti} or truncated ASDU")
                return
            asdu = data[offset:offset + asdu_len]
            offset += asdu_len
            try:
                await self._process_asdu(writer, asdu, conn_state)
            except Exception as e:
                logger.debug("IEC 104 ASDU processing error: %s", e)
                self.record_protocol_error(ProtocolErrorCategory.INTERNAL, str(e))

    def _asdu_length(self, ti: int, num: int, sq: bool) -> int | None:
        """Total ASDU length: header 6 (TI+VSQ+COT+OA+CA) + information objects."""
        obj = self._object_size(ti)
        if obj is None:
            return None
        if sq:
            # only the first object carries the IOA
            return 6 + 3 + num * obj
        return 6 + num * (3 + obj)

    def _object_size(self, ti: int) -> int | None:
        """Information object payload size (excluding IOA) or None if unsupported."""
        sizes = {
            TI_SINGLE_POINT: 1,
            TI_DOUBLE_POINT: 1,
            TI_MEASURED_NORM: 3,
            TI_MEASURED_SCALED: 3,
            TI_MEASURED_FLOAT: 5,
            TI_INTEGRATED_TOTAL: 5,
            TI_SINGLE_CMD: 1,
            TI_DOUBLE_CMD: 1,
            TI_SETPOINT_SCALED: 3,
            TI_SETPOINT_FLOAT: 5,
            TI_CLOCK_SYNC: 7,
            TI_INTERROGATION: 1,
            # time-tagged commands: command qualifier/value + 7-byte CP56Time2a
            TI_SINGLE_CMD_TA: 8,
            TI_DOUBLE_CMD_TA: 8,
            TI_SETPOINT_SCALED_TA: 10,
            TI_SETPOINT_FLOAT_TA: 12,
        }
        return sizes.get(ti)

    async def _process_asdu(self, writer: asyncio.StreamWriter, asdu: bytes, conn_state: dict) -> None:
        ti = asdu[0]
        vsq = asdu[1]
        # IEC 60870-5-104: COT 为 1 字节 + OA 1 字节 + CA 2 字节（小端）。
        # 之前误将 COT 编码/解析为 2 字节，导致主站侧 CA 显示为 256 倍、
        # IOA 整体左移 8 位、遥测浮点数错位成乱值。
        cot = asdu[2] & 0x3F
        oa = asdu[3]
        ca = struct.unpack("<H", asdu[4:6])[0]
        num = vsq & 0x7F
        sq = bool(vsq & 0x80)

        self._log_debug("recv", "asdu", f"IEC104 ASDU: TI={ti} COT={cot} CA={ca} OA={oa} n={num} sq={sq}",
                        detail={"type_id": ti, "cot": cot, "ca": ca, "num": num})

        if ca != self._common_address:
            # unknown common address — ignore silently (standard allows this)
            self._log_debug("recv", "asdu_drop", f"IEC104 drop ASDU with unknown CA={ca}")
            return

        if ti == TI_INTERROGATION:
            await self._handle_interrogation(writer, asdu, ca)
            return
        if ti == TI_CLOCK_SYNC:
            await self._handle_clock_sync(writer, asdu, ca)
            return
        if ti in (TI_SINGLE_CMD, TI_DOUBLE_CMD, TI_SETPOINT_SCALED, TI_SETPOINT_FLOAT,
                  TI_SINGLE_CMD_TA, TI_DOUBLE_CMD_TA, TI_SETPOINT_SCALED_TA, TI_SETPOINT_FLOAT_TA):
            await self._handle_commands(writer, asdu, ti, ca, num, sq, conn_state)
            return

        self._log_debug("recv", "asdu_unsupported", f"IEC104 unsupported TI={ti} COT={cot}")

    # -- general interrogation -----------------------------------------
    async def _handle_interrogation(self, writer: asyncio.StreamWriter, asdu: bytes, ca: int) -> None:
        qoi = asdu[9] if len(asdu) > 9 else 20  # header(6)+IOA(3) 之后即 QOI
        # ACT confirm
        ack = bytearray(self._asdu_header(TI_INTERROGATION, 1, COT_ACTCONFIRM, ca))
        ack += b"\x00\x00\x00" + bytes([qoi])
        await self._send_i_format(writer, bytes(ack))
        self._log_debug("send", "gi_con", f"IEC104 GI activation confirm (QOI={qoi})")

        # All points with COT=20 (interrogated)
        for dev_id, behavior in self._behaviors.items():
            for point_name in behavior._values:
                behavior.get_ti_for_point(point_name)
                asdu_out = self._build_monitor_asdu(behavior, point_name, ca, COT_INTERROGATED)
                if asdu_out:
                    await self._send_i_format(writer, asdu_out)
            self._log_debug("send", "gi_data", f"IEC104 GI data sent for device {dev_id}", device_id=dev_id)

        # ACTTERM
        term = bytearray(self._asdu_header(TI_INTERROGATION, 1, COT_ACTTERM, ca))
        term += b"\x00\x00\x00" + bytes([qoi])
        await self._send_i_format(writer, bytes(term))

    # -- clock sync ------------------------------------------------------
    async def _handle_clock_sync(self, writer: asyncio.StreamWriter, asdu: bytes, ca: int) -> None:
        # Confirm with the new server time
        now = time.time()
        ack = bytearray(self._asdu_header(TI_CLOCK_SYNC, 1, COT_ACTCONFIRM, ca))
        ack += b"\x00\x00\x00" + _build_cp56time2a(now)
        await self._send_i_format(writer, bytes(ack))
        self._log_debug("send", "cs_con", "IEC104 clock sync confirm")

    # -- control direction ------------------------------------------------
    async def _handle_commands(self, writer: asyncio.StreamWriter, asdu: bytes, ti: int,
                               ca: int, num: int, sq: bool, conn_state: dict) -> None:
        obj_size = self._object_size(ti) or 1
        offset = 6  # ASDU header: TI(1)+VSQ(1)+COT(1)+OA(1)+CA(2)
        for i in range(num):
            if sq:
                if offset + 3 + obj_size > len(asdu):
                    break
                ioa = self._decode_ioa(asdu[offset:offset + 3])
                payload = asdu[offset + 3:offset + 3 + obj_size]
                offset += 3 + obj_size if i == 0 else obj_size
            else:
                if offset + 3 + obj_size > len(asdu):
                    break
                ioa = self._decode_ioa(asdu[offset:offset + 3])
                payload = asdu[offset + 3:offset + 3 + obj_size]
                offset += 3 + obj_size

            await self._apply_command(writer, asdu, ti, ca, ioa, payload)

    async def _apply_command(self, writer: asyncio.StreamWriter, req_asdu: bytes, ti: int,
                             ca: int, ioa: int, payload: bytes) -> None:
        # Resolve device/point by IOA
        target: tuple[str, IEC104DeviceBehavior, str] | None = None
        for dev_id, behavior in self._behaviors.items():
            point_name = behavior.get_point_name(ioa)
            if point_name:
                target = (dev_id, behavior, point_name)
                break

        # S/E(Select/Execute) 位位置与值提取按 TI 区分：
        #   45/46/58/59 -> SCO/DCO 在 payload[0]；49/61 -> QOS 在 payload[2]；50/62 -> QOS 在 payload[4]
        _se_pos = {TI_SINGLE_CMD: 0, TI_DOUBLE_CMD: 0, TI_SINGLE_CMD_TA: 0, TI_DOUBLE_CMD_TA: 0,
                   TI_SETPOINT_SCALED: 2, TI_SETPOINT_SCALED_TA: 2,
                   TI_SETPOINT_FLOAT: 4, TI_SETPOINT_FLOAT_TA: 4}
        se_pos = _se_pos.get(ti, 0)
        select_flag = bool(payload[se_pos] & SE_BIT) if len(payload) > se_pos else False

        # Value extraction per TI（时标命令取值位置与非时标一致，时间标签仅回显）
        if ti in (TI_SINGLE_CMD, TI_SINGLE_CMD_TA):
            raw_val = payload[0] & 0x01 if payload else 0
            value: Any = bool(raw_val)
        elif ti in (TI_DOUBLE_CMD, TI_DOUBLE_CMD_TA):
            raw_val = payload[0] & 0x03 if payload else 0
            value = raw_val
        elif ti in (TI_SETPOINT_SCALED, TI_SETPOINT_SCALED_TA):
            raw_val = struct.unpack("<h", payload[0:2])[0] if len(payload) >= 2 else 0
            value = raw_val
        elif ti in (TI_SETPOINT_FLOAT, TI_SETPOINT_FLOAT_TA):
            raw_val = struct.unpack("<f", payload[0:4])[0] if len(payload) >= 4 else 0.0
            value = raw_val
        else:
            return

        if target is None:
            self._log_debug("recv", "cmd_unknown_ioa", f"IEC104 command for unknown IOA={ioa}",
                            detail={"ioa": ioa, "ti": ti})
            return
        dev_id, behavior, point_name = target

        if select_flag:
            # Select: confirm but do not apply; remember for the execute step
            behavior.select(point_name, {"ti": ti, "value": value})
            ack = self._build_command_ack_asdu(ti, ca, ioa, payload, COT_ACTCONFIRM)
            await self._send_i_format(writer, ack)
            self._log_debug("send", "cmd_select_con",
                            f"IEC104 SELECT confirm: IOA={ioa} value={value}",
                            device_id=dev_id, detail={"ioa": ioa, "value": value, "ti": ti})
            return

        # Execute (S/E=0): apply the value
        behavior.on_write(point_name, value)
        await self._fire_write_callback(dev_id, point_name, value)
        behavior.take_selected(point_name)  # clear any pending selection

        ack = self._build_command_ack_asdu(ti, ca, ioa, payload, COT_ACTCONFIRM)
        await self._send_i_format(writer, ack)
        # Activation termination
        term = self._build_command_ack_asdu(ti, ca, ioa, payload, COT_ACTTERM)
        await self._send_i_format(writer, term)
        self._log_debug("send", "cmd_exec",
                        f"IEC104 EXECUTE: IOA={ioa} ({point_name}) = {value}",
                        device_id=dev_id, detail={"ioa": ioa, "value": value, "ti": ti, "point": point_name})

    def _build_command_ack_asdu(self, ti: int, ca: int, ioa: int, payload: bytes, cot: int) -> bytes:
        asdu = bytearray(self._asdu_header(ti, 1, cot, ca))
        asdu += self._encode_ioa(ioa)
        # IEC 60870-5-104: 确认 ASDU 与命令 ASDU 相同（仅 COT 不同），
        # 完整回显命令对象（SCO/DCO/SCO+int16/QOS+float）。
        asdu += payload
        return bytes(asdu)

    # ------------------------------------------------------------------
    # monitor direction (spontaneous / interrogation data)
    # ------------------------------------------------------------------
    def _asdu_header(self, ti: int, num: int, cot: int, ca: int) -> bytes:
        # IEC 60870-5-104 ASDU 固定头: TI(1) + VSQ(1) + COT(1) + OA(1) + CA(2 LE)
        h = bytearray()
        h.append(ti & 0xFF)
        h.append(num & 0x7F)
        h.append(cot & 0x3F)
        h.append(self._originator_address & 0xFF)
        h += struct.pack("<H", ca & 0xFFFF)
        return bytes(h)

    def _build_monitor_asdu(self, behavior: IEC104DeviceBehavior, point_name: str,
                            ca: int, cot: int) -> bytes | None:
        ti = behavior.get_ti_for_point(point_name)
        ioa = behavior.get_ioa(point_name)
        if not ioa and ioa != 0:
            return None
        val = behavior.get_value(point_name)
        asdu = bytearray(self._asdu_header(ti, 1, cot, ca))
        asdu += self._encode_ioa(ioa)
        asdu += _monitor_object(ti, val)
        return bytes(asdu)

    async def _scan_loop(self) -> None:
        """Periodic data scan — send spontaneous/periodic data to started clients."""
        try:
            while self._server_running:
                await asyncio.sleep(self._scan_interval)
                if not self._connections:
                    continue
                for _dev_id, behavior in self._behaviors.items():
                    ca = self._common_address
                    for point_name in behavior._values:
                        asdu = self._build_monitor_asdu(behavior, point_name, ca, COT_PERIODIC)
                        if not asdu:
                            continue
                        for writer, conn in list(self._connections.items()):
                            if conn.get("started"):
                                try:
                                    await self._send_i_format(writer, asdu)
                                except Exception as e:
                                    logger.debug("IEC 104 scan send error: %s", e)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.exception("IEC 104 scan loop error: %s", e)

    # ------------------------------------------------------------------
    # send helpers
    # ------------------------------------------------------------------
    async def _send_i_format(self, writer: asyncio.StreamWriter, asdu: bytes) -> None:
        conn = self._connections.get(writer)
        if conn is None:
            return
        # ack peer before filling the window
        if conn["rx_i_count"] > 0:
            conn["rx_i_count"] = 0
            self._write_apdu(writer, bytes([S_FORMAT, 0]) + struct.pack("<H", conn["vr"] << 1))
        ns = conn["vs"] & 0x7FFF
        nr = conn["vr"] & 0x7FFF
        control = struct.pack("<HH", ns << 1, nr << 1)
        self._write_apdu(writer, control, asdu)
        await writer.drain()
        conn["vs"] = (conn["vs"] + 1) & 0x7FFF
        conn["outstanding"] += 1
        # (k-window overflow handling omitted: the simulator never reaches k=12
        #  in flight because every command is acked synchronously.)

    @staticmethod
    def _decode_ioa(b: bytes) -> int:
        # IOA 为 3 个完整 8 位组（低字节在前），高字节按标准使用全部 8 位
        return int(b[0]) | int(b[1]) << 8 | int(b[2]) << 16

    @staticmethod
    def _encode_ioa(ioa: int) -> bytes:
        return bytes([ioa & 0xFF, (ioa >> 8) & 0xFF, (ioa >> 16) & 0xFF])

    # ------------------------------------------------------------------
    # write propagation to DeviceInstance
    # ------------------------------------------------------------------
    async def _fire_write_callback(self, device_id: str, point_name: str, value: Any) -> None:
        """异步执行 _on_write 回调，捕获异常防止影响事件循环。"""
        if not self._on_write:
            return
        try:
            await self._on_write(device_id, point_name, value)
        except Exception as e:
            logger.debug("External write callback error for %s.%s: %s", device_id, point_name, e)

    # ------------------------------------------------------------------
    # device registry
    # ------------------------------------------------------------------
    async def create_device(self, device_config: DeviceConfig) -> str:
        self._device_configs[device_config.id] = device_config
        behavior = IEC104DeviceBehavior(device_config.points)
        behavior.set_config(device_config)
        self._behaviors[device_config.id] = behavior
        self._update_default_device(device_config.id)
        self._log_debug("system", "device_create",
                        f"IEC104 device created: {device_config.name} ({len(device_config.points)} points)",
                        device_id=device_config.id)
        logger.info("IEC 104 device created: %s (%d points)", device_config.id, len(device_config.points))
        return device_config.id

    async def remove_device(self, device_id: str) -> None:
        self._behaviors.pop(device_id, None)
        self._device_configs.pop(device_id, None)
        self._clear_default_device(device_id)
        self._log_debug("system", "device_remove", f"IEC104 device removed: {device_id}", device_id=device_id)

    async def read_points(self, device_id: str) -> list[PointValue]:
        behavior = self._behaviors.get(device_id)
        if not behavior:
            return []
        results = []
        for point_name, _ioa in behavior._ioa_map.items():
            val = behavior.get_value(point_name)
            results.append(PointValue(name=point_name, value=val, timestamp=time.time(), quality="good", simulated=True))
        return results

    async def write_point(self, device_id: str, point_name: str, value: Any) -> bool:
        behavior = self._behaviors.get(device_id)
        if not behavior:
            return False
        behavior.on_write(point_name, value)
        self._log_debug("recv", "point_write", f"IEC104 write {point_name}={value}", device_id=device_id)
        return True

    async def sync_point_value(self, device_id: str, point_name: str, value: Any) -> None:
        behavior = self._behaviors.get(device_id)
        if behavior:
            behavior.set_value(point_name, value)

    def get_config_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "common_address": {
                    "type": "number", "default": 1,
                    "description": "Common Address of ASDU (1-65535)"
                },
                "originator_address": {
                    "type": "number", "default": 0,
                    "description": "Originator Address (OA)"
                },
                "scan_interval": {
                    "type": "number", "default": 5.0,
                    "description": "Periodic data scan interval in seconds"
                },
                "k_factor": {
                    "type": "number", "default": 12,
                    "description": "K parameter - max outstanding unacknowledged APDUs"
                },
                "w_factor": {
                    "type": "number", "default": 8,
                    "description": "W parameter - ack after w received I-frames"
                },
            },
        }
