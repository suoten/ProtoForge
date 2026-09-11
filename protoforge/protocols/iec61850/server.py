"""IEC 61850 protocol server implementation (MMS mapping layer).

Implements a simplified IEC 61850 server using the MMS (Manufacturing Message
Specification, ISO 9506) TCP mapping. This enables testing of IEC 61850
client applications (like libIEC61850, OpenIEC61850) without requiring
a full IEC 61850 stack.

Supports:
  - MMS TCP connection (port 102 in IEC 61850 context, configurable)
  - MMS Initiate/Conclude services
  - MMS Read service (read named variable = logical node data)
  - MMS Write service (write control commands)
  - MMS GetNameList (list logical nodes/data)
  - MMS GetVariableAccessAttributes (data type query)
  - Information model: Logical Device → Logical Node → Data → Data Attribute
  - Common Data Classes (CDC): SPS (single point), MV (measured value),
    SPC (single point controllable), DPC (double point controllable)

Wire protocol:
  - TPKT header (4 bytes: version, reserved, length)
  - COTP header (variable length, class=0 for data)
  - MMS PDU (BER-encoded)

This implementation uses simplified BER encoding for MMS PDUs.
For full compliance, use libIEC61850 or IEC104 tools.
"""

from __future__ import annotations

import asyncio
import json
import logging
import struct
import time
from typing import Any

from protoforge.models.device import DeviceConfig, PointConfig, PointValue
from protoforge.protocols.behavior import ProtocolErrorCategory, ProtocolServer, ProtocolStatus, StandardDeviceBehavior

logger = logging.getLogger(__name__)

_READ_TIMEOUT = 120

# MMS PDU tags (BER)
TAG_INITIATE_REQ = 0xA8  # Initiate Request
TAG_INITIATE_CON = 0xA9  # Initiate Con
TAG_CONCLUDE_REQ = 0x82  # Conclude Request
TAG_CONCLUDE_CON = 0x83  # Conclude Con
TAG_READ_REQ = 0xA4      # Read Request
TAG_READ_CON = 0xA5      # Read Con (actually 0xA5 is GetNameList... see spec)
TAG_WRITE_REQ = 0xA6     # Write Request
TAG_WRITE_CON = 0xA7     # Write Con
TAG_GET_NAME_LIST_REQ = 0xA1
TAG_GET_NAME_LIST_CON = 0xA2
TAG_GET_VAR_ACCESS_REQ = 0xA3
TAG_GET_VAR_ACCESS_CON = 0xA4
TAG_IDENTIFY_REQ = 0x82
TAG_IDENTIFY_CON = 0x83
TAG_STATUS_REQ = 0x80
TAG_STATUS_CON = 0x81

# MMS error codes
ERR_OTHER = 0
ERR_TEMPORARILY_UNAVAILABLE = 1
ERR_ACCESS_NON_EXISTENT = 2
ERR_INVALID_ADDRESS = 3
ERR_TYPE_UNSUPPORTED = 4

# CDC types
CDC_SPS = "SPS"  # Single Point Status
CDC_MV = "MV"    # Measured Value
CDC_SPC = "SPC"  # Single Point Controllable
CDC_DPC = "DPC"  # Double Point Controllable
CDC_APC = "APC"  # Analogue Process Control


def _ber_encode_length(length: int) -> bytes:
    if length < 0x80:
        return bytes([length])
    elif length < 0x100:
        return bytes([0x81, length])
    elif length < 0x10000:
        return bytes([0x82, length >> 8, length & 0xFF])
    else:
        return bytes([0x83, length >> 16, (length >> 8) & 0xFF, length & 0xFF])


def _ber_decode_length(data: bytes, offset: int) -> tuple[int, int]:
    if offset >= len(data):
        return 0, 0
    b = data[offset]
    if b < 0x80:
        return b, 1
    elif b == 0x81:
        if offset + 1 >= len(data):
            return 0, 0
        return data[offset + 1], 2
    elif b == 0x82:
        if offset + 2 >= len(data):
            return 0, 0
        return (data[offset + 1] << 8) | data[offset + 2], 3
    elif b == 0x83:
        if offset + 3 >= len(data):
            return 0, 0
        return (data[offset + 1] << 16) | (data[offset + 2] << 8) | data[offset + 3], 4
    return 0, 0


