import asyncio
import logging
import struct
import time
from typing import Any

from protoforge.models.device import DeviceConfig, PointValue
from protoforge.protocols.base import DeviceBehavior, ProtocolServer, ProtocolStatus

logger = logging.getLogger(__name__)


class ToledoDeviceBehavior(DeviceBehavior):
    def __init__(self, points: list = None):
        self._points: dict[str, Any] = {}
        self._values: dict[str, Any] = {}
        self._weight = 0.0
        self._tare = 0.0
        self._unit = "kg"
        self._stable = True
        self._zero = True
        if points:
            for p in points:
                name = p.name if hasattr(p, 'name') else p.get("name", "")
                fixed_val = p.fixed_value if hasattr(p, 'fixed_value') else p.get("fixed_value")
                val = fixed_val if fixed_val is not None else 0
                self._points[name] = p
                self._values[name] = val
                if name == "weight":
                    self._weight = float(val)
                elif name == "tare":
                    self._tare = float(val)

    async def generate_value(self, point_config: dict[str, Any]) -> Any:
        name = point_config.get("name", "")
        return self._values.get(name, 0)

    async def on_write(self, point_name: str, value: Any) -> bool:
        if point_name in self._values:
            self._values[point_name] = value
            if point_name == "weight":
                self._weight = float(value)
            elif point_name == "tare":
                self._tare = float(value)
            return True
        return False

    def set_value(self, point_name: str, value: Any) -> None:
        self._values[point_name] = value
        if point_name == "weight":
            self._weight = float(value)
        elif point_name == "tare":
            self._tare = float(value)

    def get_value(self, point_name: str) -> Any:
        return self._values.get(point_name, 0)

    def get_weight_string(self) -> str:
        net = self._weight - self._tare
        sign = " " if net >= 0 else "-"
        abs_net = abs(net)
        stable_flag = " " if self._stable else "U"
        zero_flag = "Z" if self._zero else " "
        return f"{sign}{abs_net:08.3f}{self.unit_code()}{stable_flag}{zero_flag}\r\n"

    def unit_code(self) -> str:
        codes = {"kg": "kg", "g": "g ", "lb": "lb", "oz": "oz", "t": "t "}
        return codes.get(self._unit, "kg")

    def get_net_weight(self) -> float:
        return self._weight - self._tare


