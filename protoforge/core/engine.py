import asyncio
import logging
import socket
import time
from typing import Any, Optional

from protoforge.core.device import DeviceInstance
from protoforge.core.generator import DataGenerator
from protoforge.core.scenario import Scenario
from protoforge.models.device import DeviceConfig, DeviceInfo, DeviceStatus, PointValue
from protoforge.models.scenario import ScenarioConfig, ScenarioInfo, ScenarioStatus
from protoforge.protocols.base import ProtocolServer, ProtocolStatus

logger = logging.getLogger(__name__)


def _is_port_in_use(port: int, host: str = "0.0.0.0") -> bool:
    for sock_type in (socket.SOCK_STREAM, socket.SOCK_DGRAM):
        try:
            with socket.socket(socket.AF_INET, sock_type) as s:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                s.bind((host, port))
        except OSError:
            return True
    return False


def _find_free_port(start_port: int, host: str = "0.0.0.0", max_tries: int = 100) -> int:
    for offset in range(max_tries):
        port = start_port + offset
        if not _is_port_in_use(port, host):
            return port
    return start_port


class SimulationEngine:
    def __init__(self):
        self._protocol_servers: dict[str, ProtocolServer] = {}
        self._devices: dict[str, DeviceInstance] = {}
        self._scenarios: dict[str, ScenarioConfig] = {}
        self._scenario_instances: dict[str, Scenario] = {}
        self._scenario_status: dict[str, ScenarioStatus] = {}
        self._generator = DataGenerator()
        self._tick_task: Optional[asyncio.Task] = None
        self._running = False

    def register_protocol(self, server: ProtocolServer) -> None:
        self._protocol_servers[server.protocol_name] = server
        logger.info("Registered protocol: %s", server.protocol_name)

    def setup_debug_callbacks(self, log_bus) -> None:
        for name, server in self._protocol_servers.items():
            if hasattr(server, 'set_debug_callback'):
                def make_callback(proto_name):
                    def callback(direction, msg_type, summary, device_id="", detail=None):
                        log_bus.emit(
                            protocol=proto_name,
                            direction=direction,
                            device_id=device_id,
                            message_type=msg_type,
                            summary=summary,
                            detail=detail or {},
                        )
                    return callback
                server.set_debug_callback(make_callback(name))

    def get_protocols(self) -> list[dict[str, Any]]:
        result = []
        for name, server in self._protocol_servers.items():
            result.append({
                "name": server.protocol_name,
                "display_name": server.protocol_display_name,
                "status": server.status.value,
                "config_schema": server.get_config_schema(),
            })
        return result

    async def start_protocol(self, protocol_name: str, config: dict[str, Any]) -> None:
        server = self._protocol_servers.get(protocol_name)
        if not server:
            raise ValueError(f"Unknown protocol: {protocol_name}")
        if "port" in config and isinstance(config["port"], int):
            host = config.get("host", "0.0.0.0")
            if host and host not in ("/dev/ttyUSB0",) and _is_port_in_use(config["port"], host):
                original_port = config["port"]
                new_port = _find_free_port(original_port + 1, host)
                logger.warning(
                    "Port %d is in use for %s, auto-switching to %d",
                    original_port, protocol_name, new_port,
                )
                config = {**config, "port": new_port}
        await server.start(config)
        logger.info("Protocol %s started", protocol_name)

    async def stop_protocol(self, protocol_name: str) -> None:
        server = self._protocol_servers.get(protocol_name)
        if not server:
            raise ValueError(f"Unknown protocol: {protocol_name}")
        await server.stop()
        logger.info("Protocol %s stopped", protocol_name)

    async def create_device(self, config: DeviceConfig) -> DeviceInfo:
        instance = DeviceInstance(config, self._generator)
        self._devices[config.id] = instance

        server = self._protocol_servers.get(config.protocol)
        if server and server.status == ProtocolStatus.RUNNING:
            await server.create_device(config)
            instance.start()

        proto_config = config.protocol_config or {}
        edgelite_url = proto_config.get("edgelite_url", "")
        if edgelite_url:
            try:
                from protoforge.core.edgelite import push_device_to_edgelite
                result = await push_device_to_edgelite(instance)
                if result.get("ok"):
                    logger.info("Device %s auto-pushed to EdgeLite", config.id)
                else:
                    logger.warning("Device %s EdgeLite push failed: %s", config.id, result.get("error", result.get("reason", "")))
            except Exception as e:
                logger.warning("Device %s EdgeLite push error: %s", config.id, e)

        logger.info("Device created: %s (%s)", config.id, config.name)
        return self._get_device_info(instance)

    async def remove_device(self, device_id: str) -> None:
        instance = self._devices.pop(device_id, None)
        if not instance:
            raise ValueError(f"Device not found: {device_id}")

        server = self._protocol_servers.get(instance.protocol)
        if server and server.status == ProtocolStatus.RUNNING:
            await server.remove_device(device_id)

        instance.stop()
        logger.info("Device removed: %s", device_id)

    async def update_device(self, device_id: str, config: DeviceConfig) -> DeviceInfo:
        instance = self._devices.get(device_id)
        if not instance:
            raise ValueError(f"Device not found: {device_id}")

        await self.remove_device(device_id)
        config.id = device_id
        return await self.create_device(config)

    def get_all_device_ids(self) -> list[str]:
        return list(self._devices.keys())

    async def start_device(self, device_id: str) -> None:
        instance = self._devices.get(device_id)
        if not instance:
            raise ValueError(f"Device not found: {device_id}")
        if instance.status == DeviceStatus.ONLINE:
            return
        instance.start()
        server = self._protocol_servers.get(instance.protocol)
        if server and server.status == ProtocolStatus.RUNNING:
            try:
                await server.create_device(instance.config)
            except Exception as e:
                logger.warning("Failed to sync device %s to protocol server: %s", device_id, e)
        logger.info("Device started: %s", device_id)

    async def stop_device(self, device_id: str) -> None:
        instance = self._devices.get(device_id)
        if not instance:
            raise ValueError(f"Device not found: {device_id}")
        if instance.status != DeviceStatus.ONLINE:
            return
        instance.stop()
        server = self._protocol_servers.get(instance.protocol)
        if server and server.status == ProtocolStatus.RUNNING:
            try:
                await server.remove_device(device_id)
            except Exception as e:
                logger.warning("Failed to remove device %s from protocol server: %s", device_id, e)
        logger.info("Device stopped: %s", device_id)

    def get_device(self, device_id: str) -> DeviceInfo:
        instance = self._devices.get(device_id)
        if not instance:
            raise ValueError(f"Device not found: {device_id}")
        return self._get_device_info(instance)

    def list_devices(self, protocol: Optional[str] = None) -> list[DeviceInfo]:
        result = []
        for instance in self._devices.values():
            if protocol and instance.protocol != protocol:
                continue
            result.append(self._get_device_info(instance))
        return result

    async def read_device_points(self, device_id: str) -> list[PointValue]:
        instance = self._devices.get(device_id)
        if not instance:
            raise ValueError(f"Device not found: {device_id}")
        return instance.read_all_points()

    async def write_device_point(self, device_id: str, point_name: str, value: Any) -> bool:
        instance = self._devices.get(device_id)
        if not instance:
            raise ValueError(f"Device not found: {device_id}")
        success = instance.write_point(point_name, value)
        if success:
            server = self._protocol_servers.get(instance.protocol)
            if server and server.status == ProtocolStatus.RUNNING:
                await server.write_point(device_id, point_name, value)
        return success

    def create_scenario(self, config: ScenarioConfig) -> ScenarioInfo:
        self._scenarios[config.id] = config
        self._scenario_status[config.id] = ScenarioStatus.STOPPED
        logger.info("Scenario created: %s", config.id)
        return ScenarioInfo(
            id=config.id,
            name=config.name,
            description=config.description,
            status=ScenarioStatus.STOPPED,
            device_count=len(config.devices),
            rule_count=len(config.rules),
        )

    def remove_scenario(self, scenario_id: str) -> None:
        if scenario_id not in self._scenarios:
            raise ValueError(f"Scenario not found: {scenario_id}")
        if self._scenario_status.get(scenario_id) == ScenarioStatus.RUNNING:
            raise ValueError("Cannot delete a running scenario, stop it first")
        del self._scenarios[scenario_id]
        self._scenario_status.pop(scenario_id, None)
        logger.info("Scenario removed: %s", scenario_id)

    def update_scenario(self, scenario_id: str, config: ScenarioConfig) -> ScenarioInfo:
        if scenario_id not in self._scenarios:
            raise ValueError(f"Scenario not found: {scenario_id}")
        config.id = scenario_id
        self._scenarios[scenario_id] = config
        logger.info("Scenario updated: %s", scenario_id)
        status = self._scenario_status.get(scenario_id, ScenarioStatus.STOPPED)
        return ScenarioInfo(
            id=config.id,
            name=config.name,
            description=config.description,
            status=status,
            device_count=len(config.devices),
            rule_count=len(config.rules),
        )

    async def start_scenario(self, scenario_id: str) -> None:
        config = self._scenarios.get(scenario_id)
        if not config:
            raise ValueError(f"Scenario not found: {scenario_id}")

        scenario = Scenario(config)
        self._scenario_status[scenario_id] = ScenarioStatus.RUNNING

        for device_config in config.devices:
            if device_config.id not in self._devices:
                await self.create_device(device_config)

        for device_config in config.devices:
            instance = self._devices.get(device_config.id)
            if instance:
                scenario.add_device(instance)
            try:
                await self.start_device(device_config.id)
            except Exception as e:
                logger.warning("Failed to start device %s in scenario: %s", device_config.id, e)

        scenario.start()
        self._scenario_instances[scenario_id] = scenario
        logger.info("Scenario started: %s", scenario_id)

    async def stop_scenario(self, scenario_id: str) -> None:
        config = self._scenarios.get(scenario_id)
        if not config:
            raise ValueError(f"Scenario not found: {scenario_id}")

        scenario = self._scenario_instances.pop(scenario_id, None)
        if scenario:
            scenario.stop()

        self._scenario_status[scenario_id] = ScenarioStatus.STOPPED

        for device_config in config.devices:
            try:
                await self.stop_device(device_config.id)
            except Exception as e:
                logger.warning("Failed to stop device %s in scenario: %s", device_config.id, e)

        logger.info("Scenario stopped: %s", scenario_id)

    def list_scenarios(self) -> list[ScenarioInfo]:
        result = []
        for sid, config in self._scenarios.items():
            status = self._scenario_status.get(sid, ScenarioStatus.STOPPED)
            result.append(
                ScenarioInfo(
                    id=config.id,
                    name=config.name,
                    description=config.description,
                    status=status,
                    device_count=len(config.devices),
                    rule_count=len(config.rules),
                )
            )
        return result

    def get_scenario(self, scenario_id: str) -> ScenarioInfo:
        config = self._scenarios.get(scenario_id)
        if not config:
            raise ValueError(f"Scenario not found: {scenario_id}")
        status = self._scenario_status.get(scenario_id, ScenarioStatus.STOPPED)
        return ScenarioInfo(
            id=config.id,
            name=config.name,
            description=config.description,
            status=status,
            device_count=len(config.devices),
            rule_count=len(config.rules),
        )

    async def start(self) -> None:
        self._running = True
        self._tick_task = asyncio.create_task(self._tick_loop())
        logger.info("Simulation engine started")

    async def stop(self) -> None:
        self._running = False
        if self._tick_task:
            self._tick_task.cancel()
            try:
                await self._tick_task
            except asyncio.CancelledError:
                pass
        for server in self._protocol_servers.values():
            if server.status == ProtocolStatus.RUNNING:
                await server.stop()
        for instance in self._devices.values():
            instance.stop()
        logger.info("Simulation engine stopped")

    async def _tick_loop(self) -> None:
        while self._running:
            for instance in self._devices.values():
                instance.tick()
            for scenario in self._scenario_instances.values():
                scenario.tick()
            await asyncio.sleep(1.0)

    def _get_device_info(self, instance: DeviceInstance) -> DeviceInfo:
        return DeviceInfo(
            id=instance.id,
            name=instance.name,
            protocol=instance.protocol,
            template_id=instance.config.template_id,
            status=instance.status,
            points=instance.read_all_points(),
        )
