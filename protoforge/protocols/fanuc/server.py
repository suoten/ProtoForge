import asyncio
import logging
import struct
import time
from typing import Any

from protoforge.models.device import DeviceConfig, PointValue
from protoforge.protocols.base import DeviceBehavior, ProtocolServer, ProtocolStatus

logger = logging.getLogger(__name__)


class FanucDeviceBehavior(DeviceBehavior):
    def __init__(self, points: list = None):
        self._points: dict[str, Any] = {}
        self._values: dict[str, Any] = {}
        self._cnc_status = {
            "alarm": 0,
            "mode": 3,
            "execution": 1,
            "motion": 0,
            "program": "O0001",
            "speed_override": 100,
            "feed_override": 100,
            "spindle_speed": 3000,
            "feed_rate": 500,
            "absolute_pos": [0.0] * 5,
            "machine_pos": [0.0] * 5,
            "relative_pos": [0.0] * 5,
            "distance_pos": [0.0] * 5,
        }
        if points:
            for p in points:
                name = p.name if hasattr(p, 'name') else p.get("name", "")
                fixed_val = p.fixed_value if hasattr(p, 'fixed_value') else p.get("fixed_value")
                self._points[name] = p
                self._values[name] = fixed_val if fixed_val is not None else 0

    async def generate_value(self, point_config: dict[str, Any]) -> Any:
        name = point_config.get("name", "")
        return self._values.get(name, 0)

    async def on_write(self, point_name: str, value: Any) -> bool:
        if point_name in self._values:
            self._values[point_name] = value
            if point_name == "spindle_speed":
                self._cnc_status["spindle_speed"] = value
            elif point_name == "feed_rate":
                self._cnc_status["feed_rate"] = value
            elif point_name == "x_pos":
                self._cnc_status["absolute_pos"][0] = value
            elif point_name == "y_pos":
                self._cnc_status["absolute_pos"][1] = value
            elif point_name == "z_pos":
                self._cnc_status["absolute_pos"][2] = value
            elif point_name == "alarm":
                self._cnc_status["alarm"] = value
            return True
        return False

    def set_value(self, point_name: str, value: Any) -> None:
        self._values[point_name] = value

    def get_value(self, point_name: str) -> Any:
        return self._values.get(point_name, 0)


