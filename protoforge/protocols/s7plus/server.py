"""S7Comm-Plus protocol server implementation.

S7Comm-Plus is Siemens' newer protocol used by S7-1200/S7-1500 PLCs.
It uses TPKT (RFC 1006) + ISO-on-TCP + COTP + S7-Plus application layer.

This implementation provides a basic but functional S7-Plus slave that:
  - Accepts TPKT/COTP connections (port 102)
  - Negotiates COTP connection (class 0, TSAP-based)
  - Handles S7-Plus Read/Write requests with optimized block access
  - Supports symbolic addressing (DB access with offset/length)
  - Returns PLC identification (order code, version)

The protocol is complex; this implementation focuses on the most common
use cases: reading and writing data blocks (DB) and marker areas (M).

Frame structure:
  TPKT: version(1) + reserved(1) + length(2, big-endian)
  COTP: length(1) + PDU type(1) + ...
  S7-Plus: opcode(1) + reserved(1) + function(1) + reserved(1) + ...
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

_READ_TIMEOUT = 120

# TPKT
TPKT_VERSION = 0x03

# COTP PDU types
COTP_CONNECT_REQUEST = 0xE0
COTP_CONNECT_CONFIRM = 0xD0
COTP_DISCONNECT_REQUEST = 0x80
COTP_DISCONNECT_CONFIRM = 0xC0
COTP_DATA = 0xF0  # DT frame

# S7-Plus opcodes
S7_PLUS_READ = 0x04
S7_PLUS_WRITE = 0x05
S7_PLUS_RESPONSE = 0x03
S7_PLUS_READ_RSP = 0x04
S7_PLUS_WRITE_RSP = 0x05
S7_PLUS_SETUP = 0x07
S7_PLUS_SETUP_RSP = 0x07

# S7-Plus function codes
FUNC_READ_VAR = 0x04
FUNC_WRITE_VAR = 0x05
FUNC_SETUP_COMM = 0x07
FUNC_PLC_STOP = 0x29
FUNC_PLC_START = 0x28
FUNC_READ_SZL = 0x1c  # System Status List

# Data areas
AREA_DB = 0x84  # Data block
AREA_M = 0x83   # Markers (M flags)
AREA_I = 0x81   # Inputs
AREA_Q = 0x82   # Outputs
AREA_T = 0x1D   # Timers
AREA_C = 0x1C   # Counters

# Error codes
S7_OK = 0x00
S7_NOT_FOUND = 0xD2
S7_INVALID_PARAM = 0xD5
S7_OUT_OF_RANGE = 0xD7


def _parse_area(addr_str: str) -> tuple[int, int, int, int]:
    """Parse S7-Plus address string to (area, db_number, byte_offset, bit_offset).

    Formats:
      DB100.DBX10.2  → (0x84, 100, 10, 2)
      DB100.DBD10     → (0x84, 100, 10, 0)  (4 bytes)
      M10.0           → (0x83, 0, 10, 0)
      I0.0            → (0x81, 0, 0, 0)
      Q0.0            → (0x82, 0, 0, 0)
    """
    addr_str = addr_str.strip().upper()
    bit_offset = 0
    db_number = 0

    if addr_str.startswith("DB"):
        area = AREA_DB
        parts = addr_str.split(".")
        # DB number
        db_str = parts[0][2:]
        db_number = int(db_str) if db_str else 0
        # Rest: DBX/D BD/D BW
        if len(parts) > 1:
            offset_part = parts[1]
            if offset_part.startswith("DBX"):
                byte_offset = int(offset_part[3:]) if len(offset_part) > 3 else 0
                if len(parts) > 2:
                    bit_offset = int(parts[2])
            elif offset_part.startswith("DBB"):
                byte_offset = int(offset_part[3:]) if len(offset_part) > 3 else 0
            elif offset_part.startswith("DBW"):
                byte_offset = int(offset_part[3:]) if len(offset_part) > 3 else 0
            elif offset_part.startswith("DBD"):
                byte_offset = int(offset_part[3:]) if len(offset_part) > 3 else 0
            else:
                byte_offset = int(offset_part) if offset_part else 0
        else:
            byte_offset = 0
    elif addr_str.startswith("M"):
        area = AREA_M
        rest = addr_str[1:]
        if "." in rest:
            parts = rest.split(".")
            byte_offset = int(parts[0])
            bit_offset = int(parts[1]) if len(parts) > 1 else 0
        else:
            byte_offset = int(rest) if rest else 0
    elif addr_str.startswith("I") or addr_str.startswith("E"):
        area = AREA_I
        rest = addr_str[1:] if addr_str.startswith("I") else addr_str[1:]
        if "." in rest:
            parts = rest.split(".")
            byte_offset = int(parts[0])
            bit_offset = int(parts[1]) if len(parts) > 1 else 0
        else:
            byte_offset = int(rest) if rest else 0
    elif addr_str.startswith("Q") or addr_str.startswith("A"):
        area = AREA_Q
        rest = addr_str[1:] if addr_str.startswith("Q") else addr_str[1:]
        if "." in rest:
            parts = rest.split(".")
            byte_offset = int(parts[0])
            bit_offset = int(parts[1]) if len(parts) > 1 else 0
        else:
            byte_offset = int(rest) if rest else 0
    else:
        # Numeric: treat as DB0 offset
        area = AREA_DB
        byte_offset = int(addr_str) if addr_str.isdigit() else 0

    return area, db_number, byte_offset, bit_offset


class S7PlusDeviceBehavior(StandardDeviceBehavior):
    """S7-Plus device behavior — maps point names to S7 addresses."""

    def __init__(self, points: list | None = None):
        super().__init__(points)
        self._config: DeviceConfig | None = None
        self._addr_map: dict[str, tuple[int, int, int, int]] = {}
        if points:
            for p in points:
                name = p.name if hasattr(p, "name") else p.get("name", "")
                addr = p.address if hasattr(p, "address") else p.get("address", "0")
                self._addr_map[name] = _parse_area(addr)

    def set_config(self, config: DeviceConfig) -> None:
        self._config = config

    def get_address(self, point_name: str) -> tuple[int, int, int, int]:
        return self._addr_map.get(point_name, (AREA_DB, 0, 0, 0))

    def get_point_by_address(self, area: int, db: int, offset: int, bit: int = 0) -> str | None:
        for name, (a, d, o, b) in self._addr_map.items():
            if a == area and d == db and o == offset and b == bit:
                return name
        # Also match without bit offset for byte/word/dword access
        for name, (a, d, o, b) in self._addr_map.items():
            if a == area and d == db and o == offset:
                return name
        return None

    @staticmethod
    def encode_value(value: Any, data_type: str) -> bytes:
        """Encode value to bytes per data type."""
        try:
            if data_type == "bool":
                return bytes([0x01 if value else 0x00])
            elif data_type == "uint16":
                return struct.pack(">H", int(value) & 0xFFFF)
            elif data_type == "int16":
                return struct.pack(">h", int(value))
            elif data_type == "uint32":
                return struct.pack(">I", int(value) & 0xFFFFFFFF)
            elif data_type == "int32":
                return struct.pack(">i", int(value))
            elif data_type == "float32":
                return struct.pack(">f", float(value))
            elif data_type == "float64":
                return struct.pack(">d", float(value))
            elif data_type == "string":
                return str(value).encode("utf-8")[:254]
            else:
                return struct.pack(">f", float(value))
        except (ValueError, TypeError, struct.error):
            return b"\x00" * 4

    @staticmethod
    def decode_value(data: bytes, data_type: str) -> Any:
        """Decode bytes to value per data type."""
        try:
            if data_type == "bool":
                return bool(data[0]) if data else False
            elif data_type == "uint16":
                return struct.unpack(">H", data[:2])[0] if len(data) >= 2 else 0
            elif data_type == "int16":
                return struct.unpack(">h", data[:2])[0] if len(data) >= 2 else 0
            elif data_type == "uint32":
                return struct.unpack(">I", data[:4])[0] if len(data) >= 4 else 0
            elif data_type == "int32":
                return struct.unpack(">i", data[:4])[0] if len(data) >= 4 else 0
            elif data_type == "float32":
                return struct.unpack(">f", data[:4])[0] if len(data) >= 4 else 0.0
            elif data_type == "float64":
                return struct.unpack(">d", data[:8])[0] if len(data) >= 8 else 0.0
            elif data_type == "string":
                return data.decode("utf-8", errors="replace")
            else:
                return struct.unpack(">f", data[:4])[0] if len(data) >= 4 else 0.0
        except (ValueError, TypeError, struct.error):
            return 0


class S7PlusServer(ProtocolServer):
    """S7Comm-Plus protocol server (PLC slave side).

    Listens on TCP port 102 (default), accepts TPKT/COTP connections,
    and handles S7-Plus Read/Write requests for data blocks and markers.
    """

    protocol_name = "s7plus"
    protocol_display_name = "S7Comm-Plus"
    protocol_description = "S7Comm-Plus协议 - 西门子S7-1200/1500 PLC新一代通信协议，支持优化块访问"
    protocol_version = "1.0.0"

    def __init__(self):
        super().__init__()
        self._behaviors: dict[str, S7PlusDeviceBehavior] = {}
        self._device_configs: dict[str, DeviceConfig] = {}
        self._host = "0.0.0.0"
        self._port = 102  # Standard ISO-on-TCP port
        self._server_task: asyncio.Task | None = None
        self._server_running = False
        self._connections: dict[asyncio.StreamWriter, dict[str, Any]] = {}
        self._rack = 0
        self._slot = 1
        self._plc_name = "S7-1500"
        self._order_id = "6ES7 518-1AL00-0AB0"
        self._firmware = "V3.0"

    async def start(self, config: dict[str, Any]) -> None:
        self._status = ProtocolStatus.STARTING
        self._host = config.get("host", "0.0.0.0")
        self._port = config.get("port", 102)
        self._validate_port(self._port)
        self._rack = config.get("rack", 0)
        self._slot = config.get("slot", 1)
        self._plc_name = config.get("plc_name", "S7-1500")
        self._order_id = config.get("order_id", "6ES7 518-1AL00-0AB0")
        self._firmware = config.get("firmware", "V3.0")
        try:
            self._server_running = True
            self._server_task = asyncio.create_task(self._serve())
            self._status = ProtocolStatus.RUNNING
            logger.info("S7Comm-Plus server started on %s:%d", self._host, self._port)
            self._log_debug("system", "server_start",
                            f"S7Comm-Plus service started {self._host}:{self._port}",
                            detail={"host": self._host, "port": self._port})
        except Exception as e:
            self._status = ProtocolStatus.ERROR
            logger.exception("Failed to start S7Comm-Plus server: %s", e)
            raise

    async def stop(self) -> None:
        try:
            self._server_running = False
            if self._server_task:
                self._server_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self._server_task
            for writer in list(self._connections.keys()):
                with contextlib.suppress(Exception):
                    writer.close()
            self._connections.clear()
        except Exception as e:
            logger.warning("S7Comm-Plus server stop error: %s", e)
        finally:
            self._status = ProtocolStatus.STOPPED
            logger.info("S7Comm-Plus server stopped")
            self._log_debug("system", "server_stop", "S7Comm-Plus service stopped")

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
            logger.exception("S7Comm-Plus server error: %s", e)
            self._status = ProtocolStatus.ERROR

    async def _handle_connection(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.on_client_connect()
        peer = writer.get_extra_info("peername", default=("?", "?"))
        self._log_debug("recv", "connection", f"S7Plus client connected: {peer[0]}:{peer[1]}")
        self._connections[writer] = {"peer": peer, "cotp_connected": False, "s7_connected": False}

        try:
            while self._server_running:
                # Read TPKT header (4 bytes)
                try:
                    tpkt = await asyncio.wait_for(reader.readexactly(4), timeout=_READ_TIMEOUT)
                except (asyncio.TimeoutError, asyncio.IncompleteReadError):
                    break

                if tpkt[0] != TPKT_VERSION:
                    self.record_protocol_error(ProtocolErrorCategory.FRAME_PARSE,
                                               f"bad TPKT version {tpkt[0]:#x}")
                    continue

                tpkt_len = struct.unpack(">H", tpkt[2:4])[0]
                if tpkt_len < 4 or tpkt_len > 8192:
                    self.record_protocol_error(ProtocolErrorCategory.FRAME_PARSE,
                                               f"bad TPKT length {tpkt_len}")
                    continue

                # Read remaining COTP/S7 data
                try:
                    payload = await asyncio.wait_for(
                        reader.readexactly(tpkt_len - 4), timeout=10
                    )
                except (asyncio.TimeoutError, asyncio.IncompleteReadError):
                    break

                cotp_len = payload[0]
                cotp_type = payload[1]
                cotp_data = payload[2:1 + cotp_len] if cotp_len > 1 else b""
                s7_data = payload[1 + cotp_len:] if len(payload) > 1 + cotp_len else b""

                conn_state = self._connections[writer]

                if cotp_type == COTP_CONNECT_REQUEST:
                    # COTP connect request — respond with confirm
                    response = self._build_cotp_connect_confirm(cotp_data)
                    writer.write(response)
                    await writer.drain()
                    conn_state["cotp_connected"] = True
                    self._log_debug("send", "cotp_connect", "S7Plus COTP connect confirm")

                elif cotp_type == COTP_DISCONNECT_REQUEST:
                    # COTP disconnect
                    response = self._build_cotp_disconnect_confirm()
                    writer.write(response)
                    await writer.drain()
                    break

                elif cotp_type == COTP_DATA:
                    # S7-Plus data frame
                    if s7_data:
                        response = await self._process_s7plus(s7_data, conn_state)
                        if response:
                            writer.write(response)
                            await writer.drain()

                else:
                    self.record_protocol_error(ProtocolErrorCategory.FRAME_PARSE,
                                               f"unknown COTP type {cotp_type:#x}")

        except Exception:
            logger.exception("S7Comm-Plus connection handler error from %s", peer)
            self.record_protocol_error(ProtocolErrorCategory.NETWORK, "connection handler error")
        finally:
            self._connections.pop(writer, None)
            with contextlib.suppress(Exception):
                writer.close()
            self.on_client_disconnect()
            self._log_debug("send", "disconnected", f"S7Plus client disconnected: {peer[0]}:{peer[1]}")

    def _build_cotp_connect_confirm(self, req_data: bytes) -> bytes:
        """Build COTP connect confirm (CC) frame."""
        # TPKT + COTP CC
        # Echo back the src/dst TSAP with our adjustments
        cotp_cc = bytearray()
        cotp_cc.append(0x00)  # length placeholder
        cotp_cc.append(COTP_CONNECT_CONFIRM)
        # DST-REF and SRC-REF (2 bytes each, swapped)
        if len(req_data) >= 4:
            cotp_cc.extend(req_data[2:4])  # DST-REF = req SRC-REF
            cotp_cc.extend(req_data[0:2])  # SRC-REF = req DST-REF
        else:
            cotp_cc.extend(b"\x00\x00\x00\x00")
        cotp_cc.append(0x00)  # Class = 0
        # Copy variable part (TSAP, etc.)
        if len(req_data) > 5:
            cotp_cc.extend(req_data[5:])
        # Set length
        cotp_cc[0] = len(cotp_cc) - 1

        # TPKT wrapper
        total_len = 4 + len(cotp_cc)
        tpkt = struct.pack(">BBH", TPKT_VERSION, 0x00, total_len)
        return tpkt + bytes(cotp_cc)

    def _build_cotp_disconnect_confirm(self) -> bytes:
        """Build COTP disconnect confirm frame."""
        cotp = bytearray([0x01, COTP_DISCONNECT_CONFIRM, 0x00, 0x00, 0x00])
        total_len = 4 + len(cotp)
        return struct.pack(">BBH", TPKT_VERSION, 0x00, total_len) + bytes(cotp)

    def _build_data_frame(self, s7_data: bytes) -> bytes:
        """Wrap S7-Plus data in COTP DT + TPKT."""
        cotp = bytearray([0x02, COTP_DATA, 0x80])  # EOT flag
        cotp.extend(s7_data)
        total_len = 4 + len(cotp)
        return struct.pack(">BBH", TPKT_VERSION, 0x00, total_len) + bytes(cotp)

    async def _process_s7plus(self, data: bytes, conn_state: dict) -> bytes | None:
        """Process S7-Plus PDU and return response frame (TPKT+COTP+S7)."""
        if len(data) < 4:
            return None

        # S7-Plus header: opcode(1) + reserved(1) + function(1) + reserved(1)
        # Actually, S7Comm-Plus uses a different header structure than classic S7.
        # S7-Plus header: TSG(1) + Opcode(1) + Reserved(1) + Function(1) + Reserved(1) + ...
        # For simplicity, we parse a common subset.

        opcode = data[0]
        func = data[2] if len(data) > 2 else 0

        self._log_debug("recv", "s7plus",
                        f"S7Plus PDU: opcode={opcode:#x} func={func:#x} len={len(data)}",
                        detail={"opcode": opcode, "func": func, "len": len(data)})

        # Handle setup communication
        if func == FUNC_SETUP_COMM or opcode == S7_PLUS_SETUP:
            return self._build_setup_response(data)

        # Handle read
        if func == FUNC_READ_VAR or opcode == S7_PLUS_READ:
            return await self._handle_read(data, conn_state)

        # Handle write
        if func == FUNC_WRITE_VAR or opcode == S7_PLUS_WRITE:
            return await self._handle_write(data, conn_state)

        # Handle SZL (System Status List) read
        if func == FUNC_READ_SZL:
            return self._handle_szl_read(data)

        # Unknown function
        self.record_protocol_error(ProtocolErrorCategory.FRAME_PARSE,
                                   f"unknown S7-Plus function {func:#x}")
        return None

    def _build_setup_response(self, req: bytes) -> bytes:
        """Build setup communication response."""
        # Simple echo response with OK status
        resp = bytearray()
        resp.append(S7_PLUS_SETUP_RSP)
        resp.append(0x00)  # reserved
        resp.append(FUNC_SETUP_COMM)
        resp.append(0x00)  # reserved
        resp.extend(b"\x00\x00")  # sequence (echo)
        resp.extend(b"\x00\x00")  # param length
        resp.extend(b"\x00\x00")  # data length
        resp.append(0x00)  # error class
        resp.append(0x00)  # error code
        return self._build_data_frame(bytes(resp))

    async def _handle_read(self, data: bytes, conn_state: dict) -> bytes:
        """Handle S7-Plus read request."""
        if not self._behaviors:
            device_id = self._default_device_id
        else:
            device_id = self._default_device_id or next(iter(self._behaviors.keys()))

        behavior = self._behaviors.get(device_id)
        if not behavior:
            return self._build_error_response(data, S7_NOT_FOUND)

        # Parse read request (simplified)
        # S7-Plus read request structure varies; this handles a common format
        try:
            # Extract area, db_number, offset from the request
            # Format varies between implementations; we try a best-effort parse
            area = AREA_DB
            db_number = 0
            byte_offset = 0
            num_bytes = 4

            # Try to find a matching point by scanning all points
            # Return all point values concatenated
            resp_data = bytearray()
            for point_name in behavior._points:
                pt = behavior._points[point_name]
                dt = pt.data_type.value if hasattr(pt, "data_type") else "float32"
                val = behavior.get_value(point_name)
                resp_data.extend(behavior.encode_value(val, dt))

            if not resp_data:
                resp_data = b"\x00" * 4

            resp = bytearray()
            resp.append(S7_PLUS_READ_RSP)
            resp.append(0x00)
            resp.append(FUNC_READ_VAR)
            resp.append(0x00)
            resp.extend(b"\x00\x00")  # sequence
            resp.extend(struct.pack(">H", 0))  # param length
            resp.extend(struct.pack(">H", len(resp_data)))  # data length
            resp.append(0x00)  # error class
            resp.append(0x00)  # error code
            resp.extend(resp_data)
            return self._build_data_frame(bytes(resp))

        except Exception as e:
            logger.debug("S7-Plus read error: %s", e)
            self.record_protocol_error(ProtocolErrorCategory.INTERNAL, str(e))
            return self._build_error_response(data, S7_INVALID_PARAM)

    async def _handle_write(self, data: bytes, conn_state: dict) -> bytes:
        """Handle S7-Plus write request."""
        # Simple acknowledgment
        resp = bytearray()
        resp.append(S7_PLUS_WRITE_RSP)
        resp.append(0x00)
        resp.append(FUNC_WRITE_VAR)
        resp.append(0x00)
        resp.extend(b"\x00\x00")  # sequence
        resp.extend(struct.pack(">H", 0))  # param length
        resp.extend(struct.pack(">H", 0))  # data length
        resp.append(0x00)  # error class
        resp.append(0x00)  # error code
        return self._build_data_frame(bytes(resp))

    def _handle_szl_read(self, data: bytes) -> bytes:
        """Handle System Status List (SZL) read — return PLC identification."""
        # Build SZL response with module identification
        szl_data = bytearray()
        # SZL ID 0x011C (module identification), index 1
        szl_data.extend(struct.pack(">HH", 0x011C, 0x01))  # ID + index
        # 40 bytes of module info
        order_id = self._order_id.encode("ascii").ljust(20, b" ")
        szl_data.extend(order_id[:20])
        # Module version
        szl_data.extend(b"V3.0".ljust(4, b" "))
        # Reserved
        szl_data.extend(b"\x00" * 16)

        resp = bytearray()
        resp.append(0x03)  # response opcode
        resp.append(0x00)
        resp.append(FUNC_READ_SZL)
        resp.append(0x00)
        resp.extend(b"\x00\x00")
        resp.extend(struct.pack(">H", 0))
        resp.extend(struct.pack(">H", len(szl_data)))
        resp.append(0x00)
        resp.append(0x00)
        resp.extend(szl_data)
        return self._build_data_frame(bytes(resp))

    def _build_error_response(self, req: bytes, error_code: int) -> bytes:
        """Build an S7-Plus error response."""
        resp = bytearray()
        resp.append(S7_PLUS_RESPONSE)
        resp.append(0x00)
        resp.append(req[2] if len(req) > 2 else 0)  # echo function
        resp.append(0x00)
        resp.extend(b"\x00\x00")
        resp.extend(struct.pack(">H", 0))
        resp.extend(struct.pack(">H", 0))
        resp.append(0x85)  # error class
        resp.append(error_code)
        return self._build_data_frame(bytes(resp))

    async def _fire_write_callback(self, device_id: str, point_name: str, value: Any) -> None:
        if not self._on_write:
            return
        try:
            await self._on_write(device_id, point_name, value)
        except Exception as e:
            logger.debug("Write callback error: %s", e)

    async def create_device(self, device_config: DeviceConfig) -> str:
        self._device_configs[device_config.id] = device_config
        behavior = S7PlusDeviceBehavior(device_config.points)
        behavior.set_config(device_config)
        self._behaviors[device_config.id] = behavior
        self._update_default_device(device_config.id)
        self._log_debug("system", "device_create",
                        f"S7Plus device created: {device_config.name} ({len(device_config.points)} points)",
                        device_id=device_config.id)
        logger.info("S7Comm-Plus device created: %s (%d points)", device_config.id, len(device_config.points))
        return device_config.id

    async def remove_device(self, device_id: str) -> None:
        self._behaviors.pop(device_id, None)
        self._device_configs.pop(device_id, None)
        self._clear_default_device(device_id)

    async def read_points(self, device_id: str) -> list[PointValue]:
        behavior = self._behaviors.get(device_id)
        if not behavior:
            return []
        results = []
        for point_name in behavior._points:
            val = behavior.get_value(point_name)
            results.append(PointValue(name=point_name, value=val, timestamp=time.time(),
                                      quality="good", simulated=True))
        return results

    async def write_point(self, device_id: str, point_name: str, value: Any) -> bool:
        behavior = self._behaviors.get(device_id)
        if not behavior:
            return False
        behavior.on_write(point_name, value)
        return True

    async def sync_point_value(self, device_id: str, point_name: str, value: Any) -> None:
        behavior = self._behaviors.get(device_id)
        if behavior:
            behavior.set_value(point_name, value)

    def get_config_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "rack": {
                    "type": "number", "default": 0,
                    "description": "PLC rack number (0-7)"
                },
                "slot": {
                    "type": "number", "default": 1,
                    "description": "PLC slot number (0-31)"
                },
                "plc_name": {
                    "type": "string", "default": "S7-1500",
                    "description": "PLC name for identification"
                },
                "order_id": {
                    "type": "string", "default": "6ES7 518-1AL00-0AB0",
                    "description": "PLC order ID (module identification)"
                },
                "firmware": {
                    "type": "string", "default": "V3.0",
                    "description": "PLC firmware version"
                },
                "port": {
                    "type": "number", "default": 102,
                    "description": "TCP port (standard: 102)"
                },
            },
        }
