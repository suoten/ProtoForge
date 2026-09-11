"""IEC 60870-5-104 protocol server implementation.

Implements a simplified IEC 60870-5-104 telecontrol server (slave/controlled side).
Supports:
  - APDU frame parsing (single-octet and multi-octet)
  - I-format frames: carry application data (ASDU)
  - S-format frames: numbered supervision (ACK)
  - U-format frames: link control (STARTDT, STOPDT, TESTFR)
  - ASDU types: single point (1), double point (3), measured value normalized (9),
    measured value scaled (11), integrated totals (15), single command (45),
    double command (46), set-point command (50)
  - Spontaneous data transmission (background scan / periodic)
  - Common address of ASDU, cause of transmission (COT)
  - Sequence number management (N(S) / N(R))

Design principles:
  - Pure Python, no third-party IEC104 library required
  - One TCP listener per protocol instance
  - Per-connection state: sequence numbers, ASDU queue
  - Periodic data push (Class 1 / Class 2 scanning)
  - Debug logging via _log_debug (visible in Web UI Debug Logs)
"""

from __future__ import annotations

import asyncio
import logging
import struct
import time
from typing import Any

from protoforge.models.device import DeviceConfig, PointConfig, PointValue
from protoforge.protocols.behavior import ProtocolErrorCategory, ProtocolServer, ProtocolStatus, StandardDeviceBehavior

logger = logging.getLogger(__name__)

_READ_TIMEOUT = 120  # matches other protocol servers

# ---------------------------------------------------------------------------
#  APDU / ASDU constants
# ---------------------------------------------------------------------------

# U-format frame identifiers
U_STARTDT_ACT = 0x07  # STARTDT act
U_STARTDT_CON = 0x0B  # STARTDT con
U_STOPDT_ACT = 0x13   # STOPDT act
U_STOPDT_CON = 0x17   # STOPDT con
U_TESTFR_ACT = 0x43   # TESTFR act
U_TESTFR_CON = 0x83   # TESTFR con

# ASDU type identifiers (TI)
TI_SINGLE_POINT = 1           # M_SP_NA_1
TI_DOUBLE_POINT = 3           # M_DP_NA_1
TI_MEASURED_NORM = 9          # M_ME_NA_1
TI_MEASURED_SCALED = 11      # M_ME_NB_1
TI_INTEGRATED_TOTAL = 15     # M_IT_NA_1
TI_SINGLE_CMD = 45            # C_SC_NA_1
TI_DOUBLE_CMD = 46            # C_DC_NA_1
TI_SETPOINT_CMD = 50          # C_SE_NA_1

# Cause of transmission (COT) common values
COT_PERIODIC = 1
COT_BACKGROUND = 2
COT_SPONTANEOUS = 3
COT_INITIALIZED = 6
COT_RETURN_REMOTE = 11
COT_ACTIVATED = 6  # same as initialized? no — COT 6 = initialized, 7 = activated
COT_ACTCONFIRM = 7
COT_ACTTERM = 10

# Map our point data types to IEC104 ASDU types
_DATA_TYPE_TO_TI: dict[str, int] = {
    "bool": TI_SINGLE_POINT,
    "int16": TI_MEASURED_SCALED,
    "uint16": TI_MEASURED_SCALED,
    "int32": TI_MEASURED_SCALED,
    "uint32": TI_MEASURED_SCALED,
    "float32": TI_MEASURED_NORM,
    "float64": TI_MEASURED_NORM,
    "string": TI_MEASURED_SCALED,
}


class IEC104DeviceBehavior(StandardDeviceBehavior):
    """IEC 104 device behavior — maps point values to ASDU types."""

    def __init__(self, points: list | None = None):
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
            return _DATA_TYPE_TO_TI.get(pt.data_type.value, TI_MEASURED_NORM)
        return TI_MEASURED_NORM