class FanucServer(ProtocolServer):
    protocol_name = "fanuc"
    protocol_display_name = "FANUC FOCAS"

    FOCAS_HEADER_SIZE = 10

    def __init__(self):
        super().__init__()
        self._behaviors: dict[str, FanucDeviceBehavior] = {}
        self._device_configs: dict[str, DeviceConfig] = {}
        self._device_params: dict[str, dict] = {}
        self._host = "0.0.0.0"
        self._port = 8193
        self._server_task: asyncio.Task | None = None
        self._server_running = False

    async def start(self, config: dict[str, Any]) -> None:
        self._status = ProtocolStatus.STARTING
        self._host = config.get("host", "0.0.0.0")
        self._port = config.get("port", 8193)
        try:
            self._server_running = True
            self._server_task = asyncio.create_task(self._serve())
            self._status = ProtocolStatus.RUNNING
            logger.info("FANUC FOCAS server started on %s:%d", self._host, self._port)
            self._log_debug("system", "server_start",
                            f"FANUC服务启动 {self._host}:{self._port}",
                            detail={"host": self._host, "port": self._port})
        except Exception as e:
            self._status = ProtocolStatus.ERROR
            logger.error("Failed to start FANUC server: %s", e)
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
            logger.warning("FANUC server stop error: %s", e)
        finally:
            self._status = ProtocolStatus.STOPPED
            logger.info("FANUC server stopped")
            self._log_debug("system", "server_stop", "FANUC服务停止")

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
            logger.error("FANUC server error: %s", e)
            self._status = ProtocolStatus.ERROR

    async def _handle_connection(self, reader: asyncio.StreamReader,
                                  writer: asyncio.StreamWriter) -> None:
        addr = writer.get_extra_info("peername")
        logger.debug("FANUC connection from %s", addr)
        try:
            while self._server_running:
                data = await reader.read(4096)
                if not data:
                    break
                response = self._process_focas(data)
                if response:
                    writer.write(response)
                    await writer.drain()
        except (ConnectionResetError, asyncio.CancelledError):
            pass
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    def _process_focas(self, data: bytes) -> bytes | None:
        if len(data) < self.FOCAS_HEADER_SIZE:
            return None

        func_id = struct.unpack("<H", data[0:2])[0]
        req_id = struct.unpack("<I", data[2:6])[0]
        data_len = struct.unpack("<I", data[6:10])[0]

        if func_id == 0x0001:
            return self._handle_cnc_connect(req_id)
        elif func_id == 0x0002:
            return self._handle_cnc_disconnect(req_id)
        elif func_id == 0x0101:
            return self._handle_cnc_statinfo(req_id)
        elif func_id == 0x0102:
            return self._handle_cnc_absolute(req_id)
        elif func_id == 0x0103:
            return self._handle_cnc_machine(req_id)
        elif func_id == 0x0104:
            return self._handle_cnc_relative(req_id)
        elif func_id == 0x0105:
            return self._handle_cnc_distance(req_id)
        elif func_id == 0x0110:
            return self._handle_cnc_rdspindlespd(req_id)
        elif func_id == 0x0111:
            return self._handle_cnc_rdfeed(req_id)
        elif func_id == 0x0120:
            return self._handle_cnc_alarm(req_id)
        elif func_id == 0x0130:
            return self._handle_cnc_program(req_id)

        return self._make_focas_error(req_id, 0x01)

    def _handle_cnc_connect(self, req_id: int) -> bytes:
        resp = bytearray()
        resp += struct.pack("<H", 0x0001)
        resp += struct.pack("<I", req_id)
        resp += struct.pack("<I", 0x00000000)
        resp += struct.pack("<I", 0x00000001)
        return bytes(resp)

    def _handle_cnc_disconnect(self, req_id: int) -> bytes:
        resp = bytearray()
        resp += struct.pack("<H", 0x0002)
        resp += struct.pack("<I", req_id)
        resp += struct.pack("<I", 0x00000000)
        return bytes(resp)

    def _handle_cnc_statinfo(self, req_id: int) -> bytes:
        behavior = self._behaviors.get(self._default_device_id)
        status = behavior._cnc_status if behavior else {
            "alarm": 0, "mode": 3, "execution": 1, "motion": 0
        }

        resp = bytearray()
        resp += struct.pack("<H", 0x0101)
        resp += struct.pack("<I", req_id)
        resp += struct.pack("<I", 0x00000000)
        resp += struct.pack("<H", status.get("alarm", 0))
        resp += struct.pack("<H", status.get("mode", 3))
        resp += struct.pack("<H", status.get("execution", 1))
        resp += struct.pack("<H", status.get("motion", 0))
        return bytes(resp)

    def _handle_cnc_absolute(self, req_id: int) -> bytes:
        behavior = self._behaviors.get(self._default_device_id)
        positions = behavior._cnc_status.get("absolute_pos", [0.0] * 5) if behavior else [0.0] * 5

        resp = bytearray()
        resp += struct.pack("<H", 0x0102)
        resp += struct.pack("<I", req_id)
        resp += struct.pack("<I", 0x00000000)
        resp += struct.pack("<H", 5)
        for pos in positions[:5]:
            resp += struct.pack("<d", pos)
        return bytes(resp)

    def _handle_cnc_machine(self, req_id: int) -> bytes:
        behavior = self._behaviors.get(self._default_device_id)
        positions = behavior._cnc_status.get("machine_pos", [0.0] * 5) if behavior else [0.0] * 5

        resp = bytearray()
        resp += struct.pack("<H", 0x0103)
        resp += struct.pack("<I", req_id)
        resp += struct.pack("<I", 0x00000000)
        resp += struct.pack("<H", 5)
        for pos in positions[:5]:
            resp += struct.pack("<d", pos)
        return bytes(resp)

    def _handle_cnc_relative(self, req_id: int) -> bytes:
        behavior = self._behaviors.get(self._default_device_id)
        positions = behavior._cnc_status.get("relative_pos", [0.0] * 5) if behavior else [0.0] * 5

        resp = bytearray()
        resp += struct.pack("<H", 0x0104)
        resp += struct.pack("<I", req_id)
        resp += struct.pack("<I", 0x00000000)
        resp += struct.pack("<H", 5)
        for pos in positions[:5]:
            resp += struct.pack("<d", pos)
        return bytes(resp)

    def _handle_cnc_distance(self, req_id: int) -> bytes:
        behavior = self._behaviors.get(self._default_device_id)
        positions = behavior._cnc_status.get("distance_pos", [0.0] * 5) if behavior else [0.0] * 5

        resp = bytearray()
        resp += struct.pack("<H", 0x0105)
        resp += struct.pack("<I", req_id)
        resp += struct.pack("<I", 0x00000000)
        resp += struct.pack("<H", 5)
        for pos in positions[:5]:
            resp += struct.pack("<d", pos)
        return bytes(resp)

    def _handle_cnc_rdspindlespd(self, req_id: int) -> bytes:
        behavior = self._behaviors.get(self._default_device_id)
        speed = behavior._cnc_status.get("spindle_speed", 3000) if behavior else 3000

        resp = bytearray()
        resp += struct.pack("<H", 0x0110)
        resp += struct.pack("<I", req_id)
        resp += struct.pack("<I", 0x00000000)
        resp += struct.pack("<d", float(speed))
        return bytes(resp)

    def _handle_cnc_rdfeed(self, req_id: int) -> bytes:
        behavior = self._behaviors.get(self._default_device_id)
        feed = behavior._cnc_status.get("feed_rate", 500) if behavior else 500

        resp = bytearray()
        resp += struct.pack("<H", 0x0111)
        resp += struct.pack("<I", req_id)
        resp += struct.pack("<I", 0x00000000)
        resp += struct.pack("<d", float(feed))
        return bytes(resp)

    def _handle_cnc_alarm(self, req_id: int) -> bytes:
        behavior = self._behaviors.get(self._default_device_id)
        alarm = behavior._cnc_status.get("alarm", 0) if behavior else 0

        resp = bytearray()
        resp += struct.pack("<H", 0x0120)
        resp += struct.pack("<I", req_id)
        resp += struct.pack("<I", 0x00000000)
        resp += struct.pack("<H", alarm)
        if alarm > 0:
            resp += struct.pack("<H", 1)
            resp += struct.pack("<H", alarm)
            resp += struct.pack("<H", 1)
            resp += b"ALM\x00"
        else:
            resp += struct.pack("<H", 0)
        return bytes(resp)

    def _handle_cnc_program(self, req_id: int) -> bytes:
        behavior = self._behaviors.get(self._default_device_id)
        prog = behavior._cnc_status.get("program", "O0001") if behavior else "O0001"

        resp = bytearray()
        resp += struct.pack("<H", 0x0130)
        resp += struct.pack("<I", req_id)
        resp += struct.pack("<I", 0x00000000)
        prog_bytes = prog.encode("ascii", errors="replace")
        resp += struct.pack("<H", len(prog_bytes))
        resp += prog_bytes
        return bytes(resp)

    def _make_focas_error(self, req_id: int, error_code: int) -> bytes:
        resp = bytearray()
        resp += struct.pack("<H", 0xFFFF)
        resp += struct.pack("<I", req_id)
        resp += struct.pack("<I", error_code)
        return bytes(resp)

    async def create_device(self, device_config: DeviceConfig) -> str:
        behavior = FanucDeviceBehavior(device_config.points)
        self._behaviors[device_config.id] = behavior
        self._device_configs[device_config.id] = device_config
        self._update_default_device(device_config.id)

        proto_config = device_config.protocol_config or {}
        self._device_params[device_config.id] = {
            "cnc_type": proto_config.get("cnc_type", "0i-F"),
            "axis_count": proto_config.get("axis_count", 3),
        }

        axis_count = self._device_params[device_config.id]["axis_count"]
        for key in ["absolute_pos", "machine_pos", "relative_pos", "distance_pos"]:
            current = behavior._cnc_status[key]
            if len(current) < axis_count:
                behavior._cnc_status[key] = current + [0.0] * (axis_count - len(current))

        logger.info("FANUC device created: %s (cnc_type=%s, axis=%d)",
                     device_config.id,
                     self._device_params[device_config.id]["cnc_type"],
                     axis_count)
        self._log_debug("system", "device_create",
                        f"创建FANUC设备 {device_config.name}",
                        device_id=device_config.id)
        return device_config.id

    async def remove_device(self, device_id: str) -> None:
        self._behaviors.pop(device_id, None)
        self._device_configs.pop(device_id, None)
        self._device_params.pop(device_id, None)
        self._clear_default_device(device_id)
        logger.info("FANUC device removed: %s", device_id)
        self._log_debug("system", "device_remove",
                        f"移除FANUC设备 {device_id}",
                        device_id=device_id)

    async def read_points(self, device_id: str) -> list[PointValue]:
        behavior = self._behaviors.get(device_id)
        config = self._device_configs.get(device_id)
        if not behavior or not config:
            return []
        now = time.time()
        return [PointValue(name=p.name, value=behavior.get_value(p.name), timestamp=now) for p in config.points]

    async def write_point(self, device_id: str, point_name: str, value: Any) -> bool:
        behavior = self._behaviors.get(device_id)
        if not behavior:
            return False
        return await behavior.on_write(point_name, value)

    def get_config_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "host": {"type": "string", "default": "0.0.0.0", "description": "FOCAS 服务器监听地址"},
                "port": {"type": "integer", "default": 8193, "description": "FOCAS 端口 (默认8193)"},
            },
        }
