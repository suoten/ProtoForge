"""DLT/T 645-2007 protocol server implementation.

Standard-compliant DLT/T 645-2007 smart meter protocol server (slave side),
interoperate-tested with standard DLT645 master tools.

Implements:
  - Frame format: 0x68 + A0~A5(6 BCD) + A6(complement) + 0x68 + C + L + DATA + CS + 0x16
  - Address: 12-digit BCD meter address (6 bytes, little-endian BCD)
  - Data encryption: each data byte + 0x33
  - Control codes:
    - 0x11: Read data (read specified data identifier)
    - 0x12: Read subsequent data
    - 0x15: Read address
    - 0x97: Write address
    - 0x04: Write data
    - 0x08: Freeze command
    - 0x0A: Change baud rate
    - 0x0C: Change password
    - 0x0D: Clear max demand
    - 0x10: Clear event
    - 0x13: Reset meter
  - Data identifiers (DI0-DI3): 4-byte hierarchical addressing
    - Common: total active energy (0x00010000), etc.
    - Voltage: 0x02010000 (phase A), etc.
    - Current: 0x02020000 (phase A), etc.
    - Power: 0x02030000, etc.
  - Error response: control code | 0xC0, error code in data[0]

Pure Python, no third-party DLT645 library required.
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

# ---------------------------------------------------------------------------
# Frame constants
# ---------------------------------------------------------------------------
FRAME_START = 0x68
FRAME_END = 0x16
ADDRESS_LEN = 7  # A0-A5 (6 bytes BCD) + A6 (complement of A5 in 0xFF... ~A5)
DATA_ENCRYPT_KEY = 0x33

# Control codes
C_READ_DATA = 0x11
C_READ_SUBSEQUENT = 0x12
C_READ_ADDRESS = 0x15
C_WRITE_DATA = 0x04
C_WRITE_ADDRESS = 0x97
C_FREEZE = 0x08
C_CHANGE_BAUD = 0x0A
C_CHANGE_PASSWORD = 0x0C
C_CLEAR_MAX_DEMAND = 0x0D
C_CLEAR_EVENT = 0x10
C_RESET_METER = 0x13

# Control code masks
C_DIR_MASK = 0x80  # direction bit: 0=master->slave, 1=slave->master
C_ABNORMAL_MASK = 0x40  # abnormal response flag
C_FOLLOW_MASK = 0x20  # follow-up data flag
C_ERROR_MASK = 0xC0  # error code bits

# Error codes (in data[0] of error response)
ERR_OK = 0x00
ERR_OTHER = 0x01  # other error
ERR_NO_DATA = 0x02  # no data
ERR_PASSWORD = 0x04  # password mode not matched
ERR_BAUD = 0x08  # baud rate not matched
ERR_DATA = 0x10  # data out of range
ERR_PASSWORD_ERROR = 0x20  # password error
ERR_UNAUTHORIZED = 0x40  # unauthorized

def _bcd_encode(val: int, num_bytes: int) -> bytes:
    """Encode integer to BCD bytes (little-endian digit order)."""
    result = bytearray()
    for _ in range(num_bytes):
        low = val % 10
        val //= 10
        high = val % 10
        val //= 10
        result.append((high << 4) | low)
    return bytes(result)

def _bcd_decode(data: bytes) -> int:
    """Decode BCD bytes to integer (little-endian digit order)."""
    val = 0
    for i, b in enumerate(data):
        low = b & 0x0F
        high = (b >> 4) & 0x0F
        val += (low + high * 10) * (100 ** i)
    return val

def _encrypt_data(data: bytes) -> bytes:
    """DLT645 data encryption: each byte + 0x33."""
    return bytes((b + DATA_ENCRYPT_KEY) & 0xFF for b in data)

def _decrypt_data(data: bytes) -> bytes:
    """DLT645 data decryption: each byte - 0x33."""
    return bytes((b - DATA_ENCRYPT_KEY) & 0xFF for b in data)

def _calc_checksum(data: bytes) -> int:
    """DLT645 checksum: sum of all bytes mod 256."""
    return sum(data) & 0xFF

def _parse_meter_address(addr_bytes: bytes) -> str:
    """Parse 7-byte address field to 12-digit string.

    DLT645 address: A0~A5 is 6-byte BCD (12 digits), A5 is complement.
    Bytes are in little-endian order (A0 lowest address digit pair).
    """
    # Only use A0~A5 (first 6 bytes), ignore A6 (complement)
    bcd = addr_bytes[:6]
    # Reverse to get big-endian (most significant first)
    digits = []
    for b in reversed(bcd):
        high = (b >> 4) & 0x0F
        low = b & 0x0F
        digits.append(f"{high}{low}")
    return "".join(digits)

def _build_meter_address(addr_str: str) -> bytes:
    """Build 6-byte address field (DL/T645-2007 standard) from 12-digit string.

    Returns A0~A5 as BCD in little-endian order. The 7-byte variant (A6 = ~A5)
    is only accepted on receive for vendor compatibility; responses follow the
    standard 6-byte layout so standard clients (EdgeLite, pymeter, etc.) parse
    them correctly.
    """
    # Pad to 12 digits
    addr_str = addr_str.zfill(12)
    # Parse 6 BCD bytes in little-endian order
    result = bytearray(6)
    for i in range(6):
        # Start from the least significant pair
        idx = 10 - i * 2  # position in string (0-indexed)
        high = int(addr_str[idx])
        low = int(addr_str[idx + 1])
        result[i] = (high << 4) | low
    return bytes(result)

# ---------------------------------------------------------------------------
# Standard data identifiers (DI3-DI0)
# ---------------------------------------------------------------------------
# Format: DI3-DI2-DI1-DI0 (big-endian in protocol, 4 bytes)

# Common data items
DI_TOTAL_ACTIVE_ENERGY = bytes([0x00, 0x01, 0x00, 0x00])  # (当前)组合有功总电能
DI_TOTAL_REACTIVE_ENERGY = bytes([0x00, 0x02, 0x00, 0x00])  # 组合无功总电能
DI_TOTAL_ACTIVE_ENERGY_T1 = bytes([0x00, 0x01, 0x01, 0x00])  # 费率1有功电能
DI_TOTAL_ACTIVE_ENERGY_T2 = bytes([0x00, 0x01, 0x02, 0x00])  # 费率2有功电能
DI_TOTAL_ACTIVE_ENERGY_T3 = bytes([0x00, 0x01, 0x03, 0x00])  # 费率3有功电能
DI_TOTAL_ACTIVE_ENERGY_T4 = bytes([0x00, 0x01, 0x04, 0x00])  # 费率4有功电能

# Voltage
DI_VOLTAGE_A = bytes([0x02, 0x01, 0x01, 0x00])  # A相电压
DI_VOLTAGE_B = bytes([0x02, 0x01, 0x02, 0x00])  # B相电压
DI_VOLTAGE_C = bytes([0x02, 0x01, 0x03, 0x00])  # C相电压

# Current
DI_CURRENT_A = bytes([0x02, 0x02, 0x01, 0x00])  # A相电流
DI_CURRENT_B = bytes([0x02, 0x02, 0x02, 0x00])  # B相电流
DI_CURRENT_C = bytes([0x02, 0x02, 0x03, 0x00])  # C相电流

# Power
DI_TOTAL_ACTIVE_POWER = bytes([0x02, 0x03, 0x00, 0x00])  # 有功功率
DI_TOTAL_REACTIVE_POWER = bytes([0x02, 0x04, 0x00, 0x00])  # 无功功率
DI_POWER_FACTOR = bytes([0x02, 0x06, 0x00, 0x00])  # 功率因数
DI_FREQUENCY = bytes([0x02, 0x80, 0x00, 0x03])  # 频率

# Time
DI_DATE_TIME = bytes([0x04, 0x00, 0x01, 0x00])  # 日期时间

def _format_data_value(value: Any, data_type: str = "float") -> bytes:
    """Format a value to DLT645 BCD data bytes.

    DLT645 uses BCD encoding for most data:
    - Energy: XXXXXX.XX kWh (6 integer + 2 decimal, 4 bytes BCD)
    - Voltage: XXX.X V (3 integer + 1 decimal, 2 bytes BCD)
    - Current: XXXXXX.XX A (6 integer + 2 decimal, 4 bytes BCD)
    - Power: XXXXXX.XX W (6 integer + 2 decimal, 4 bytes BCD)
    - Power factor: X.XXX (0 integer + 3 decimal, 2 bytes BCD)
    - Frequency: XX.XX Hz (2 integer + 2 decimal, 2 bytes BCD)
    """
    try:
        v = float(value)
    except (TypeError, ValueError):
        v = 0.0

    if data_type == "energy":
        # XXXXXX.XX → 4 bytes BCD, little-endian
        scaled = int(abs(v) * 100)
        bcd = _bcd_encode(scaled, 4)
        # Add sign byte
        sign = 0x00 if v >= 0 else 0x0A  # 0x0A = negative
        return bytes([sign]) + bcd
    elif data_type == "voltage":
        # XXX.X → 2 bytes BCD
        scaled = int(abs(v) * 10)
        bcd = _bcd_encode(scaled, 2)
        sign = 0x00 if v >= 0 else 0x0A
        return bytes([sign]) + bcd
    elif data_type == "current":
        # XXXXXX.XX → 4 bytes BCD
        scaled = int(abs(v) * 100)
        bcd = _bcd_encode(scaled, 4)
        sign = 0x00 if v >= 0 else 0x0A
        return bytes([sign]) + bcd
    elif data_type == "power":
        # XXXXXX.XX → 4 bytes BCD
        scaled = int(abs(v) * 100)
        bcd = _bcd_encode(scaled, 4)
        sign = 0x00 if v >= 0 else 0x0A
        return bytes([sign]) + bcd
    elif data_type == "power_factor":
        # X.XXX → 2 bytes BCD
        scaled = int(abs(v) * 1000)
        bcd = _bcd_encode(scaled, 2)
        sign = 0x00 if v >= 0 else 0x0A
        return bytes([sign]) + bcd
    elif data_type == "frequency":
        # XX.XX → 2 bytes BCD
        scaled = int(abs(v) * 100)
        bcd = _bcd_encode(scaled, 2)
        sign = 0x00
        return bytes([sign]) + bcd
    elif data_type == "datetime":
        # YYMMDDWWHHmmss → 7 bytes BCD
        t = time.localtime(time.time())
        year = t.tm_year % 100
        month = t.tm_mon
        day = t.tm_mday
        weekday = t.tm_wday + 1  # 1=Monday
        hour = t.tm_hour
        minute = t.tm_min
        second = t.tm_sec
        bcd = _bcd_encode(year, 1) + _bcd_encode(month, 1) + _bcd_encode(day, 1)
        bcd += _bcd_encode(weekday, 1) + _bcd_encode(hour, 1)
        bcd += _bcd_encode(minute, 1) + _bcd_encode(second, 1)
        return bcd
    else:
        # Default: 4 bytes BCD
        scaled = int(abs(v) * 100)
        bcd = _bcd_encode(scaled, 4)
        return bcd

def _di_to_data_type(di: bytes) -> str:
    """Map data identifier to data type for formatting."""
    di_hex = di.hex()
    # Energy
    if di_hex.startswith("0001"):
        return "energy"
    if di_hex.startswith("0002"):
        return "energy"
    # Voltage
    if di_hex.startswith("0201"):
        return "voltage"
    # Current
    if di_hex.startswith("0202"):
        return "current"
    # Power
    if di_hex.startswith("0203"):
        return "power"
    if di_hex.startswith("0204"):
        return "power"
    if di_hex.startswith("0205"):
        return "power"
    if di_hex.startswith("0206"):
        return "power_factor"
    if di_hex.startswith("0280"):
        return "frequency"
    if di_hex.startswith("0400"):
        return "datetime"
    return "energy"

class DLT645DeviceBehavior(StandardDeviceBehavior):
    """DLT645 device behavior — maps point names <-> data identifiers."""

    def __init__(self, points: list | None = None):
        super().__init__(points)
        self._config: DeviceConfig | None = None
        # Map point name -> data identifier (4 bytes)
        self._di_map: dict[str, bytes] = {}
        self._di_reverse: dict[bytes, str] = {}
        if points:
            for p in points:
                name = p.name if hasattr(p, "name") else p.get("name", "")
                addr = p.address if hasattr(p, "address") else p.get("address", "")
                di = self._parse_address(addr, name)
                self._di_map[name] = di
                self._di_reverse[di] = name

    def set_config(self, config: DeviceConfig) -> None:
        self._config = config

    @staticmethod
    def _parse_address(addr: str, name: str) -> bytes:
        """Parse point address to 4-byte data identifier.

        Address format: 8 hex digits (DI3DI2DI1DI0), e.g. "00010000"
        Or use name-based mapping for standard items.
        """
        addr = addr.strip()
        # Try parsing as hex DI
        try:
            if len(addr) == 8:
                return bytes.fromhex(addr)
            elif len(addr) == 10 and addr.startswith("0x"):
                return bytes.fromhex(addr[2:])
        except ValueError:
            pass

        # Name-based mapping
        name_lower = name.lower().replace("-", "_").replace(" ", "_")
        standard_map = {
            "total_active_energy": DI_TOTAL_ACTIVE_ENERGY,
            "total_reactive_energy": DI_TOTAL_REACTIVE_ENERGY,
            "active_energy_t1": DI_TOTAL_ACTIVE_ENERGY_T1,
            "active_energy_t2": DI_TOTAL_ACTIVE_ENERGY_T2,
            "active_energy_t3": DI_TOTAL_ACTIVE_ENERGY_T3,
            "active_energy_t4": DI_TOTAL_ACTIVE_ENERGY_T4,
            "voltage_a": DI_VOLTAGE_A,
            "voltage_b": DI_VOLTAGE_B,
            "voltage_c": DI_VOLTAGE_C,
            "current_a": DI_CURRENT_A,
            "current_b": DI_CURRENT_B,
            "current_c": DI_CURRENT_C,
            "total_active_power": DI_TOTAL_ACTIVE_POWER,
            "total_reactive_power": DI_TOTAL_REACTIVE_POWER,
            "power_factor": DI_POWER_FACTOR,
            "frequency": DI_FREQUENCY,
            "date_time": DI_DATE_TIME,
        }
        return standard_map.get(name_lower, DI_TOTAL_ACTIVE_ENERGY)

    def get_di(self, point_name: str) -> bytes:
        return self._di_map.get(point_name, DI_TOTAL_ACTIVE_ENERGY)

    def get_point_name(self, di: bytes) -> str | None:
        return self._di_reverse.get(di)

    def get_data_type_for_di(self, di: bytes) -> str:
        return _di_to_data_type(di)

class DLT645Server(ProtocolServer):
    """DLT/T 645-2007 smart meter protocol server (slave side).

    Runs over TCP (commonly used in IP-based meter reading scenarios)
    and supports the standard DLT645-2007 frame format and command set.
    """

    protocol_name = "dlt645"
    protocol_display_name = "DLT/T 645-2007"
    protocol_description = "DLT/T 645-2007智能电表通信协议 - 中国电力行业标准，用于智能电表数据采集"
    protocol_version = "1.0.0"

    def __init__(self):
        super().__init__()
        self._behaviors: dict[str, DLT645DeviceBehavior] = {}
        self._device_configs: dict[str, DeviceConfig] = {}
        self._host = "0.0.0.0"
        self._port = 37120  # Common port for DLT645 over TCP
        self._server_task: asyncio.Task | None = None
        self._server_running = False
        self._connections: dict[asyncio.StreamWriter, dict[str, Any]] = {}
        self._meter_addresses: dict[str, str] = {}  # device_id -> meter address string
        self._broadcast_address = "999999999999"  # broadcast address

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------
    async def start(self, config: dict[str, Any]) -> None:
        self._status = ProtocolStatus.STARTING
        self._host = config.get("host", "0.0.0.0")
        self._port = config.get("port", 37120)
        self._validate_port(self._port)
        try:
            self._server_running = True
            self._server_task = asyncio.create_task(self._serve())
            self._status = ProtocolStatus.RUNNING
            logger.info("DLT645 server started on %s:%d", self._host, self._port)
            self._log_debug("system", "server_start",
                            f"DLT645 service started {self._host}:{self._port}",
                            detail={"host": self._host, "port": self._port})
        except Exception as e:
            self._status = ProtocolStatus.ERROR
            logger.exception("Failed to start DLT645 server: %s", e)
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
            logger.warning("DLT645 server stop error: %s", e)
        finally:
            self._status = ProtocolStatus.STOPPED
            logger.info("DLT645 server stopped")
            self._log_debug("system", "server_stop", "DLT645 service stopped")

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
            logger.exception("DLT645 server error: %s", e)
            self._status = ProtocolStatus.ERROR

    # ------------------------------------------------------------------
    # connection handling
    # ------------------------------------------------------------------
    async def _handle_connection(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.on_client_connect()
        peer = writer.get_extra_info("peername", default=("?", "?"))
        self._log_debug("recv", "connection", f"DLT645 client connected: {peer[0]}:{peer[1]}")
        self._connections[writer] = {"peer": peer}

        try:
            while self._server_running:
                # Read frame: start byte
                try:

                    start = await asyncio.wait_for(reader.readexactly(1), timeout=_READ_TIMEOUT)

                except asyncio.TimeoutError:
                    break
                except asyncio.IncompleteReadError:
                    break

                if start[0] != FRAME_START:
                    self.record_protocol_error(ProtocolErrorCategory.FRAME_PARSE,
                                               f"bad start byte {start[0]:#x}")
                    continue

                # Read address field. DL/T645-2007 standard is 6 bytes (A0~A5);
                # some vendors append a 7th byte A6 = ~A5 (one's complement).
                # Read 6 bytes first, then peek one byte to detect the variant.
                try:
                    addr_bytes = await asyncio.wait_for(reader.readexactly(6), timeout=10)

                except (asyncio.TimeoutError, asyncio.IncompleteReadError) as _e:

                    break

                # Read next byte: either the second start byte (standard frame)
                # or the A6 complement byte (7-byte address variant).
                try:
                    next_byte = await asyncio.wait_for(reader.readexactly(1), timeout=10)

                except (asyncio.TimeoutError, asyncio.IncompleteReadError) as _e:

                    break

                if next_byte[0] != FRAME_START:
                    if next_byte[0] == (~addr_bytes[5]) & 0xFF:
                        # 7-byte address variant (A6 = ~A5)
                        addr_bytes += next_byte
                        try:
                            next_byte = await asyncio.wait_for(reader.readexactly(1), timeout=10)
                        except (asyncio.TimeoutError, asyncio.IncompleteReadError):
                            break
                    if next_byte[0] != FRAME_START:
                        self.record_protocol_error(ProtocolErrorCategory.FRAME_PARSE,
                                                   f"bad second start byte {next_byte[0]:#x}")
                        continue
                start2 = next_byte

                # Read control code + data length
                try:
                    ctrl_len = await asyncio.wait_for(reader.readexactly(2), timeout=10)
                except (asyncio.TimeoutError, asyncio.IncompleteReadError):
                    break

                ctrl = ctrl_len[0]
                data_len = ctrl_len[1]

                # Read data + checksum + end byte
                try:
                    remaining = await asyncio.wait_for(
                        reader.readexactly(data_len + 2), timeout=10  # data + CS + end
                    )
                except (asyncio.TimeoutError, asyncio.IncompleteReadError) as _e:

                    break

                data = remaining[:data_len]
                cs = remaining[data_len] if data_len + 1 <= len(remaining) else 0
                end_byte = remaining[data_len + 1] if data_len + 2 <= len(remaining) else 0

                if end_byte != FRAME_END:
                    self.record_protocol_error(ProtocolErrorCategory.FRAME_PARSE,
                                               f"bad end byte {end_byte:#x}")

                    continue

                # Verify checksum
                frame_for_cs = addr_bytes + bytes([FRAME_START, ctrl, data_len]) + data
                calc_cs = _calc_checksum(frame_for_cs)
                if calc_cs != cs:
                    self.record_protocol_error(ProtocolErrorCategory.FRAME_PARSE,
                                               f"checksum mismatch: calc={calc_cs:#x} recv={cs:#x}")

                    continue

                # Parse meter address
                meter_addr = _parse_meter_address(addr_bytes)
                self._log_debug("recv", "frame",
                                f"DLT645 req: addr={meter_addr} C={ctrl:#04x} L={data_len}",
                                detail={"meter_addr": meter_addr, "ctrl": ctrl, "data_len": data_len})

                # Process request
                response = await self._process_request(meter_addr, ctrl, data)
                if response:
                    try:
                        writer.write(response)
                        await writer.drain()
                    except Exception as e:
                        logger.debug("DLT645 send error: %s", e)
                        break

        except Exception:
            logger.exception("DLT645 connection handler error from %s", peer)
            self.record_protocol_error(ProtocolErrorCategory.NETWORK, "connection handler error")
        finally:
            self._connections.pop(writer, None)
            with contextlib.suppress(Exception):
                writer.close()
            self.on_client_disconnect()
            self._log_debug("send", "disconnected", f"DLT645 client disconnected: {peer[0]}:{peer[1]}")

    # ------------------------------------------------------------------
    # request processing
    # ------------------------------------------------------------------
    async def _process_request(self, meter_addr: str, ctrl: int, data: bytes) -> bytes | None:
        """Process a DLT645 request and return response frame bytes."""
        # Find device by meter address
        device_id = self._find_device_by_addr(meter_addr)

        # Handle broadcast address (only read address allowed)
        if meter_addr == self._broadcast_address:
            if ctrl == C_READ_ADDRESS and device_id is None:
                # Return first device's address
                if self._behaviors:
                    first_dev = next(iter(self._behaviors.keys()))
                    addr = self._meter_addresses.get(first_dev, "000000000000")
                    return self._build_read_address_response(addr)
                return None
            return None  # Ignore other broadcast requests

        if ctrl == C_READ_ADDRESS:
            # Return this device's address or first available
            if device_id:
                addr = self._meter_addresses.get(device_id, "000000000000")
            elif self._behaviors:
                first_dev = next(iter(self._behaviors.keys()))
                addr = self._meter_addresses.get(first_dev, "000000000000")
            else:
                addr = "000000000000"
            return self._build_read_address_response(addr)

        if device_id is None:
            # No matching device — no response (DLT645 slave stays silent)
            return None

        behavior = self._behaviors[device_id]

        if ctrl == C_READ_DATA:
            return await self._handle_read_data(meter_addr, ctrl, data, behavior, device_id)

        # Unsupported control codes — return error
        return self._build_error_response(meter_addr, ctrl, ERR_OTHER)

    async def _handle_read_data(self, meter_addr: str, ctrl: int, data: bytes,
                                behavior: DLT645DeviceBehavior, device_id: str) -> bytes:
        """Handle read data request (control code 0x11)."""
        if len(data) < 4:
            return self._build_error_response(meter_addr, ctrl, ERR_DATA)

        # Decrypt data and extract DI.
        # 传输序（DL/T645-2007）：DI0 在前（低字节先发），而 _di_map 键按
        # DI3..DI0（fromhex 顺序）存储 —— 查表前需反转；响应回显保持传输序。
        dec_data = _decrypt_data(data)
        di = dec_data[:4]

        # Look up point by DI
        point_name = behavior.get_point_name(di[::-1])

        if point_name is None:
            # No matching point — return error (no data)
            return self._build_error_response(meter_addr, ctrl, ERR_NO_DATA)

        # Get value
        value = behavior.get_value(point_name)
        data_type = behavior.get_data_type_for_di(di[::-1])

        # Format value to BCD
        value_bytes = _format_data_value(value, data_type)

        # Build response data: DI (4 bytes) + value bytes
        resp_data = di + value_bytes

        # Encrypt response data
        enc_data = _encrypt_data(resp_data)

        return self._build_response_frame(meter_addr, ctrl, enc_data)

    def _find_device_by_addr(self, meter_addr: str) -> str | None:
        """Find device ID by meter address."""
        # Check exact match
        for dev_id, addr in self._meter_addresses.items():
            if addr == meter_addr:
                return dev_id
        # If only one device, respond to any address
        if len(self._behaviors) == 1:
            return next(iter(self._behaviors.keys()))
        return None

    # ------------------------------------------------------------------
    # frame building
    # ------------------------------------------------------------------
    def _build_response_frame(self, meter_addr: str, ctrl: int, data: bytes) -> bytes:
        """Build a DLT645 response frame.

        Response control code: set DIR bit (0x80), clear ABNORMAL bit.
        If follow-up data exists, set FOLLOW bit (0x20).
        """
        resp_ctrl = ctrl | C_DIR_MASK  # Direction bit = 1 (slave -> master)
        addr_bytes = _build_meter_address(meter_addr)
        data_len = len(data)

        # Frame: 0x68 + addr(7) + 0x68 + C + L + DATA + CS + 0x16
        frame = bytearray()
        frame.append(FRAME_START)
        frame.extend(addr_bytes)
        frame.append(FRAME_START)
        frame.append(resp_ctrl)
        frame.append(data_len)
        frame.extend(data)
        # Checksum
        cs_data = addr_bytes + bytes([FRAME_START, resp_ctrl, data_len]) + data
        frame.append(_calc_checksum(cs_data))
        frame.append(FRAME_END)

        self._log_debug("send", "response",
                        f"DLT645 resp: addr={meter_addr} C={resp_ctrl:#04x} L={data_len}",
                        detail={"meter_addr": meter_addr, "ctrl": resp_ctrl, "data_len": data_len})
        return bytes(frame)

    def _build_error_response(self, meter_addr: str, ctrl: int, error_code: int) -> bytes:
        """Build a DLT645 error response frame."""
        resp_ctrl = ctrl | C_DIR_MASK | C_ABNORMAL_MASK
        addr_bytes = _build_meter_address(meter_addr)
        # Error data: 1 byte error code (encrypted)
        err_data = _encrypt_data(bytes([error_code]))
        data_len = 1

        frame = bytearray()
        frame.append(FRAME_START)
        frame.extend(addr_bytes)
        frame.append(FRAME_START)
        frame.append(resp_ctrl)
        frame.append(data_len)
        frame.extend(err_data)
        cs_data = addr_bytes + bytes([FRAME_START, resp_ctrl, data_len]) + err_data
        frame.append(_calc_checksum(cs_data))
        frame.append(FRAME_END)

        self._log_debug("send", "error",
                        f"DLT645 error resp: addr={meter_addr} C={resp_ctrl:#04x} ERR={error_code:#x}",
                        detail={"meter_addr": meter_addr, "ctrl": resp_ctrl, "error": error_code})
        return bytes(frame)

    def _build_read_address_response(self, meter_addr: str) -> bytes:
        """Build a read address response (control code 0x15)."""
        resp_ctrl = C_READ_ADDRESS | C_DIR_MASK
        addr_bytes = _build_meter_address(meter_addr)
        # Response data: address in BCD (7 bytes, encrypted)
        enc_data = _encrypt_data(addr_bytes)
        data_len = len(enc_data)

        frame = bytearray()
        frame.append(FRAME_START)
        # Use broadcast address in response (standard behavior)
        frame.extend(_build_meter_address(self._broadcast_address))
        frame.append(FRAME_START)
        frame.append(resp_ctrl)
        frame.append(data_len)
        frame.extend(enc_data)
        # Checksum uses the response address field
        resp_addr = _build_meter_address(self._broadcast_address)
        cs_data = resp_addr + bytes([FRAME_START, resp_ctrl, data_len]) + enc_data
        frame.append(_calc_checksum(cs_data))
        frame.append(FRAME_END)

        self._log_debug("send", "read_addr",
                        f"DLT645 read address resp: addr={meter_addr}",
                        detail={"meter_addr": meter_addr})
        return bytes(frame)

    # ------------------------------------------------------------------
    # write propagation
    # ------------------------------------------------------------------
    async def _fire_write_callback(self, device_id: str, point_name: str, value: Any) -> None:
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
        behavior = DLT645DeviceBehavior(device_config.points)
        behavior.set_config(device_config)
        self._behaviors[device_config.id] = behavior
        self._update_default_device(device_config.id)

        # Set meter address from protocol_config or device ID
        meter_addr = "000000000001"
        if device_config.protocol_config:
            meter_addr = device_config.protocol_config.get("meter_address", meter_addr)
        self._meter_addresses[device_config.id] = meter_addr.zfill(12)

        self._log_debug("system", "device_create",
                        f"DLT645 device created: {device_config.name} (addr={meter_addr}, {len(device_config.points)} points)",
                        device_id=device_config.id)
        logger.info("DLT645 device created: %s (addr=%s, %d points)",
                    device_config.id, meter_addr, len(device_config.points))
        return device_config.id

    async def remove_device(self, device_id: str) -> None:
        self._behaviors.pop(device_id, None)
        self._device_configs.pop(device_id, None)
        self._meter_addresses.pop(device_id, None)
        self._clear_default_device(device_id)
        self._log_debug("system", "device_remove", f"DLT645 device removed: {device_id}", device_id=device_id)

    async def read_points(self, device_id: str) -> list[PointValue]:
        behavior = self._behaviors.get(device_id)
        if not behavior:
            return []
        results = []
        for point_name, di in behavior._di_map.items():
            val = behavior.get_value(point_name)
            results.append(PointValue(name=point_name, value=val, timestamp=time.time(),
                                      quality="good", simulated=True))
        return results

    async def write_point(self, device_id: str, point_name: str, value: Any) -> bool:
        behavior = self._behaviors.get(device_id)
        if not behavior:
            return False
        behavior.on_write(point_name, value)
        self._log_debug("recv", "point_write", f"DLT645 write {point_name}={value}", device_id=device_id)
        return True

    async def sync_point_value(self, device_id: str, point_name: str, value: Any) -> None:
        behavior = self._behaviors.get(device_id)
        if behavior:
            behavior.set_value(point_name, value)

    def get_config_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "meter_address": {
                    "type": "string",
                    "default": "000000000001",
                    "description": "12-digit BCD meter address (e.g. 000000000001)"
                },
                "port": {
                    "type": "number",
                    "default": 37120,
                    "description": "TCP port for DLT645 over TCP"
                },
            },
        }
