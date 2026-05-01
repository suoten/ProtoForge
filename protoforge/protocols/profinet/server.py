import asyncio
import logging
import struct
import time
import uuid
from enum import IntEnum
from typing import Any

from protoforge.models.device import DeviceConfig, PointConfig, PointValue
from protoforge.protocols.behavior import DefaultDeviceBehavior as DeviceBehavior, ProtocolServer, ProtocolStatus
from protoforge.protocols.behavior import DynamicValueGenerator

logger = logging.getLogger(__name__)

PROFINET_ETH_TYPE = 0x8892
DCP_ETH_TYPE = 0x8892
DCP_SERVICE_GET = 0x03
DCP_SERVICE_SET = 0x04
DCP_SERVICE_IDENTIFY = 0x05
DCP_BLOCK_DEVICE_NAME = 0x02
DCP_BLOCK_IP = 0x01

PNIO_FRAME_ID_RT = 0x8000
PNIO_ALARM_HIGH = 0xFC01
PNIO_ALARM_LOW = 0xFE01

MSG_TYPE_DCP = 0x01
MSG_TYPE_RT = 0x02
MSG_TYPE_CM = 0x03
MSG_TYPE_ALARM = 0x04


class ARState(IntEnum):
    W_CONNECT = 1
    W_DATA = 2
    W_ABORT = 3


class CRType(IntEnum):
    INPUT = 1
    OUTPUT = 2
    ALARM = 3


class CommunicationRelation:
    def __init__(self, cr_type: CRType, cr_id: int, data_length: int):
        self.cr_type = cr_type
        self.cr_id = cr_id
        self.data_length = data_length
        self.frame_id: int = 0
        self.is_consumer: bool = cr_type == CRType.INPUT
        self.is_provider: bool = cr_type == CRType.OUTPUT

    def to_dict(self) -> dict[str, Any]:
        return {
            "cr_type": self.cr_type.name,
            "cr_id": self.cr_id,
            "data_length": self.data_length,
            "frame_id": self.frame_id,
        }


class ApplicationRelation:
    def __init__(self, ar_id: int, ar_uuid: bytes, ar_type: int = 1):
        self.ar_id = ar_id
        self.ar_uuid = ar_uuid
        self.ar_type = ar_type
        self.state = ARState.W_CONNECT
        self.crs: list[CommunicationRelation] = []
        self.session_key: int = 0
        self.send_clock: int = 0x0032
        self.reduction_ratio: int = 1
        self.watchdog_timeout: int = 100
        self.data_hold_factor: int = 1
        self.input_cr: CommunicationRelation | None = None
        self.output_cr: CommunicationRelation | None = None
        self.alarm_cr: CommunicationRelation | None = None

    def setup_default_crs(self, input_size: int, output_size: int) -> None:
        if input_size > 0:
            self.input_cr = CommunicationRelation(CRType.INPUT, 1, input_size)
            self.input_cr.frame_id = PNIO_FRAME_ID_RT
            self.crs.append(self.input_cr)
        if output_size > 0:
            self.output_cr = CommunicationRelation(CRType.OUTPUT, 2, output_size)
            self.output_cr.frame_id = PNIO_FRAME_ID_RT
            self.crs.append(self.output_cr)
        self.alarm_cr = CommunicationRelation(CRType.ALARM, 3, 0)
        self.alarm_cr.frame_id = PNIO_ALARM_HIGH
        self.crs.append(self.alarm_cr)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ar_id": self.ar_id,
            "ar_uuid": self.ar_uuid.hex(),
            "state": self.state.name,
            "crs": [cr.to_dict() for cr in self.crs],
        }