class ToledoServer(ProtocolServer):
    protocol_name = "toledo"
    protocol_display_name = "Mettler-Toledo"

    STX = 0x02
    ETX = 0x03
    CR = 0x0D
    LF = 0x0A

    def __init__(self):
        super().__init__()
        self._behaviors: dict[str, ToledoDeviceBehavior] = {}
        self._device_configs: dict[str, DeviceConfig] = {}
        self._host = "0.0.0.0"
        self._port = 1701
        self._server_task: asyncio.Task | None = None
        self._server_running = False
        self._continuous_mode = False
        self._continuous_task: asyncio.Task | None = None
        self._continuous_writers: set[asyncio.StreamWriter] = set()

    async def start(self, config: dict[str, Any]) -> None:
        self._status = ProtocolStatus.STARTING
        self._host = config.get("host", "0.0.0.0")
        self._port = config.get("port", 1701)
        try:
            self._server_running = True
            self._server_task = asyncio.create_task(self._serve())
            self._status = ProtocolStatus.RUNNING
            logger.info("Toledo server started on %s:%d", self._host, self._port)
            self._log_debug("system", "server_start",
                            f"Toledo服务启动 {self._host}:{self._port}",
                            detail={"host": self._host, "port": self._port})
        except Exception as e:
            self._status = ProtocolStatus.ERROR
            logger.error("Failed to start Toledo server: %s", e)
            raise

    async def stop(self) -> None:
        try:
            self._server_running = False
            self._continuous_mode = False
            if self._continuous_task:
                self._continuous_task.cancel()
                try:
                    await self._continuous_task
                except asyncio.CancelledError:
                    pass
                self._continuous_task = None
            for w in list(self._continuous_writers):
                try:
                    w.close()
                except Exception:
                    pass
            self._continuous_writers.clear()
            if self._server_task:
                self._server_task.cancel()
                try:
                    await self._server_task
                except asyncio.CancelledError:
                    pass
        except Exception as e:
            logger.warning("Toledo server stop error: %s", e)
        finally:
            self._status = ProtocolStatus.STOPPED
            logger.info("Toledo server stopped")
            self._log_debug("system", "server_stop", "Toledo服务停止")

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
            logger.error("Toledo server error: %s", e)
            self._status = ProtocolStatus.ERROR

    async def _handle_connection(self, reader: asyncio.StreamReader,
                                  writer: asyncio.StreamWriter) -> None:
        addr = writer.get_extra_info("peername")
        logger.debug("Toledo connection from %s", addr)
        try:
            while self._server_running:
                data = await reader.read(1024)
                if not data:
                    break
                response = self._process_toledo(data, writer)
                if response:
                    writer.write(response)
                    await writer.drain()
        except (ConnectionResetError, asyncio.CancelledError):
            pass
        finally:
            self._continuous_writers.discard(writer)
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    def _process_toledo(self, data: bytes, writer: asyncio.StreamWriter = None) -> bytes | None:
        if not data:
            return None

        cmd = data[0]

        if cmd == self.STX:
            return self._handle_stx_command(data, writer)
        elif cmd == ord("S") or cmd == ord("s"):
            return self._handle_stable_weight()
        elif cmd == ord("T") or cmd == ord("t"):
            return self._handle_tare()
        elif cmd == ord("Z") or cmd == ord("z"):
            return self._handle_zero()
        elif cmd == ord("P") or cmd == ord("p"):
            return self._handle_print_weight()
        elif cmd == ord("I"):
            return self._handle_immediate()
        elif cmd == ord("C"):
            return self._handle_continuous_start(writer)
        elif cmd == ord("D"):
            return self._handle_continuous_stop(writer)

        return self._handle_print_weight()

    def _handle_stx_command(self, data: bytes, writer: asyncio.StreamWriter = None) -> bytes:
        if len(data) < 2:
            return self._handle_print_weight()

        sub_cmd = data[1] if len(data) > 1 else 0
        if sub_cmd == ord("S"):
            return self._handle_stable_weight()
        elif sub_cmd == ord("T"):
            return self._handle_tare()
        elif sub_cmd == ord("Z"):
            return self._handle_zero()
        elif sub_cmd == ord("P"):
            return self._handle_print_weight()
        elif sub_cmd == ord("C"):
            return self._handle_continuous_start(writer)
        elif sub_cmd == ord("D"):
            return self._handle_continuous_stop(writer)

        return self._handle_print_weight()

    def _handle_stable_weight(self) -> bytes:
        behavior = self._behaviors.get(self._default_device_id)
        if not behavior:
            return b"   0.000kg \r\n"
        return behavior.get_weight_string().encode("ascii")

    def _handle_tare(self) -> bytes:
        behavior = self._behaviors.get(self._default_device_id)
        if behavior:
            behavior._tare = behavior._weight
        return self._handle_stable_weight()

    def _handle_zero(self) -> bytes:
        behavior = self._behaviors.get(self._default_device_id)
        if behavior:
            behavior._weight = 0.0
            behavior._tare = 0.0
            behavior._zero = True
        return self._handle_stable_weight()

    def _handle_print_weight(self) -> bytes:
        return self._handle_stable_weight()

    def _handle_immediate(self) -> bytes:
        return self._handle_stable_weight()

    def _handle_continuous_start(self, writer: asyncio.StreamWriter = None) -> bytes:
        self._continuous_mode = True
        if writer:
            self._continuous_writers.add(writer)
        if self._continuous_writers and (self._continuous_task is None or self._continuous_task.done()):
            self._continuous_task = asyncio.create_task(self._continuous_send())
        return self._handle_stable_weight()

    def _handle_continuous_stop(self, writer: asyncio.StreamWriter = None) -> bytes:
        if writer:
            self._continuous_writers.discard(writer)
        if not self._continuous_writers:
            self._continuous_mode = False
            if self._continuous_task:
                self._continuous_task.cancel()
                self._continuous_task = None
        return self._handle_stable_weight()

    async def _continuous_send(self) -> None:
        try:
            while self._server_running and self._continuous_writers:
                behavior = self._behaviors.get(self._default_device_id)
                if behavior:
                    weight_str = behavior.get_weight_string().encode("ascii")
                    dead_writers = []
                    for w in self._continuous_writers:
                        try:
                            w.write(weight_str)
                            await w.drain()
                        except Exception:
                            dead_writers.append(w)
                    for w in dead_writers:
                        self._continuous_writers.discard(w)
                        try:
                            w.close()
                        except Exception:
                            pass
                await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("Toledo continuous send error: %s", e)

    async def create_device(self, device_config: DeviceConfig) -> str:
        behavior = ToledoDeviceBehavior(device_config.points)
        self._behaviors[device_config.id] = behavior
        self._device_configs[device_config.id] = device_config
        self._update_default_device(device_config.id)

        proto_config = device_config.protocol_config or {}
        scale_addr = proto_config.get("scale_addr", "1")
        unit = proto_config.get("unit", "kg")
        behavior._unit = unit

        logger.info("Toledo device created: %s (addr=%s, unit=%s)",
                     device_config.id, scale_addr, unit)
        self._log_debug("system", "device_create",
                        f"创建Toledo设备 {device_config.name}",
                        device_id=device_config.id)
        return device_config.id

    async def remove_device(self, device_id: str) -> None:
        self._behaviors.pop(device_id, None)
        self._device_configs.pop(device_id, None)
        self._clear_default_device(device_id)
        logger.info("Toledo device removed: %s", device_id)
        self._log_debug("system", "device_remove",
                        f"移除Toledo设备 {device_id}",
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
                "host": {"type": "string", "default": "0.0.0.0", "description": "Toledo 服务器监听地址"},
                "port": {"type": "integer", "default": 1701, "description": "Toledo 端口 (默认1701)"},
            },
        }