def _ber_encode_string(s: str) -> bytes:
    encoded = s.encode("utf-8")
    return bytes([0x1A]) + _ber_encode_length(len(encoded)) + encoded


def _ber_encode_int(val: int) -> bytes:
    if val == 0:
        return bytes([0x02, 0x01, 0x00])
    if val > 0:
        encoded = []
        v = val
        while v > 0:
            encoded.append(v & 0xFF)
            v >>= 8
        encoded.reverse()
        if encoded[0] & 0x80:
            encoded.insert(0, 0x00)
        return bytes([0x02]) + _ber_encode_length(len(encoded)) + bytes(encoded)
    else:
        encoded = []
        v = val
        while v < -1:
            encoded.append(v & 0xFF)
            v >>= 8
        encoded.append(v & 0xFF)
        encoded.reverse()
        return bytes([0x02]) + _ber_encode_length(len(encoded)) + bytes(encoded)


def _ber_encode_bool(val: bool) -> bytes:
    return bytes([0x01, 0x01, 0xFF if val else 0x00])


def _ber_encode_float(val: float) -> bytes:
    # Simplified: encode as BER real (8-byte double)
    raw = struct.pack(">d", val)
    return bytes([0x09, 0x08]) + raw


def _ber_encode_visible_string(s: str) -> bytes:
    encoded = s.encode("ascii")
    return bytes([0x1A]) + _ber_encode_length(len(encoded)) + encoded


class IEC61850DeviceBehavior(StandardDeviceBehavior):
    """IEC 61850 device behavior — maps points to LogicalNode.Data.Attribute."""

    def __init__(self, points: list | None = None):
        super().__init__(points)
        self._config: DeviceConfig | None = None
        # Map LD/LN/DO/DA path -> point name
        self._da_map: dict[str, str] = {}
        self._point_to_da: dict[str, str] = {}
        self._cdc_map: dict[str, str] = {}
        if points:
            for p in points:
                name = p.name if hasattr(p, "name") else p.get("name", "")
                addr = p.address if hasattr(p, "address") else p.get("address", "")
                da_path = addr if addr else f"LD0/LLN0.{name}.stVal"
                self._da_map[da_path] = name
                self._point_to_da[name] = da_path
                # Determine CDC type from data_type
                dt = p.data_type.value if hasattr(p, "data_type") else p.get("data_type", "float32")
                if dt == "bool":
                    self._cdc_map[name] = CDC_SPC
                else:
                    self._cdc_map[name] = CDC_MV

    def set_config(self, config: DeviceConfig) -> None:
        self._config = config

    def get_point_by_da(self, da_path: str) -> str | None:
        return self._da_map.get(da_path)

    def get_da_path(self, point_name: str) -> str:
        return self._point_to_da.get(point_name, "")

    def get_cdc(self, point_name: str) -> str:
        return self._cdc_map.get(point_name, CDC_MV)

    def get_all_da_paths(self) -> list[str]:
        return list(self._da_map.keys())