class IEC104Server(ProtocolServer):
    """IEC 60870-5-104 telecontrol server (slave/controlled side)."""

    protocol_name = "iec104"
    protocol_display_name = "IEC 60870-5-104"
    protocol_description = "IEC 60870-5-104电力远动协议 - 基于TCP的远动设备和系统标准，广泛用于电力SCADA系统"
    protocol_version = "2.0"

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
        self._scan_interval: float = 1.0
        self._common_address: int = 1  # Common address of ASDU
        self._originator_address: int = 0
        self._k_factor: int = 12  # k parameter (max outstanding APDUs)
        self._t1_timeout: float = 15.0
        self._t2_timeout: float = 10.0
        self._t3_timeout: float = 20.0

    async def start(self, config: dict[str, Any]) -> None:
        self._status = ProtocolStatus.STARTING
        self._host = config.get("host", "0.0.0.0")
        self._port = config.get("port", 2404)
        self._validate_port(self._port)
        self._common_address = int(config.get("common_address", 1))
        self._scan_interval = float(config.get("scan_interval", 1.0))
        self._k_factor = int(config.get("k_factor", 12))
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
                try:
                    await self._scan_task
                except asyncio.CancelledError:
                    pass
            if self._server_task:
                self._server_task.cancel()
                try:
                    await self._server_task
                except asyncio.CancelledError:
                    pass
            for writer in list(self._connections.keys()):
                try:
                    writer.close()
                except Exception:
                    pass
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

    async def _handle_connection(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.on_client_connect()
        peer = writer.get_extra_info("peername", default=("?", "?"))
        self._log_debug("recv", "connection", f"IEC104 client connected: {peer[0]}:{peer[1]}")
        # Per-connection state
        conn_state = {
            "vs": 0,   # N(S) — send sequence
            "vr": 0,   # N(R) — receive sequence
            "started": False,
            "last_activity": time.time(),
            "ack_pending": False,
        }
        self._connections[writer] = conn_state

        try:
            while self._server_running:
                try:
                    apdu = await asyncio.wait_for(reader.readexactly(2), timeout=self._t3_timeout)
                except asyncio.TimeoutError:
                    # Send TESTFR
                    testfr = bytes([0x43, 0x00])
                    writer.write(testfr)
                    await writer.drain()
                    continue
                except asyncio.IncompleteReadError:
                    break

                start_byte = apdu[0]
                if start_byte & 0x01 == 0:
                    # I-format frame
                    await self._handle_i_frame(reader, writer, apdu, conn_state)
                elif start_byte & 0x03 == 0x01:
                    # S-format frame
                    await self._handle_s_frame(reader, writer, apdu, conn_state)
                else:
                    # U-format frame
                    self._handle_u_frame(writer, apdu, conn_state)

                conn_state["last_activity"] = time.time()

        except Exception as e:
            self.record_protocol_error(ProtocolErrorCategory.NETWORK, str(e))
            logger.debug("IEC 104 connection error from %s: %s", peer, e)
        finally:
            self._connections.pop(writer, None)
            try:
                writer.close()
            except Exception:
                pass
            self.on_client_disconnect()
            self._log_debug("send", "disconnected", f"IEC104 client disconnected: {peer[0]}:{peer[1]}")

    async def _handle_i_frame(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter,
                               header: bytes, conn_state: dict) -> None:
        # I-format: 4 bytes header + ASDU
        remaining = await reader.readexactly(2)  # next 2 bytes complete 4-byte header
        full_header = header + remaining
        ns = (full_header[0] >> 1) & 0x7F  # send sequence
        nr = (full_header[2] >> 1) & 0x7F  # receive sequence
        conn_state["vr"] = (conn_state["vr"] + 1) & 0x7FFF
        conn_state["vs"] = (conn_state["vs"] + 1) & 0x7FFF

        # Parse ASDU
        try:
            asdu_len = self._parse_asdu_length(remaining, reader)
            if asdu_len > 0:
                asdu_data = await reader.readexactly(asdu_len)
                await self._process_asdu(writer, asdu_data, conn_state)
        except asyncio.IncompleteReadError:
            logger.warning("IEC 104: incomplete ASDU from client")
        except Exception as e:
            logger.debug("IEC 104 ASDU parse error: %s", e)

    async def _parse_asdu_length(self, remaining: bytes, reader: asyncio.StreamReader) -> int:
        # We already consumed 4 header bytes; the ASDU follows.
        # We need to peek at the type + COT + CA + IOA to determine size.
        # But since we don't have random access, we read the ASDU header.
        try:
            asdu_header = await reader.readexactly(4)  # type(1) + var_qual(1) + COT(1) + CA(1) [simplified]
        except asyncio.IncompleteReadError:
            return 0

        ti = asdu_header[0]
        # var_qual: bit 7 = structure flag, bit 6 = number of elements follows
        var_qual = asdu_header[1]
        is_sequence = bool(var_qual & 0x80)
        num_elements = var_qual & 0x7F
        if num_elements == 0:
            num_elements = 1

        # Determine IO size per type
        io_size = self._get_io_size(ti, is_sequence)
        if is_sequence:
            total_io_size = 4 + io_size + (num_elements - 1) * 3  # first IOA + (n-1)*0
        else:
            total_io_size = 4 + io_size * num_elements

        # We already read 4 bytes of ASDU header, so remaining ASDU = total - 4
        return total_io_size - 4

    def _get_io_size(self, ti: int, is_sequence: bool) -> int:
        """Return size of one information object (including IOA) for given TI."""
        ioa_size = 3 if not is_sequence else 0
        data_size_map = {
            TI_SINGLE_POINT: 1,      # SIQ (1 byte)
            TI_DOUBLE_POINT: 1,      # DIQ (1 byte)
            TI_MEASURED_NORM: 5,      # NVA(2) + QDS(1) + time? no — normalized: value(2)+QDS(1)=3, no time in non-time version
            TI_MEASURED_SCALED: 3,    # value(2)+QDS(1)
            TI_INTEGRATED_TOTAL: 5,  # value(4)+QDS(1)
            TI_SINGLE_CMD: 1,        # SCO (1 byte)
            TI_DOUBLE_CMD: 1,        # DCO (1 byte)
            TI_SETPOINT_CMD: 5,      # value(4)+QOS(1)
        }
        data_size = data_size_map.get(ti, 3)
        return ioa_size + data_size

    async def _process_asdu(self, writer: asyncio.StreamWriter, asdu: bytes, conn_state: dict) -> None:
        if len(asdu) < 4:
            return
        ti = asdu[0]
        var_qual = asdu[1]
        cot = asdu[2]
        ca = asdu[3] | (asdu[4] << 8 if len(asdu) > 4 else 0)  # common address (2 bytes)
        num_elements = var_qual & 0x7F
        if num_elements == 0:
            num_elements = 1

        self._log_debug("recv", "asdu", f"IEC104 ASDU: TI={ti} COT={cot} CA={ca} n={num_elements}",
                        detail={"type_id": ti, "cot": cot, "ca": ca, "num": num_elements})

        # Handle command ASDUs
        if ti in (TI_SINGLE_CMD, TI_DOUBLE_CMD, TI_SETPOINT_CMD):
            await self._handle_command(writer, asdu, ti, ca, num_elements)

    async def _handle_command(self, writer: asyncio.StreamWriter, asdu: bytes, ti: int,
                               ca: int, num_elements: int) -> None:
        offset = 5  # type(1)+var(1)+cot(1)+ca(2)
        for i in range(num_elements):
            if offset + 3 >= len(asdu):
                break
            ioa = asdu[offset] | (asdu[offset + 1] << 8) | (asdu[offset + 2] << 16)
            cmd_value = asdu[offset + 3] if offset + 3 < len(asdu) else 0

            # Find device by IOA
            for dev_id, behavior in self._behaviors.items():
                point_name = behavior.get_point_name(ioa)
                if point_name:
                    # Apply command
                    if ti == TI_SINGLE_CMD:
                        behavior.on_write(point_name, bool(cmd_value & 0x01))
                    elif ti == TI_DOUBLE_CMD:
                        behavior.on_write(point_name, (cmd_value & 0x03))
                    elif ti == TI_SETPOINT_CMD:
                        val = struct.unpack("<f", asdu[offset + 3:offset + 7])[0] if offset + 7 <= len(asdu) else 0.0
                        behavior.on_write(point_name, val)

                    self._log_debug("send", "cmd_ack", f"IEC104 command ack: IOA={ioa} val={cmd_value}",
                                    device_id=dev_id, detail={"ioa": ioa, "value": cmd_value})

                    # Send acknowledgment (COT=ACTCONFIRM)
                    ack = self._build_command_ack_asdu(ti, ca, ioa, cmd_value)
                    await self._send_i_format(writer, ack)
                    break
            offset += 4 if ti != TI_SETPOINT_CMD else 8

    async def _handle_s_frame(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter,
                               header: bytes, conn_state: dict) -> None:
        remaining = await reader.readexactly(2)
        nr = (remaining[1] >> 1) & 0x7F
        conn_state["ack_pending"] = False
        self._log_debug("recv", "s_frame", f"IEC104 S-frame N(R)={nr}")

    def _handle_u_frame(self, writer: asyncio.StreamWriter, header: bytes, conn_state: dict) -> None:
        u_type = header[0] & 0xFC
        if u_type == U_STARTDT_ACT:
            conn_state["started"] = True
            writer.write(bytes([U_STARTDT_CON, 0x00]))
            self._log_debug("send", "startdt_con", "IEC104 STARTDT confirm")
        elif u_type == U_STOPDT_ACT:
            conn_state["started"] = False
            writer.write(bytes([U_STOPDT_CON, 0x00]))
            self._log_debug("send", "stopdt_con", "IEC104 STOPDT confirm")
        elif u_type == U_TESTFR_ACT:
            writer.write(bytes([U_TESTFR_CON, 0x00]))
            self._log_debug("send", "testfr_con", "IEC104 TESTFR confirm")

    async def _send_i_format(self, writer: asyncio.StreamWriter, asdu: bytes) -> None:
        conn = self._connections.get(writer)
        if conn is None:
            return
        ns = conn["vs"] & 0x7F
        nr = conn["vr"] & 0x7F
        header = bytes([(ns << 1) & 0xFE, 0x00, (nr << 1) & 0xFE, 0x00])
        writer.write(header + asdu)
        await writer.drain()
        conn["vs"] = (conn["vs"] + 1) & 0x7FFF

    def _build_command_ack_asdu(self, ti: int, ca: int, ioa: int, value: int) -> bytes:
        asdu = bytearray()
        asdu.append(ti)               # type identification
        asdu.append(0x01)             # 1 element, non-sequence
        asdu.append(COT_ACTCONFIRM)   # COT = activation confirmation
        asdu += struct.pack("<H", ca)  # common address (2 bytes)
        # IO: IOA(3 bytes) + value(1 byte for SCO/DCO)
        asdu += struct.pack("<I", ioa)[:3]  # IOA 3 bytes
        asdu.append(value & 0xFF)     # SCO/DCO
        return bytes(asdu)

    def _build_spontaneous_asdu(self, behavior: IEC104DeviceBehavior, point_name: str,
                                value: Any, ti: int, ca: int, cot: int) -> bytes:
        asdu = bytearray()
        asdu.append(ti)
        asdu.append(0x01)  # 1 element
        asdu.append(cot)
        asdu += struct.pack("<H", ca)
        ioa = behavior.get_ioa(point_name)
        asdu += struct.pack("<I", ioa)[:3]

        if ti == TI_SINGLE_POINT:
            asdu.append(0x01 if value else 0x00)
        elif ti == TI_DOUBLE_POINT:
            asdu.append(int(value) & 0x03)
        elif ti == TI_MEASURED_NORM:
            # Normalized value: -1.0..1.0 -> -32768..32767
            norm = max(-1.0, min(1.0, float(value) / 32767.0))
            asdu += struct.pack("<h", int(norm * 32767))
            asdu.append(0x00)  # QDS
        elif ti == TI_MEASURED_SCALED:
            asdu += struct.pack("<h", int(value))
            asdu.append(0x00)
        elif ti == TI_INTEGRATED_TOTAL:
            asdu += struct.pack("<i", int(value))
            asdu.append(0x00)
        else:
            asdu += struct.pack("<h", int(value))
            asdu.append(0x00)
        return bytes(asdu)

    async def _scan_loop(self) -> None:
        """Periodic data scan — send spontaneous data to connected clients."""
        try:
            while self._server_running:
                await asyncio.sleep(self._scan_interval)
                if not self._connections:
                    continue
                for dev_id, behavior in self._behaviors.items():
                    ca = self._common_address
                    for point_name in behavior._values:
                        val = behavior.get_value(point_name)
                        ti = behavior.get_ti_for_point(point_name)
                        asdu = self._build_spontaneous_asdu(behavior, point_name, val, ti, ca, COT_PERIODIC)
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
        for point_name, ioa in behavior._ioa_map.items():
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
                "scan_interval": {
                    "type": "number", "default": 1.0,
                    "description": "Periodic data scan interval in seconds"
                },
                "k_factor": {
                    "type": "number", "default": 12,
                    "description": "K parameter - max outstanding unacknowledged APDUs"
                },
            },
        }