class ProfinetDeviceBehavior(DeviceBehavior):
    def __init__(self, points: list[PointConfig]):
        self._points = {p.name: p for p in points}
        self._values: dict[str, Any] = {}
        self._generators: dict[str, DynamicValueGenerator] = {}
        for p in points:
            self._values[p.name] = p.fixed_value if p.fixed_value is not None else 0
            self._generators[p.name] = DynamicValueGenerator(p)

    def generate_value(self, point_config: dict[str, Any]) -> Any:
        name = point_config.get("name", "")
        return self._values.get(name, 0)

    def on_write(self, point_name: str, value: Any) -> bool:
        if point_name in self._values:
            self._values[point_name] = value
            return True
        return False

    def set_value(self, point_name: str, value: Any) -> None:
        self._values[point_name] = value

    def get_value(self, point_name: str) -> Any:
        gen = self._generators.get(point_name)
        if gen:
            pt = self._points.get(point_name)
            if pt and hasattr(pt, "generator_type") and pt.generator_type.value != "fixed":
                value = gen.generate()
                self._values[point_name] = value
                return value
        return self._values.get(point_name, 0)

    def get_input_data(self, config: DeviceConfig) -> bytes:
        data = bytearray()
        for point in config.points:
            val = self._values.get(point.name, 0)
            if point.data_type.value in ("bool",):
                data.append(int(bool(val)))
            elif point.data_type.value in ("int16",):
                data += struct.pack(">h", int(val))
            elif point.data_type.value in ("uint16",):
                data += struct.pack(">H", int(val) & 0xFFFF)
            elif point.data_type.value in ("int32",):
                data += struct.pack(">i", int(val))
            elif point.data_type.value in ("uint32",):
                data += struct.pack(">I", int(val) & 0xFFFFFFFF)
            elif point.data_type.value in ("float32", "float"):
                data += struct.pack(">f", float(val))
            else:
                data += struct.pack(">H", int(val) & 0xFFFF)
        return bytes(data)

    def set_output_data(self, config: DeviceConfig, data: bytes) -> None:
        offset = 0
        for point in config.points:
            if offset >= len(data):
                break
            if point.data_type.value in ("bool",):
                self._values[point.name] = bool(data[offset])
                offset += 1
            elif point.data_type.value in ("int16",):
                if offset + 2 <= len(data):
                    self._values[point.name] = struct.unpack(">h", data[offset:offset + 2])[0]
                    offset += 2
            elif point.data_type.value in ("uint16",):
                if offset + 2 <= len(data):
                    self._values[point.name] = struct.unpack(">H", data[offset:offset + 2])[0]
                    offset += 2
            elif point.data_type.value in ("int32",):
                if offset + 4 <= len(data):
                    self._values[point.name] = struct.unpack(">i", data[offset:offset + 4])[0]
                    offset += 4
            elif point.data_type.value in ("uint32",):
                if offset + 4 <= len(data):
                    self._values[point.name] = struct.unpack(">I", data[offset:offset + 4])[0]
                    offset += 4
            elif point.data_type.value in ("float32", "float"):
                if offset + 4 <= len(data):
                    self._values[point.name] = struct.unpack(">f", data[offset:offset + 4])[0]
                    offset += 4
            else:
                if offset + 2 <= len(data):
                    self._values[point.name] = struct.unpack(">H", data[offset:offset + 2])[0]
                    offset += 2