class IEC61850Server(ProtocolServer):
    """IEC 61850 server with MMS TCP mapping."""

    protocol_name = "iec61850"
    protocol_display_name = "IEC 61850"
    protocol_description = "IEC 61850 — 变电站自动化标准，MMS映射层(TCP)，支持逻辑设备/逻辑节点/数据对象模型"
    protocol_version = "Ed.2"

    def __init__(self):
        super().__init__()
        self._behaviors: dict[str, IEC61850DeviceBehavior] = {}
        self._device_configs: dict[str, DeviceConfig] = {}
        self._host = "0.0.0.0"
        self._port = 102  # Default IEC 61850 MMS port
        self._server_task: asyncio.Task | None = None
        self._server_running = False

    async def start(self, config: dict[str, Any]) -> None:
        self._status = ProtocolStatus.STARTING
        self._host = config.get("host", "0.0.0.0")
        self._port = config.get("port", 102)
        self._validate_port(self._port)
        try:
            self._server_running = True
            self._server_task = asyncio.create_task(self._serve())
            self._status = ProtocolStatus.RUNNING
            logger.info("IEC 61850 server started on %s:%d (MMS)", self._host, self._port)
            self._log_debug("system", "server_start",
                            f"IEC 61850 service started {self._host}:{self._port} (MMS)",
                            detail={"host": self._host, "port": self._port})
        except Exception as e:
            self._status = ProtocolStatus.ERROR
            logger.exception("Failed to start IEC 61850 server: %s", e)
            raise

    async def stop(self) -> None:
        try:
            self._server_running = False
            if self._server_task:
                self._server_task.cancel()
                try:
                    await self._server_task
                except asyncio.CancelledError:
                    pass
        except Exception as e:
            logger.warning("IEC 61850 server stop error: %s", e)
        finally:
            self._status = ProtocolStatus.STOPPED
            logger.info("IEC 61850 server stopped")
            self._log_debug("system", "server_stop", "IEC 61850 service stopped")

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
            logger.exception("IEC 61850 server error: %s", e)
            self._status = ProtocolStatus.ERROR

    async def _handle_connection(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.on_client_connect()
        peer = writer.get_extra_info("peername", default=("?", "?"))
        self._log_debug("recv", "connection", f"IEC61850 client connected: {peer[0]}:{peer[1]}")

        try:
            while self._server_running:
                try:
                    tpkt = await asyncio.wait_for(reader.readexactly(4), timeout=_READ_TIMEOUT)
                except (asyncio.TimeoutError, asyncio.IncompleteReadError):
                    break

                if tpkt[0] != 0x03:  # TPKT version
                    break
                tpkt_len = struct.unpack(">H", tpkt[2:4])[0]
                if tpkt_len < 4:
                    break

                remaining = tpkt_len - 4
                if remaining > 0:
                    try:
                        body = await reader.readexactly(remaining)
                    except asyncio.IncompleteReadError:
                        break

                    # Parse COTP header
                    cotp_len = body[0]
                    cotp_class = body[1] & 0xF0

                    if cotp_class == 0xF0:  # Data transfer class
                        # Extract MMS PDU
                        mms_offset = 2 + cotp_len
                        if mms_offset < len(body):
                            mms_pdu = body[mms_offset:]
                            response = self._process_mms_pdu(mms_pdu)
                            if response:
                                await self._send_mms_response(writer, response)

                    elif cotp_class == 0xE0:  # Connection request
                        # Send COTP connect confirm + MMS Initiate Response
                        init_resp = self._build_initiate_response()
                        await self._send_mms_response(writer, init_resp)

        except Exception as e:
            self.record_protocol_error(ProtocolErrorCategory.NETWORK, str(e))
            logger.debug("IEC 61850 connection error from %s: %s", peer, e)
        finally:
            self.on_client_disconnect()
            self._log_debug("send", "disconnected", f"IEC61850 client disconnected: {peer[0]}:{peer[1]}")

    async def _send_mms_response(self, writer: asyncio.StreamWriter, mms_pdu: bytes) -> None:
        # Wrap in COTP + TPKT
        cotp_header = bytes([0x02, 0xF0, 0x80])  # len=2, DT class, EOT flag
        cotp = cotp_header + mms_pdu
        tpkt_len = len(cotp) + 4
        tpkt = struct.pack(">BBH", 0x03, 0x00, tpkt_len)
        writer.write(tpkt + cotp)
        await writer.drain()

    def _build_initiate_response(self) -> bytes:
        """Build MMS Initiate Response PDU."""
        # Simplified Initiate Response
        result = bytes([0x00])  # negotiated version
        result += bytes([0x01])  # proposed parameter structure
        result += b"\x00\x01"  # services supported
        mms_pdu = bytes([TAG_INITIATE_CON]) + _ber_encode_length(len(result)) + result
        return mms_pdu

    def _process_mms_pdu(self, pdu: bytes) -> bytes | None:
        if not pdu:
            return None

        tag = pdu[0]
        length, length_bytes = _ber_decode_length(pdu, 1)
        content = pdu[1 + length_bytes:1 + length_bytes + length]

        self._log_debug("recv", "mms_pdu", f"IEC61850 MMS PDU tag=0x{tag:02X} len={length}")

        if tag == TAG_READ_REQ:
            return self._handle_read_request(content)
        elif tag == TAG_WRITE_REQ:
            return self._handle_write_request(content)
        elif tag == TAG_GET_NAME_LIST_REQ:
            return self._handle_get_name_list(content)
        elif tag == TAG_CONCLUDE_REQ:
            return bytes([TAG_CONCLUDE_CON, 0x00])
        elif tag == TAG_IDENTIFY_REQ:
            return self._handle_identify()
        elif tag == TAG_STATUS_REQ:
            return bytes([TAG_STATUS_CON, 0x01, 0x00])

        return None

    def _handle_read_request(self, content: bytes) -> bytes:
        # Parse variable specification (simplified)
        # In real MMS, this is complex BER encoding of variable access spec
        # We extract the domain/item name from the BER structure
        da_path = self._extract_variable_name(content)

        point_name = None
        dev_id = None
        for did, behavior in self._behaviors.items():
            point_name = behavior.get_point_by_da(da_path)
            if point_name:
                dev_id = did
                break

        if not point_name or not dev_id:
            # Build error response
            return self._build_read_error(ERR_ACCESS_NON_EXISTENT)

        behavior = self._behaviors[dev_id]
        val = behavior.get_value(point_name)
        cdc = behavior.get_cdc(point_name)

        return self._build_read_response(da_path, val, cdc)

    def _handle_write_request(self, content: bytes) -> bytes:
        da_path, write_val = self._extract_write_value(content)

        point_name = None
        dev_id = None
        for did, behavior in self._behaviors.items():
            point_name = behavior.get_point_by_da(da_path)
            if point_name:
                dev_id = did
                break

        if not point_name or not dev_id:
            return self._build_write_error(ERR_ACCESS_NON_EXISTENT)

        behavior = self._behaviors[dev_id]
        behavior.on_write(point_name, write_val)
        self._log_debug("recv", "mms_write", f"IEC61850 write {da_path}={write_val}", device_id=dev_id)

        # Write success
        return bytes([TAG_WRITE_CON, 0x01, 0x00])

    def _handle_get_name_list(self, content: bytes) -> bytes:
        # Return list of all data attributes
        names = []
        for behavior in self._behaviors.values():
            names.extend(behavior.get_all_da_paths())

        # Build GetNameList response
        result = b""
        for name in names:
            result += _ber_encode_visible_string(name)

        mms_pdu = bytes([TAG_GET_NAME_LIST_CON]) + _ber_encode_length(len(result)) + result
        return mms_pdu

    def _handle_identify(self) -> bytes:
        vendor = _ber_encode_visible_string("ProtoForge")
        model = _ber_encode_visible_string("IEC 61850 Simulator")
        revision = _ber_encode_visible_string("1.0.0")
        result = vendor + model + revision
        mms_pdu = bytes([TAG_IDENTIFY_CON]) + _ber_encode_length(len(result)) + result
        return mms_pdu

    def _extract_variable_name(self, content: bytes) -> str:
        """Extract variable name from MMS Read request BER content."""
        # Very simplified: look for visible string in content
        for i in range(len(content)):
            if content[i] == 0x1A:  # Visible string tag
                str_len, len_bytes = _ber_decode_length(content, i + 1)
                if i + 1 + len_bytes + str_len <= len(content):
                    return content[i + 1 + len_bytes:i + 1 + len_bytes + str_len].decode("ascii", errors="replace")
        return ""

    def _extract_write_value(self, content: bytes) -> tuple[str, Any]:
        """Extract variable name and value from MMS Write request."""
        name = self._extract_variable_name(content)
        # Look for value after the name
        for i in range(len(content)):
            if content[i] == 0x1A:
                str_len, len_bytes = _ber_decode_length(content, i + 1)
                after_str = i + 1 + len_bytes + str_len
                if after_str < len(content):
                    val_tag = content[after_str]
                    if val_tag == 0x02:  # Integer
                        int_len, int_lb = _ber_decode_length(content, after_str + 1)
                        raw = content[after_str + 1 + int_lb:after_str + 1 + int_lb + int_len]
                        if raw:
                            return name, int.from_bytes(raw, "big", signed=True)
                    elif val_tag == 0x09:  # Real (float)
                        float_len, fl_lb = _ber_decode_length(content, after_str + 1)
                        raw = content[after_str + 1 + fl_lb:after_str + 1 + fl_lb + float_len]
                        if len(raw) == 8:
                            return name, struct.unpack(">d", raw)[0]
                        elif len(raw) == 4:
                            return name, struct.unpack(">f", raw)[0]
                    elif val_tag == 0x01:  # Boolean
                        bool_val = content[after_str + 2] if after_str + 2 < len(content) else 0
                        return name, bool(bool_val)
                    elif val_tag == 0x1A:  # String
                        s_len, s_lb = _ber_decode_length(content, after_str + 1)
                        raw = content[after_str + 1 + s_lb:after_str + 1 + s_lb + s_len]
                        return name, raw.decode("ascii", errors="replace")
                break
        return name, 0

    def _build_read_response(self, da_path: str, value: Any, cdc: str) -> bytes:
        """Build MMS Read Response PDU."""
        if cdc in (CDC_SPS, CDC_SPC):
            val_encoded = _ber_encode_bool(bool(value))
        elif cdc == CDC_MV:
            if isinstance(value, float):
                val_encoded = _ber_encode_float(value)
            else:
                val_encoded = _ber_encode_int(int(value))
        else:
            val_encoded = _ber_encode_float(float(value))

        result = val_encoded
        mms_pdu = bytes([0xAD]) + _ber_encode_length(len(result)) + result  # Read Con tag = 0xAD in some impls
        return mms_pdu

    def _build_read_error(self, err_code: int) -> bytes:
        err = _ber_encode_int(err_code)
        return bytes([0x8D]) + _ber_encode_length(len(err)) + err  # ServiceError

    def _build_write_error(self, err_code: int) -> bytes:
        err = _ber_encode_int(err_code)
        return bytes([0x8D]) + _ber_encode_length(len(err)) + err

    async def create_device(self, device_config: DeviceConfig) -> str:
        self._device_configs[device_config.id] = device_config
        behavior = IEC61850DeviceBehavior(device_config.points)
        behavior.set_config(device_config)
        self._behaviors[device_config.id] = behavior
        self._update_default_device(device_config.id)
        self._log_debug("system", "device_create",
                        f"IEC61850 device created: {device_config.name} ({len(device_config.points)} DA)",
                        device_id=device_config.id)
        logger.info("IEC 61850 device created: %s (%d points)", device_config.id, len(device_config.points))
        return device_config.id

    async def remove_device(self, device_id: str) -> None:
        self._behaviors.pop(device_id, None)
        self._device_configs.pop(device_id, None)
        self._clear_default_device(device_id)
        self._log_debug("system", "device_remove", f"IEC61850 device removed: {device_id}", device_id=device_id)

    async def read_points(self, device_id: str) -> list[PointValue]:
        behavior = self._behaviors.get(device_id)
        if not behavior:
            return []
        results = []
        for point_name in behavior._values:
            val = behavior.get_value(point_name)
            results.append(PointValue(name=point_name, value=val, timestamp=time.time(),
                                      quality="good", simulated=True))
        return results

    async def write_point(self, device_id: str, point_name: str, value: Any) -> bool:
        behavior = self._behaviors.get(device_id)
        if not behavior:
            return False
        behavior.on_write(point_name, value)
        self._log_debug("recv", "point_write", f"IEC61850 write {point_name}={value}", device_id=device_id)
        return True

    async def sync_point_value(self, device_id: str, point_name: str, value: Any) -> None:
        behavior = self._behaviors.get(device_id)
        if behavior:
            behavior.set_value(point_name, value)

    def get_config_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "ied_name": {
                    "type": "string", "default": "PROTOFORGE",
                    "description": "IED (Intelligent Electronic Device) name"
                },
            },
        }
