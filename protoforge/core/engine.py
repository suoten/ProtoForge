import asyncio
import logging
import socket
from typing import Any, Optional

from protoforge.core.device import DeviceInstance
from protoforge.core.event_bus import EventBus, DeviceCreatedEvent, DeviceStartedEvent, DeviceStoppedEvent, DeviceRemovedEvent
from protoforge.core.generator import DataGenerator
from protoforge.core.scenario import Scenario
from protoforge.models.device import DeviceConfig, DeviceInfo, DeviceStatus, PointValue
from protoforge.models.scenario import ScenarioConfig, ScenarioInfo, ScenarioStatus
from protoforge.protocols.base import ProtocolServer, ProtocolStatus

logger = logging.getLogger(__name__)


def _is_port_in_use(port: int, host: str = "0.0.0.0") -> bool:
    for sock_type in (socket.SOCK_STREAM,):
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
    raise RuntimeError(f"No free port found in range {start_port}-{start_port + max_tries - 1}")


class SimulationEngine:
    def __init__(self, event_bus: EventBus | None = None):
        self._protocol_servers: dict[str, ProtocolServer] = {}
        self._devices: dict[str, DeviceInstance] = {}
        self._scenarios: dict[str, ScenarioConfig] = {}
        self._scenario_instances: dict[str, Scenario] = {}
        self._scenario_status: dict[str, ScenarioStatus] = {}
        self._generator = DataGenerator()
        self._tick_task: Optional[asyncio.Task] = None
        self._running = False
        self._event_bus = event_bus

    def register_protocol(self, server: ProtocolServer) -> None:
        if server.protocol_name in self._protocol_servers:
            logger.warning("Protocol %s already registered, overwriting", server.protocol_name)
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
                "description": getattr(server, 'protocol_description', ''),
                "version": getattr(server, 'protocol_version', '1.0.0'),
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
                config["port"] = new_port
        await server.start(config)
        logger.info("Protocol %s started", protocol_name)

    async def stop_protocol(self, protocol_name: str) -> None:
        server = self._protocol_servers.get(protocol_name)
        if not server:
            raise ValueError(f"Unknown protocol: {protocol_name}")
        await server.stop()
        logger.info("Protocol %s stopped", protocol_name)

    async def create_device(self, config: DeviceConfig) -> DeviceInfo:
        if config.id in self._devices:
            logger.warning("Device %s already exists, removing old instance first", config.id)
            await self.remove_device(config.id)
        instance = DeviceInstance(config, self._generator)
        self._devices[config.id] = instance

        server = self._protocol_servers.get(config.protocol)
        if server and server.status == ProtocolStatus.RUNNING:
            await server.create_device(config)
            instance.start()

        if self._event_bus:
            await self._event_bus.publish_safe(DeviceCreatedEvent(
                device_id=config.id,
                protocol=config.protocol,
                protocol_config=config.protocol_config or {},
            ))

        proto_config = config.protocol_config or {}
        edgelite_url = proto_config.get("edgelite_url", "")
        skip_auto_push = proto_config.get("_skip_auto_push", False)
        if edgelite_url and not skip_auto_push:
            try:
                from protoforge.core.edgelite import push_device_to_edgelite
                result = await push_device_to_edgelite(config)
                if result.get("ok"):
                    logger.info("Device %s auto-pushed to EdgeLite: %s", config.id, edgelite_url)
                else:
                    logger.warning("Device %s EdgeLite push failed: %s", config.id, result.get("error") or result.get("reason", "unknown"))
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

        proto_config = instance.config.protocol_config or {}
        edgelite_url = proto_config.get("edgelite_url", "")
        if edgelite_url:
            try:
                from protoforge.core.edgelite import remove_device_from_edgelite
                result = await remove_device_from_edgelite(instance.config)
                if result.get("ok"):
                    logger.info("Device %s auto-removed from EdgeLite: %s", device_id, edgelite_url)
                else:
                    logger.warning("Device %s EdgeLite remove failed: %s", device_id, result.get("error") or result.get("reason", "unknown"))
            except Exception as e:
                logger.warning("Device %s EdgeLite remove error: %s", device_id, e)

        if self._event_bus:
            await self._event_bus.publish_safe(DeviceRemovedEvent(device_id=device_id))

        logger.info("Device removed: %s", device_id)

    async def update_device(self, device_id: str, config: DeviceConfig) -> DeviceInfo:
        instance = self._devices.get(device_id)
        if not instance:
            raise ValueError(f"Device not found: {device_id}")

        old_config = instance.config
        try:
            await self.remove_device(device_id)
        except Exception as e:
            logger.error("Failed to remove old device %s during update: %s", device_id, e)
            raise
        config.id = device_id
        try:
            return await self.create_device(config)
        except Exception as e:
            logger.error("Failed to create new device %s during update: %s, restoring old", device_id, e)
            try:
                await self.create_device(old_config)
            except Exception as restore_err:
                logger.error("Failed to restore old device %s: %s", device_id, restore_err)
            raise

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

        if self._event_bus:
            await self._event_bus.publish_safe(DeviceStartedEvent(device_id=device_id))

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

        if self._event_bus:
            await self._event_bus.publish_safe(DeviceStoppedEvent(device_id=device_id))

        logger.info("Device stopped: %s", device_id)

    def get_device(self, device_id: str) -> DeviceInfo:
        instance = self._devices.get(device_id)
        if not instance:
            raise ValueError(f"Device not found: {device_id}")
        return self._get_device_info(instance)

    def get_device_instance(self, device_id: str) -> Optional[DeviceInstance]:
        return self._devices.get(device_id)

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

        _SENTINEL = object()
        old_value = _SENTINEL
        found = False
        for pv in instance.read_all_points():
            if pv.name == point_name:
                old_value = pv.value
                found = True
                break

        success = await instance.write_point(point_name, value)
        if success:
            server = self._protocol_servers.get(instance.protocol)
            if server and server.status == ProtocolStatus.RUNNING:
                try:
                    proto_success = await server.write_point(device_id, point_name, value)
                    if not proto_success:
                        if found:
                            await instance.write_point(point_name, old_value)
                        logger.warning("Protocol write failed for %s/%s, rolled back", device_id, point_name)
                        return False
                except Exception as e:
                    if found:
                        await instance.write_point(point_name, old_value)
                    logger.warning("Protocol write error for %s/%s: %s, rolled back", device_id, point_name, e)
                    return False
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
        status = self._scenario_status.get(scenario_id)
        if status in (ScenarioStatus.RUNNING, ScenarioStatus.STARTING):
            raise ValueError("Cannot delete a running or starting scenario, stop it first")
        del self._scenarios[scenario_id]
        self._scenario_status.pop(scenario_id, None)
        logger.info("Scenario removed: %s", scenario_id)

    def update_scenario(self, scenario_id: str, config: ScenarioConfig) -> ScenarioInfo:
        if scenario_id not in self._scenarios:
            raise ValueError(f"Scenario not found: {scenario_id}")
        config.id = scenario_id
        self._scenarios[scenario_id] = config
        instance = self._scenario_instances.get(scenario_id)
        if instance and hasattr(instance, 'config'):
            instance.config = config
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
        self._scenario_status[scenario_id] = ScenarioStatus.STARTING

        try:
            failed_devices = []
            for device_config in config.devices:
                if device_config.id not in self._devices:
                    try:
                        await self.create_device(device_config)
                    except Exception as e:
                        logger.warning("Failed to create device %s in scenario: %s", device_config.id, e)
                        failed_devices.append(device_config.id)

            for device_config in config.devices:
                if device_config.id in failed_devices:
                    continue
                instance = self._devices.get(device_config.id)
                if instance:
                    scenario.add_device(instance)
                try:
                    await self.start_device(device_config.id)
                except Exception as e:
                    logger.warning("Failed to start device %s in scenario: %s", device_config.id, e)
                    failed_devices.append(device_config.id)

            if failed_devices and len(failed_devices) == len(config.devices):
                self._scenario_status[scenario_id] = ScenarioStatus.ERROR
                logger.error("All devices failed in scenario %s", scenario_id)
                return

            if failed_devices:
                logger.warning(
                    "Scenario %s started with %d/%d device failures: %s",
                    scenario_id, len(failed_devices), len(config.devices), failed_devices
                )

            scenario.start()
            self._scenario_status[scenario_id] = ScenarioStatus.RUNNING
            self._scenario_instances[scenario_id] = scenario
            logger.info("Scenario started: %s (failed devices: %s)", scenario_id, failed_devices or "none")
        except Exception:
            self._scenario_status[scenario_id] = ScenarioStatus.ERROR
            raise

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
            for instance in list(self._devices.values()):
                await instance.tick()
            for scenario in list(self._scenario_instances.values()):
                await scenario.tick()
            await asyncio.sleep(1.0)

    def _get_device_info(self, instance: DeviceInstance) -> DeviceInfo:
        return DeviceInfo(
            id=instance.id,
            name=instance.name,
            protocol=instance.protocol,
            template_id=instance.config.template_id,
            status=instance.status,
            points=instance.read_all_points(),
            protocol_config=instance.config.protocol_config,
        )