class ProfinetServer(ProtocolServer):
    protocol_name = "profinet"
    protocol_display_name = "PROFINET IO"

    def __init__(self):
        super().__init__()
        self._behaviors: dict[str, ProfinetDeviceBehavior] = {}
        self._device_configs: dict[str, DeviceConfig] = {}
        self._host = "0.0.0.0"
        self._port = 34964
        self._server_task: asyncio.Task | None = None
        self._server_running = False
        self._device_name = "protoforge-device"
        self._vendor_id = 0x010A
        self._device_id = 0x0100
        self._input_size = 0
        self._output_size = 0
        self._connections: set[asyncio.StreamWriter] = set()
        self._ip_address = "192.168.1.1"
        self._subnet_mask = "255.255.255.0"
        self._gateway = "192.168.1.254"
        self._ar_counter = 0
        self._active_ars: dict[int, ApplicationRelation] = {}
        self._alarm_seq = 0

    async def start(self, config: dict[str, Any]) -> None:
        self._status = ProtocolStatus.STARTING
        self._host = config.get("host", "0.0.0.0")
        self._port = config.get("port", 34964)
        self._device_name = config.get("device_name", "protoforge-device")
        self._vendor_id = config.get("vendor_id", 0x010A)
        self._device_id = config.get("device_id", 0x0100)
        self._ip_address = config.get("ip_address", "192.168.1.1")
        self._subnet_mask = config.get("subnet_mask", "255.255.255.0")
        self._gateway = config.get("gateway", "192.168.1.254")
        try:
            self._recalc_data_sizes()
            self._server_running = True
            self._active_ars.clear()
            self._ar_counter = 0

            self._server_task = asyncio.create_task(self._serve())
            self._status = ProtocolStatus.RUNNING
            logger.info("PROFINET IO server starting on %s:%d", self._host, self._port)
            self._log_debug("system", "server_start",
                            f"PROFINET IO服务启动 {self._host}:{self._port}",
                            detail={"host": self._host, "port": self._port,
                                    "device_name": self._device_name})
        except Exception as e:
            self._status = ProtocolStatus.ERROR
            logger.error("Failed to start PROFINET server: %s", e)
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
            logger.warning("PROFINET server stop error: %s", e)
        finally:
            self._status = ProtocolStatus.STOPPED
            self._active_ars.clear()
            logger.info("PROFINET IO server stopped")
            self._log_debug("system", "server_stop", "PROFINET IO服务停止")

    def _recalc_data_sizes(self) -> None:
        self._input_size = 0
        self._output_size = 0
        for cfg in self._device_configs.values():
            for point in cfg.points:
                sz = self._point_size(point)
                if point.access in ("r", "rw"):
                    self._input_size += sz
                if point.access in ("w", "rw"):
                    self._output_size += sz

    def _point_size(self, point: PointConfig) -> int:
        dt = point.data_type.value
        if dt == "bool":
            return 1
        if dt in ("int16", "uint16"):
            return 2
        if dt in ("int32", "uint32", "float32", "float"):
            return 4
        if dt == "float64":
            return 8
        return 2

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
            logger.error("PROFINET IO server error: %s", e)
            self._status = ProtocolStatus.ERROR

    async def _handle_connection(self, reader: asyncio.StreamReader,
                                  writer: asyncio.StreamWriter) -> None:
        addr = writer.get_extra_info("peername")
        logger.info("PROFINET IO connection from %s", addr)
        self._connections.add(writer)
        self._log_debug("inbound", "connect",
                        f"IO Controller连接: {addr[0]}:{addr[1]}",
                        detail={"peer": str(addr)})
        try:
            while self._server_running:
                header = await reader.readexactly(2)
                body_len = struct.unpack(">H", header)[0]
                data = await reader.readexactly(body_len) if body_len > 0 else b""
                response = self._process_tunnel_message(data, addr, writer)
                if response:
                    resp_len = struct.pack(">H", len(response))
                    writer.write(resp_len + response)
                    await writer.drain()
        except (ConnectionResetError, asyncio.CancelledError, asyncio.IncompleteReadError):
            pass
        finally:
            self._connections.discard(writer)
            for ar_id in list(self._active_ars.keys()):
                ar = self._active_ars[ar_id]
                if ar.state == ARState.W_DATA:
                    ar.state = ARState.W_ABORT
                    self._log_debug("outbound", "ar_abort",
                                    f"PROFINET AR[{ar_id}]连接断开, 转为W_ABORT",
                                    detail={"ar_id": ar_id})
            writer.close()
            try:
                await writer.wait_closed()
            except Exception as e:
                logger.debug("Writer wait_closed error: %s", e)

    def _process_tunnel_message(self, data: bytes, addr: tuple,
                                 writer: asyncio.StreamWriter) -> bytes | None:
        if len(data) < 2:
            return None
        msg_type = data[0]
        if msg_type == MSG_TYPE_DCP:
            return self._handle_dcp_tunnel(data, addr)
        elif msg_type == MSG_TYPE_RT:
            return self._handle_rt_tunnel(data)
        elif msg_type == MSG_TYPE_CM:
            return self._handle_cm_tunnel(data, addr, writer)
        elif msg_type == MSG_TYPE_ALARM:
            return self._handle_alarm_tunnel(data)
        return None

    def _handle_dcp_tunnel(self, data: bytes, addr: tuple) -> bytes | None:
        if len(data) < 6:
            return None
        service_id = data[1]
        xid = struct.unpack(">I", data[2:6])[0] if len(data) >= 6 else 0
        if service_id == DCP_SERVICE_IDENTIFY:
            resp = self._make_dcp_identify_response(data, xid)
            return bytes([MSG_TYPE_DCP]) + resp
        elif service_id == DCP_SERVICE_GET:
            resp = self._make_dcp_get_response(data, xid)
            return bytes([MSG_TYPE_DCP]) + resp
        elif service_id == DCP_SERVICE_SET:
            resp = self._make_dcp_set_response(data, xid)
            return bytes([MSG_TYPE_DCP]) + resp
        return None

    def _make_dcp_identify_response(self, data: bytes, xid: int) -> bytes:
        resp = bytearray()
        resp += struct.pack(">H", self._vendor_id)
        resp += struct.pack(">H", self._device_id)

        name_bytes = self._device_name.encode("utf-8")
        resp += struct.pack(">BH", DCP_BLOCK_DEVICE_NAME, len(name_bytes) + 4)
        resp += name_bytes
        resp += b"\x00" * ((4 - len(name_bytes) % 4) % 4)

        resp += struct.pack(">BHIHII",
                            DCP_BLOCK_IP, 14,
                            self._ip_to_int(self._ip_address),
                            self._ip_to_int(self._subnet_mask),
                            self._ip_to_int(self._gateway),
                            0)

        header = bytearray()
        header += struct.pack(">BBIBH",
                              DCP_SERVICE_IDENTIFY + 1,
                              0x01,
                              xid,
                              0x0001,
                              len(resp))
        return bytes(header + resp)

    def _make_dcp_get_response(self, data: bytes, xid: int) -> bytes:
        resp = bytearray()
        name_bytes = self._device_name.encode("utf-8")
        resp += struct.pack(">BH", DCP_BLOCK_DEVICE_NAME, len(name_bytes) + 4)
        resp += name_bytes

        header = bytearray()
        header += struct.pack(">BBIBH",
                              DCP_SERVICE_GET + 1,
                              0x01,
                              xid,
                              0x0001,
                              len(resp))
        return bytes(header + resp)

    def _make_dcp_set_response(self, data: bytes, xid: int) -> bytes:
        header = bytearray()
        header += struct.pack(">BBIBH",
                              DCP_SERVICE_SET + 1,
                              0x01,
                              xid,
                              0x0001,
                              0)
        return bytes(header)

    def _handle_cm_tunnel(self, data: bytes, addr: tuple,
                           writer: asyncio.StreamWriter) -> bytes | None:
        if len(data) < 3:
            return None
        cm_op = data[1]
        cm_seq = data[2]

        if cm_op == 0x01:
            return self._handle_cm_connect(data, addr, writer, cm_seq)
        elif cm_op == 0x02:
            return self._handle_cm_release(data, cm_seq)
        elif cm_op == 0x03:
            return self._handle_cm_read(data, cm_seq)
        elif cm_op == 0x04:
            return self._handle_cm_write(data, cm_seq)
        elif cm_op == 0x05:
            return self._handle_cm_control(data, cm_seq)

        return bytes([MSG_TYPE_CM, 0xFF, cm_seq]) + struct.pack(">H", 0x8001)

    def _handle_cm_connect(self, data: bytes, addr: tuple,
                            writer: asyncio.StreamWriter, cm_seq: int) -> bytes:
        self._ar_counter += 1
        ar_id = self._ar_counter
        ar_uuid = uuid.uuid4().bytes

        ar = ApplicationRelation(ar_id, ar_uuid)
        ar.setup_default_crs(self._input_size, self._output_size)

        if len(data) >= 10:
            ar.ar_type = data[3] if len(data) > 3 else 1
            ar.session_key = struct.unpack(">H", data[4:6])[0] if len(data) >= 6 else 0
            ar.send_clock = struct.unpack(">H", data[6:8])[0] if len(data) >= 8 else 0x0032
            ar.reduction_ratio = struct.unpack(">H", data[8:10])[0] if len(data) >= 10 else 1

        ar.state = ARState.W_DATA
        self._active_ars[ar_id] = ar

        resp = bytearray()
        resp += struct.pack(">H", ar_id)
        resp += ar_uuid
        resp += struct.pack(">B", ar.ar_type)
        resp += struct.pack(">H", ar.session_key)
        resp += struct.pack(">H", ar.send_clock)
        resp += struct.pack(">H", ar.reduction_ratio)
        resp += struct.pack(">H", 0x0000)
        resp += struct.pack(">H", len(ar.crs))
        for cr in ar.crs:
            resp += struct.pack(">B", cr.cr_type.value)
            resp += struct.pack(">H", cr.cr_id)
            resp += struct.pack(">H", cr.data_length)
            resp += struct.pack(">H", cr.frame_id)
            resp += struct.pack(">B", 0x01 if cr.is_provider else 0x00)
            resp += struct.pack(">B", 0x01 if cr.is_consumer else 0x00)

        self._log_debug("inbound", "cm_connect",
                        f"PROFINET CM Connect: AR[{ar_id}]建立, 状态=W_DATA, "
                        f"CRs={len(ar.crs)}, input={self._input_size}, output={self._output_size}",
                        detail={"ar_id": ar_id, "session_key": ar.session_key,
                                "send_clock": ar.send_clock, "crs": len(ar.crs)})

        return bytes([MSG_TYPE_CM, 0x01, cm_seq]) + resp

    def _handle_cm_release(self, data: bytes, cm_seq: int) -> bytes:
        ar_id = struct.unpack(">H", data[3:5])[0] if len(data) >= 5 else 0
        ar = self._active_ars.pop(ar_id, None)

        if ar:
            ar.state = ARState.W_ABORT
            self._log_debug("inbound", "cm_release",
                            f"PROFINET CM Release: AR[{ar_id}]释放",
                            detail={"ar_id": ar_id})
        else:
            self._log_debug("inbound", "cm_release_error",
                            f"PROFINET CM Release: AR[{ar_id}]不存在",
                            detail={"ar_id": ar_id})

        resp = bytearray()
        resp += struct.pack(">H", ar_id)
        resp += struct.pack(">H", 0x0000)

        return bytes([MSG_TYPE_CM, 0x02, cm_seq]) + resp

    def _handle_cm_read(self, data: bytes, cm_seq: int) -> bytes:
        resp = bytearray()
        resp += struct.pack(">H", 0x0000)
        resp += struct.pack(">H", 0x0000)
        return bytes([MSG_TYPE_CM, 0x03, cm_seq]) + resp

    def _handle_cm_write(self, data: bytes, cm_seq: int) -> bytes:
        resp = bytearray()
        resp += struct.pack(">H", 0x0000)
        resp += struct.pack(">H", 0x0000)
        return bytes([MSG_TYPE_CM, 0x04, cm_seq]) + resp

    def _handle_cm_control(self, data: bytes, cm_seq: int) -> bytes:
        ar_id = struct.unpack(">H", data[3:5])[0] if len(data) >= 5 else 0
        control_cmd = data[5] if len(data) > 5 else 0

        ar = self._active_ars.get(ar_id)
        if ar:
            if control_cmd == 0x01:
                ar.state = ARState.W_DATA
                self._log_debug("inbound", "cm_control",
                                f"PROFINET CM Control: AR[{ar_id}] -> W_DATA (ApplicationReady)",
                                detail={"ar_id": ar_id, "command": "ApplicationReady"})
            elif control_cmd == 0x02:
                ar.state = ARState.W_ABORT
                self._log_debug("inbound", "cm_control",
                                f"PROFINET CM Control: AR[{ar_id}] -> W_ABORT",
                                detail={"ar_id": ar_id, "command": "Abort"})

        resp = bytearray()
        resp += struct.pack(">H", ar_id)
        resp += struct.pack(">B", control_cmd)
        resp += struct.pack(">H", 0x0000)

        return bytes([MSG_TYPE_CM, 0x05, cm_seq]) + resp

    def _handle_alarm_tunnel(self, data: bytes) -> bytes | None:
        if len(data) < 8:
            return None

        alarm_type = struct.unpack(">H", data[1:3])[0]
        ar_id = struct.unpack(">H", data[3:5])[0]
        alarm_seq = struct.unpack(">H", data[5:7])[0]
        alarm_spec = data[7] if len(data) > 7 else 0

        ar = self._active_ars.get(ar_id)

        self._log_debug("inbound", "alarm_received",
                        f"PROFINET Alarm: AR[{ar_id}] type=0x{alarm_type:04X} seq={alarm_seq}",
                        detail={"ar_id": ar_id, "alarm_type": alarm_type,
                                "alarm_seq": alarm_seq, "alarm_spec": alarm_spec})

        resp = bytearray()
        resp += struct.pack(">H", alarm_type)
        resp += struct.pack(">H", ar_id)
        resp += struct.pack(">H", alarm_seq)
        resp += struct.pack(">B", 0x00)
        resp += struct.pack(">H", 0x0000)

        return bytes([MSG_TYPE_ALARM]) + resp

    def _send_alarm(self, ar_id: int, alarm_type: int, alarm_detail: bytes = b"",
                     writers: set[asyncio.StreamWriter] | None = None) -> None:
        self._alarm_seq = (self._alarm_seq + 1) & 0xFFFF
        alarm_msg = bytearray()
        alarm_msg += struct.pack(">H", alarm_type)
        alarm_msg += struct.pack(">H", ar_id)
        alarm_msg += struct.pack(">H", self._alarm_seq)
        alarm_msg += struct.pack(">B", 0x01)
        alarm_msg += struct.pack(">H", len(alarm_detail))
        alarm_msg += alarm_detail

        payload = bytes([MSG_TYPE_ALARM]) + bytes(alarm_msg)
        frame = struct.pack(">H", len(payload)) + payload

        self._log_debug("outbound", "alarm_send",
                        f"PROFINET Alarm发送: AR[{ar_id}] type=0x{alarm_type:04X}",
                        detail={"ar_id": ar_id, "alarm_type": alarm_type,
                                "alarm_seq": self._alarm_seq})

        if writers:
            for w in writers:
                try:
                    w.write(frame)
                except Exception:
                    pass

    def _handle_rt_tunnel(self, data: bytes) -> bytes | None:
        behavior = self._behaviors.get(self._default_device_id)
        config = self._device_configs.get(self._default_device_id)
        if not behavior or not config:
            return None

        active_ar = None
        for ar in self._active_ars.values():
            if ar.state == ARState.W_DATA:
                active_ar = ar
                break

        payload = data[1:]
        cycle_counter = 0
        data_status = 0x01
        transfer_status = 0x00

        if len(payload) >= 4:
            cycle_counter = struct.unpack(">H", payload[0:2])[0]
            data_status = payload[2]
            transfer_status = payload[3]

        rt_payload = payload[4:] if len(payload) > 4 else b""

        if self._output_size > 0 and len(rt_payload) >= self._output_size:
            output_data = rt_payload[:self._output_size]
            behavior.set_output_data(config, output_data)
            self._log_debug("inbound", "cyclic_write",
                            f"PROFINET IO循环写入 {len(output_data)}字节 cycle={cycle_counter}",
                            device_id=self._default_device_id or "",
                            detail={"size": len(output_data), "cycle": cycle_counter})

        input_data = behavior.get_input_data(config)

        resp_cycle = (cycle_counter + 1) & 0xFFFF
        resp = bytearray()
        resp += struct.pack(">H", resp_cycle)
        resp += struct.pack(">B", 0x05 if active_ar else 0x01)
        resp += struct.pack(">B", transfer_status)
        resp += input_data

        self._log_debug("outbound", "cyclic_read",
                        f"PROFINET IO循环响应 {len(input_data)}字节 cycle={resp_cycle}",
                        device_id=self._default_device_id or "",
                        detail={"size": len(input_data), "cycle": resp_cycle})

        return bytes([MSG_TYPE_RT]) + bytes(resp)

    async def create_device(self, device_config: DeviceConfig) -> str:
        behavior = ProfinetDeviceBehavior(device_config.points)
        self._behaviors[device_config.id] = behavior
        self._device_configs[device_config.id] = device_config
        self._update_default_device(device_config.id)

        proto_config = device_config.protocol_config or {}
        if proto_config.get("device_name"):
            self._device_name = proto_config["device_name"]
        if proto_config.get("vendor_id"):
            self._vendor_id = int(proto_config["vendor_id"])
        if proto_config.get("device_id"):
            self._device_id = int(proto_config["device_id"])

        self._recalc_data_sizes()

        for ar in self._active_ars.values():
            if ar.state == ARState.W_DATA:
                ar.setup_default_crs(self._input_size, self._output_size)

        logger.info("PROFINET IO device created: %s (input=%d, output=%d)",
                     device_config.id, self._input_size, self._output_size)
        self._log_debug("system", "device_created",
                        f"PROFINET设备创建: {device_config.name}",
                        device_id=device_config.id,
                        detail={"input_size": self._input_size,
                                "output_size": self._output_size})
        return device_config.id

    async def remove_device(self, device_id: str) -> None:
        self._behaviors.pop(device_id, None)
        self._device_configs.pop(device_id, None)
        self._clear_default_device(device_id)
        self._recalc_data_sizes()
        logger.info("PROFINET device removed: %s", device_id)
        self._log_debug("system", "device_remove",
                        f"移除PROFINET设备 {device_id}",
                        device_id=device_id)

    async def read_points(self, device_id: str) -> list[PointValue]:
        behavior = self._behaviors.get(device_id)
        config = self._device_configs.get(device_id)
        if not behavior or not config:
            return []
        now = time.time()
        result = []
        for point in config.points:
            value = behavior.get_value(point.name)
            result.append(PointValue(name=point.name, value=value, timestamp=now))
        return result

    async def write_point(self, device_id: str, point_name: str, value: Any) -> bool:
        behavior = self._behaviors.get(device_id)
        if not behavior:
            return False
        success = behavior.on_write(point_name, value)
        if success:
            self._log_debug("system", "write_point",
                            f"PROFINET写入测点: {point_name}={value}",
                            device_id=device_id)
        return success

    def get_config_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "host": {"type": "string", "default": "0.0.0.0", "description": "监听地址(TCP隧道模式)"},
                "port": {"type": "integer", "default": 34964, "description": "TCP隧道端口"},
                "device_name": {"type": "string", "default": "protoforge-device", "description": "PROFINET设备名称(DCP识别用)"},
                "vendor_id": {"type": "integer", "default": 266, "description": "厂商ID(VendorID)"},
                "device_id": {"type": "integer", "default": 256, "description": "设备ID(DeviceID)"},
                "ip_address": {"type": "string", "default": "192.168.1.1", "description": "DCP Identify响应IP地址"},
                "subnet_mask": {"type": "string", "default": "255.255.255.0", "description": "子网掩码"},
                "gateway": {"type": "string", "default": "192.168.1.254", "description": "默认网关"},
            },
            "description": "TCP隧道模式 - 支持DCP发现/CM连接建立/AR状态机/RT循环数据/Alarm通知",
        }

    @staticmethod
    def _ip_to_int(ip_str: str) -> int:
        try:
            parts = [int(x) for x in ip_str.split(".")]
            if len(parts) == 4:
                return (parts[0] << 24) | (parts[1] << 16) | (parts[2] << 8) | parts[3]
        except (ValueError, IndexError) as e:
            logger.warning("PROFINET IP parse error for '%s': %s", ip_str, e)
        return 0xC0A80101
