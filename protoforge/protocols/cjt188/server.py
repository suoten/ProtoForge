"""CJ/T 188-2004 protocol server implementation.

CJ/T 188 is the Chinese industry standard for water/gas/heat meter data
transmission. It operates over RS-485 or TCP, using a simple frame format
similar to DLT645 but with different address and data encoding.

Frame format:
  Start(0x68) + Addr(7 bytes) + Ctrl(1) + DataLen(1) + Data(n) + CS(1) + End(0x16)
  Address: 7 bytes BCD (A0~A6), A0~A3 = meter serial, A4 = meter type, A5~A6 = mfr code

Meter types: 0=water, 1=hot water, 2=gas, 3=heat, 4=electric

Control codes:
  0x81: Read data (master->slave)
  0x81|0x80: Read data response (slave->master)
  0x82: Write data
  0x83: Read address
  0x84: Write address

Pure Python, no third-party library required.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from typing import Any

from protoforge.models.device import DeviceConfig, PointValue
from protoforge.protocols.behavior import ProtocolErrorCategory, ProtocolServer, ProtocolStatus, StandardDeviceBehavior

logger = logging.getLogger(__name__)

_READ_TIMEOUT = 120

FRAME_START = 0x68
FRAME_END = 0x16
ADDRESS_LEN = 7

# Meter types
METER_WATER = 0x00
METER_HOT_WATER = 0x01
METER_GAS = 0x02
METER_HEAT = 0x03
METER_ELECTRIC = 0x04

# Control codes
C_READ_DATA = 0x81
C_WRITE_DATA = 0x82
C_READ_ADDRESS = 0x83
C_WRITE_ADDRESS = 0x84

# Direction bit
DIR_SLAVE = 0x80  # set in response

# Error flags
ERR_FLAG = 0x40

# Standard data identifiers for CJ/T 188
# DI0: 0x90 = cumulative volume, 0x91 = current volume, etc.
DI_CUMULATIVE_VOLUME = 0x90
DI_CURRENT_VOLUME = 0x91
DI_FLOW_RATE = 0x92
DI_TEMPERATURE = 0x93
DI_PRESSURE = 0x94
DI_VOLTAGE = 0x95
DI_DATE_TIME = 0x96
DI_STATUS = 0x97


def _bcd_encode(val: float, num_bytes: int, decimal_places: int = 0) -> bytes:
    """Encode value to BCD bytes (little-endian digit order)."""
    scaled = int(abs(val) * (10 ** decimal_places))
    result = bytearray()
    for _ in range(num_bytes):
        low = scaled % 10
        scaled //= 10
        high = scaled % 10
        scaled //= 10
        result.append((high << 4) | low)
    return bytes(result)


def _encrypt_data(data: bytes) -> bytes:
    """CJ/T 188 data encryption: each byte + 0x33."""
    return bytes((b + 0x33) & 0xFF for b in data)


def _decrypt_data(data: bytes) -> bytes:
    """CJ/T 188 data decryption: each byte - 0x33."""
    return bytes((b - 0x33) & 0xFF for b in data)


def _calc_checksum(data: bytes) -> int:
    return sum(data) & 0xFF


def _parse_address(addr_bytes: bytes) -> str:
    """Parse 7-byte address to 14-digit hex string."""
    return addr_bytes[:7].hex().upper()


def _build_address(addr_str: str) -> bytes:
    """Build 7-byte address from 14-digit hex string."""
    addr_str = addr_str.ljust(14, "0")[:14]
    return bytes.fromhex(addr_str)


class CJT188DeviceBehavior(StandardDeviceBehavior):
    """CJ/T 188 device behavior."""

    def __init__(self, points: list | None = None):
        super().__init__(points)
        self._config: DeviceConfig | None = None
        self._di_map: dict[str, int] = {}
        self._di_reverse: dict[int, str] = {}
        if points:
            for p in points:
                name = p.name if hasattr(p, "name") else p.get("name", "")
                addr = p.address if hasattr(p, "address") else p.get("address", "")
                di = self._parse_di(addr, name)
                self._di_map[name] = di
                self._di_reverse[di] = name

    def set_config(self, config: DeviceConfig) -> None:
        self._config = config

    @staticmethod
    def _parse_di(addr: str, name: str) -> int:
        try:
            return int(addr, 0) if addr else DI_CUMULATIVE_VOLUME
        except (ValueError, TypeError):
            name_lower = name.lower().replace("-", "_").replace(" ", "_")
            std_map = {
                "cumulative_volume": DI_CUMULATIVE_VOLUME,
                "total_volume": DI_CUMULATIVE_VOLUME,
                "current_volume": DI_CURRENT_VOLUME,
                "flow_rate": DI_FLOW_RATE,
                "temperature": DI_TEMPERATURE,
                "pressure": DI_PRESSURE,
                "voltage": DI_VOLTAGE,
                "date_time": DI_DATE_TIME,
                "status": DI_STATUS,
            }
            return std_map.get(name_lower, DI_CUMULATIVE_VOLUME)

    def get_di(self, point_name: str) -> int:
        return self._di_map.get(point_name, DI_CUMULATIVE_VOLUME)

    def get_point_name(self, di: int) -> str | None:
        return self._di_reverse.get(di)

    @staticmethod
    def get_decimal_places(di: int) -> int:
        """Get decimal places for a data identifier."""
        return {DI_CUMULATIVE_VOLUME: 3, DI_CURRENT_VOLUME: 3, DI_FLOW_RATE: 3,
                DI_TEMPERATURE: 1, DI_PRESSURE: 2, DI_VOLTAGE: 1}.get(di, 2)

    @staticmethod
    def get_data_len(di: int) -> int:
        """Get data length in bytes for a data identifier."""
        return {DI_CUMULATIVE_VOLUME: 4, DI_CURRENT_VOLUME: 4, DI_FLOW_RATE: 3,
                DI_TEMPERATURE: 2, DI_PRESSURE: 2, DI_VOLTAGE: 2,
                DI_DATE_TIME: 6, DI_STATUS: 1}.get(di, 4)


class CJT188Server(ProtocolServer):
    """CJ/T 188-2004 meter protocol server (slave side).

    Supports water, gas, heat, and electric meter simulation over TCP.
    """

    protocol_name = "cjt188"
    protocol_display_name = "CJ/T 188-2004"
    protocol_description = "CJ/T 188水气热表传输协议 - 中国城建标准，用于水表/气表/热量表数据采集"
    protocol_version = "1.0.0"

    def __init__(self):
        super().__init__()
        self._behaviors: dict[str, CJT188DeviceBehavior] = {}
        self._device_configs: dict[str, DeviceConfig] = {}
        self._host = "0.0.0.0"
        self._port = 37121
        self._server_task: asyncio.Task | None = None
        self._server_running = False
        self._connections: dict[asyncio.StreamWriter, dict[str, Any]] = {}
        self._meter_addresses: dict[str, str] = {}
        self._meter_types: dict[str, int] = {}

    async def start(self, config: dict[str, Any]) -> None:
        self._status = ProtocolStatus.STARTING
        self._host = config.get("host", "0.0.0.0")
        self._port = config.get("port", 37121)
        self._validate_port(self._port)
        try:
            self._server_running = True
            self._server_task = asyncio.create_task(self._serve())
            self._status = ProtocolStatus.RUNNING
            logger.info("CJ/T 188 server started on %s:%d", self._host, self._port)
            self._log_debug("system", "server_start",
                            f"CJ/T 188 service started {self._host}:{self._port}",
                            detail={"host": self._host, "port": self._port})
        except Exception as e:
            self._status = ProtocolStatus.ERROR
            logger.exception("Failed to start CJ/T 188 server: %s", e)
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
            logger.warning("CJ/T 188 server stop error: %s", e)
        finally:
            self._status = ProtocolStatus.STOPPED
            logger.info("CJ/T 188 server stopped")
            self._log_debug("system", "server_stop", "CJ/T 188 service stopped")

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
            logger.exception("CJ/T 188 server error: %s", e)
            self._status = ProtocolStatus.ERROR

    async def _handle_connection(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.on_client_connect()
        peer = writer.get_extra_info("peername", default=("?", "?"))
        self._log_debug("recv", "connection", f"CJ/T 188 client connected: {peer[0]}:{peer[1]}")
        self._connections[writer] = {"peer": peer}

        try:
            while self._server_running:
                try:
                    start = await asyncio.wait_for(reader.readexactly(1), timeout=_READ_TIMEOUT)
                except (asyncio.TimeoutError, asyncio.IncompleteReadError):
                    break

                if start[0] != FRAME_START:
                    self.record_protocol_error(ProtocolErrorCategory.FRAME_PARSE,
                                               f"bad start byte {start[0]:#x}")
                    continue

                try:
                    addr_bytes = await asyncio.wait_for(reader.readexactly(ADDRESS_LEN), timeout=10)
                except (asyncio.TimeoutError, asyncio.IncompleteReadError):
                    break

                try:
                    ctrl_len = await asyncio.wait_for(reader.readexactly(2), timeout=10)
                except (asyncio.TimeoutError, asyncio.IncompleteReadError):
                    break

                ctrl = ctrl_len[0]
                data_len = ctrl_len[1]

                try:
                    remaining = await asyncio.wait_for(
                        reader.readexactly(data_len + 2), timeout=10
                    )
                except (asyncio.TimeoutError, asyncio.IncompleteReadError):
                    break

                data = remaining[:data_len]
                cs = remaining[data_len] if data_len < len(remaining) else 0
                end_byte = remaining[data_len + 1] if data_len + 1 < len(remaining) else 0

                if end_byte != FRAME_END:
                    self.record_protocol_error(ProtocolErrorCategory.FRAME_PARSE,
                                               f"bad end byte {end_byte:#x}")
                    continue

                frame_for_cs = addr_bytes + bytes([ctrl, data_len]) + data
                calc_cs = _calc_checksum(frame_for_cs)
                if calc_cs != cs:
                    self.record_protocol_error(ProtocolErrorCategory.FRAME_PARSE,
                                               f"checksum mismatch: calc={calc_cs:#x} recv={cs:#x}")
                    continue

                meter_addr = _parse_address(addr_bytes)
                self._log_debug("recv", "frame",
                                f"CJ/T 188 req: addr={meter_addr} C={ctrl:#04x} L={data_len}",
                                detail={"meter_addr": meter_addr, "ctrl": ctrl, "data_len": data_len})

                response = await self._process_request(meter_addr, ctrl, data)
                if response:
                    try:
                        writer.write(response)
                        await writer.drain()
                    except Exception as e:
                        logger.debug("CJ/T 188 send error: %s", e)
                        break

        except Exception:
            logger.exception("CJ/T 188 connection handler error from %s", peer)
            self.record_protocol_error(ProtocolErrorCategory.NETWORK, "connection handler error")
        finally:
            self._connections.pop(writer, None)
            with contextlib.suppress(Exception):
                writer.close()
            self.on_client_disconnect()
            self._log_debug("send", "disconnected", f"CJ/T 188 client disconnected: {peer[0]}:{peer[1]}")

    async def _process_request(self, meter_addr: str, ctrl: int, data: bytes) -> bytes | None:
        device_id = self._find_device_by_addr(meter_addr)

        if device_id is None:
            return None

        behavior = self._behaviors[device_id]

        if ctrl == C_READ_DATA:
            return await self._handle_read_data(meter_addr, ctrl, data, behavior, device_id)
        if ctrl == C_READ_ADDRESS:
            addr = self._meter_addresses.get(device_id, "00000000000000")
            return self._build_response(meter_addr, ctrl, _build_address(addr))

        return self._build_error_response(meter_addr, ctrl)

    async def _handle_read_data(self, meter_addr: str, ctrl: int, data: bytes,
                                behavior: CJT188DeviceBehavior, device_id: str) -> bytes:
        if len(data) < 1:
            return self._build_error_response(meter_addr, ctrl)

        dec_data = _decrypt_data(data)
        di = dec_data[0]

        point_name = behavior.get_point_name(di)
        if point_name is None:
            return self._build_error_response(meter_addr, ctrl)

        value = behavior.get_value(point_name)
        decimal_places = behavior.get_decimal_places(di)
        data_len = behavior.get_data_len(di)

        bcd = _bcd_encode(value, data_len, decimal_places)
        resp_data = bytes([di]) + bcd
        enc_data = _encrypt_data(resp_data)

        return self._build_response(meter_addr, ctrl, enc_data)

    def _find_device_by_addr(self, addr: str) -> str | None:
        for dev_id, a in self._meter_addresses.items():
            if a == addr:
                return dev_id
        if len(self._behaviors) == 1:
            return next(iter(self._behaviors.keys()))
        return None

    def _build_response(self, meter_addr: str, ctrl: int, data: bytes) -> bytes:
        resp_ctrl = ctrl | DIR_SLAVE
        addr_bytes = _build_address(meter_addr)
        data_len = len(data)

        frame = bytearray([FRAME_START])
        frame.extend(addr_bytes)
        frame.append(resp_ctrl)
        frame.append(data_len)
        frame.extend(data)
        cs_data = addr_bytes + bytes([resp_ctrl, data_len]) + data
        frame.append(_calc_checksum(cs_data))
        frame.append(FRAME_END)

        self._log_debug("send", "response",
                        f"CJ/T 188 resp: addr={meter_addr} C={resp_ctrl:#04x} L={data_len}")
        return bytes(frame)

    def _build_error_response(self, meter_addr: str, ctrl: int) -> bytes:
        resp_ctrl = ctrl | DIR_SLAVE | ERR_FLAG
        addr_bytes = _build_address(meter_addr)
        data = bytes([0x01])  # generic error
        data_len = 1

        frame = bytearray([FRAME_START])
        frame.extend(addr_bytes)
        frame.append(resp_ctrl)
        frame.append(data_len)
        frame.extend(data)
        cs_data = addr_bytes + bytes([resp_ctrl, data_len]) + data
        frame.append(_calc_checksum(cs_data))
        frame.append(FRAME_END)

        return bytes(frame)

    async def _fire_write_callback(self, device_id: str, point_name: str, value: Any) -> None:
        if not self._on_write:
            return
        try:
            await self._on_write(device_id, point_name, value)
        except Exception as e:
            logger.debug("Write callback error: %s", e)

    async def create_device(self, device_config: DeviceConfig) -> str:
        self._device_configs[device_config.id] = device_config
        behavior = CJT188DeviceBehavior(device_config.points)
        behavior.set_config(device_config)
        self._behaviors[device_config.id] = behavior
        self._update_default_device(device_config.id)

        meter_addr = "00000000000000"
        meter_type = METER_WATER
        if device_config.protocol_config:
            meter_addr = device_config.protocol_config.get("meter_address", meter_addr)
            meter_type = device_config.protocol_config.get("meter_type", meter_type)
        self._meter_addresses[device_config.id] = meter_addr
        self._meter_types[device_config.id] = meter_type

        self._log_debug("system", "device_create",
                        f"CJ/T 188 device created: {device_config.name} (addr={meter_addr})",
                        device_id=device_config.id)
        logger.info("CJ/T 188 device created: %s (addr=%s)", device_config.id, meter_addr)
        return device_config.id

    async def remove_device(self, device_id: str) -> None:
        self._behaviors.pop(device_id, None)
        self._device_configs.pop(device_id, None)
        self._meter_addresses.pop(device_id, None)
        self._meter_types.pop(device_id, None)
        self._clear_default_device(device_id)

    async def read_points(self, device_id: str) -> list[PointValue]:
        behavior = self._behaviors.get(device_id)
        if not behavior:
            return []
        results = []
        for point_name in behavior._di_map:
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
                "meter_address": {
                    "type": "string", "default": "00000000000000",
                    "description": "14-digit hex meter address"
                },
                "meter_type": {
                    "type": "number", "default": 0,
                    "description": "Meter type: 0=water, 1=hot water, 2=gas, 3=heat, 4=electric"
                },
                "port": {
                    "type": "number", "default": 37121,
                    "description": "TCP port"
                },
            },
        }
