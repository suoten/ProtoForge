import asyncio
import logging
import re
import socket
from typing import Any, Optional

from protoforge.core.device import DeviceInstance
from protoforge.core.event_bus import EventBus, DeviceCreatedEvent, DeviceStartedEvent, DeviceStoppedEvent, DeviceRemovedEvent, ProtocolStatusEvent
from protoforge.core.generator import DataGenerator
from protoforge.core.scenario import Scenario
from protoforge.models.device import DeviceConfig, DeviceInfo, DeviceStatus, PointValue
from protoforge.models.scenario import ScenarioConfig, ScenarioDetail, ScenarioInfo, ScenarioStatus
from protoforge.protocols.base import ProtocolServer, ProtocolStatus

logger = logging.getLogger(__name__)

_VALID_ID_PATTERN = re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9_\-.]{0,127}$')


def _validate_entity_id(entity_id: str, entity_type: str = "Entity") -> None:
    if not entity_id or not isinstance(entity_id, str):
        raise ValueError(f"{entity_type} ID must be a non-empty string")
    if not _VALID_ID_PATTERN.match(entity_id):
        raise ValueError(
            f"{entity_type} ID '{entity_id}' is invalid. "
            "Must start with alphanumeric, contain only letters, digits, '_', '-', '.', max 128 chars"
        )


def _is_port_in_use(port: int, host: str = "0.0.0.0") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((host, port))
        except OSError:
            return True
    return False


def _is_serial_path(host: str) -> bool:
    return (host.startswith("/dev/tty") or
            host.startswith("/dev/serial") or
            host.upper().startswith("COM"))


def _find_free_port(start_port: int, host: str = "0.0.0.0", max_tries: int = 100) -> int:
    for offset in range(max_tries):
        port = start_port + offset
        if not _is_port_in_use(port, host):
            return port
    raise RuntimeError(f"No free port found in range {start_port}-{start_port + max_tries - 1}")


class SimulationEngine:
    def __init__(self, event_bus: EventBus | None = None, tick_interval: float = 1.0):
        self._protocol_servers: dict[str, ProtocolServer] = {}
        self._devices: dict[str, DeviceInstance] = {}
        self._scenarios: dict[str, ScenarioConfig] = {}
        self._scenario_instances: dict[str, Scenario] = {}
        self._scenario_status: dict[str, ScenarioStatus] = {}
        self._generator = DataGenerator()
        self._tick_task: Optional[asyncio.Task] = None
        self._running = False
        self._event_bus = event_bus
        self._tick_interval = tick_interval

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
        from protoforge.config import get_protocol_port_map
        port_map = get_protocol_port_map()
        result = []
        for name, server in self._protocol_servers.items():
            port_info = port_map.get(name, {})
            result.append({
                "name": server.protocol_name,
                "display_name": server.protocol_display_name,
                "description": getattr(server, 'protocol_description', ''),
                "version": getattr(server, 'protocol_version', '1.0.0'),
                "status": server.status.value,
                "default_port": port_info.get("port", 0),
                "config_schema": server.get_config_schema(),
            })
        return result

    def is_protocol_running(self, protocol_name: str) -> bool:
        server = self._protocol_servers.get(protocol_name)
        return server is not None and server.status == ProtocolStatus.RUNNING

    _MAX_START_RETRIES = 3
    _RETRY_DELAY_SECONDS = 2.0
    _RETRYABLE_ERRORS = ("connection refused", "timed out", "connection reset", "temporarily unavailable")

    async def start_protocol(self, protocol_name: str, config: dict[str, Any]) -> None:
        server = self._protocol_servers.get(protocol_name)
        if not server:
            raise ValueError(f"Unknown protocol: {protocol_name}")
        if server.status == ProtocolStatus.RUNNING:
            logger.info("Protocol %s is already running, skipping", protocol_name)
            return
        logger.info("Starting protocol %s with config: %s", protocol_name, {k: v for k, v in config.items() if k not in ("auth_password", "secret")})
        if "port" in config and isinstance(config["port"], int):
            if config["port"] < 1 or config["port"] > 65535:
                raise ValueError(f"Invalid port {config['port']}, must be between 1 and 65535")
            host = config.get("host", "0.0.0.0")
            if host and not _is_serial_path(host) and _is_port_in_use(config["port"], host):
                original_port = config["port"]
                new_port = _find_free_port(original_port + 1, host)
                logger.warning(
                    "Port %d is in use for %s, auto-switching to %d",
                    original_port, protocol_name, new_port,
                )
                config["port"] = new_port
                config["_port_changed"] = True
                config["_original_port"] = original_port

        last_error = None
        for attempt in range(1, self._MAX_START_RETRIES + 1):
            try:
                await server.start(config)
                for i in range(5):
                    await asyncio.sleep(0.2)
                    if server.status == ProtocolStatus.ERROR:
                        break
                if server.status == ProtocolStatus.ERROR:
                    port_info = ""
                    if "port" in config:
                        port_info = f" (port {config['port']})"
                    error_msg = f"Protocol server entered ERROR state after start{port_info}. Possible causes: port conflict, permission denied, or config error. Check server logs for details."
                    logger.error("Protocol %s: %s", protocol_name, error_msg)
                    try:
                        await server.stop()
                    except Exception as stop_err:
                        logger.warning("Error stopping protocol %s after ERROR state: %s", protocol_name, stop_err)
                    raise RuntimeError(f"Failed to start protocol {protocol_name}: {error_msg}")
                logger.info("Protocol %s started", protocol_name)
                for dev_id, instance in list(self._devices.items()):
                    if instance.protocol == protocol_name:
                        try:
                            await server.create_device(instance.config)
                            logger.info("Re-registered device %s to newly started protocol %s", dev_id, protocol_name)
                        except Exception as reg_err:
                            logger.debug("Device %s already registered or registration failed: %s", dev_id, reg_err)
                if self._event_bus:
                    await self._event_bus.publish_safe(ProtocolStatusEvent(
                        protocol_name=protocol_name,
                        old_status="stopped",
                        new_status="running",
                    ))
                return  # SUCCESS
            except Exception as e:
                last_error = e
                error_str = str(e).lower()
                is_retryable = any(err in error_str for err in self._RETRYABLE_ERRORS)
                if is_retryable and attempt < self._MAX_START_RETRIES:
                    logger.warning(
                        "Protocol %s start attempt %d/%d failed (retryable): %s — retrying in %.1fs",
                        protocol_name, attempt, self._MAX_START_RETRIES, e, self._RETRY_DELAY_SECONDS,
                    )
                    await asyncio.sleep(self._RETRY_DELAY_SECONDS)
                    continue
                else:
                    logger.error("Failed to start protocol %s: %s", protocol_name, e)
                    raise RuntimeError(f"Failed to start protocol {protocol_name}: {e}") from e

    async def stop_protocol(self, protocol_name: str) -> None:
        server = self._protocol_servers.get(protocol_name)
        if not server:
            raise ValueError(f"Unknown protocol: {protocol_name}")
        try:
            await server.stop()
            logger.info("Protocol %s stopped", protocol_name)
            if self._event_bus:
                await self._event_bus.publish_safe(ProtocolStatusEvent(
                    protocol_name=protocol_name,
                    old_status="running",
                    new_status="stopped",
                ))
        except Exception as e:
            logger.error("Failed to stop protocol %s: %s", protocol_name, e)
            raise RuntimeError(f"Failed to stop protocol {protocol_name}: {e}") from e

    async def create_device(self, config: DeviceConfig, allow_update: bool = False) -> DeviceInfo:
        if config.id in self._devices:
            if allow_update:
                logger.warning("Device %s already exists, updating instead", config.id)
                return await self.update_device(config.id, config)
            raise ValueError(f"Device '{config.id}' already exists. Use update_device() to modify it, or delete it first.")
        instance = DeviceInstance(config, self._generator)
        self._devices[config.id] = instance

        server = self._protocol_servers.get(config.protocol)
        if server and server.status == ProtocolStatus.RUNNING:
            try:
                await server.create_device(config)
                instance.start()
            except Exception as e:
                logger.warning("Failed to sync device %s to protocol server: %s", config.id, e)

        if self._event_bus:
            await self._event_bus.publish_safe(DeviceCreatedEvent(
                device_id=config.id,
                protocol=config.protocol,
                protocol_config=config.protocol_config or {},
            ))

        proto_config = config.protocol_config or {}
        edgelite_url = proto_config.get("edgelite_url", "")
        edgelite_enabled = proto_config.get("edgelite_enabled", False)
        skip_auto_push = proto_config.get("_skip_auto_push", False)

        should_push = False
        if edgelite_url and not skip_auto_push:
            should_push = True
        elif edgelite_enabled and not skip_auto_push:
            from protoforge.core.edgelite import get_global_edgelite_config
            global_el = get_global_edgelite_config()
            if global_el["url"]:
                should_push = True

        edgelite_result = None
        if should_push:
            try:
                from protoforge.core.edgelite import push_device_to_edgelite
                edgelite_result = await push_device_to_edgelite(config)
                if edgelite_result.get("ok"):
                    logger.info("Device %s auto-pushed to EdgeLite", config.id)
                else:
                    logger.warning("Device %s EdgeLite push failed: %s", config.id, edgelite_result.get("error") or edgelite_result.get("reason", "unknown"))
            except Exception as e:
                logger.warning("Device %s EdgeLite push error: %s", config.id, e)

        logger.info("Device created: %s (%s)", config.id, config.name)
        info = self._get_device_info(instance)
        if edgelite_result:
            info.edgelite_status = edgelite_result
        server = self._protocol_servers.get(config.protocol)
        if not server or server.status != ProtocolStatus.RUNNING:
            info.protocol_active = False
        else:
            info.protocol_active = True
        return info

    async def remove_device(self, device_id: str) -> None:
        instance = self._devices.pop(device_id, None)
        if not instance:
            raise ValueError(f"Device not found: {device_id}")

        server = self._protocol_servers.get(instance.protocol)
        if server and server.status == ProtocolStatus.RUNNING:
            try:
                await server.remove_device(device_id)
            except Exception as e:
                logger.warning("Failed to remove device %s from protocol server: %s", device_id, e)

        try:
            instance.stop()
        except Exception as e:
            logger.warning("Failed to stop device %s during removal: %s", device_id, e)

        proto_config = instance.config.protocol_config or {}
        edgelite_url = proto_config.get("edgelite_url", "")
        edgelite_enabled = proto_config.get("edgelite_enabled", False)

        should_remove = False
        if edgelite_url:
            should_remove = True
        elif edgelite_enabled:
            from protoforge.core.edgelite import get_global_edgelite_config
            global_el = get_global_edgelite_config()
            if global_el["url"]:
                should_remove = True

        if should_remove:
            try:
                from protoforge.core.edgelite import remove_device_from_edgelite
                result = await remove_device_from_edgelite(instance.config)
                if result.get("ok"):
                    logger.info("Device %s auto-removed from EdgeLite", device_id)
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
        was_running = instance.status == DeviceStatus.ONLINE
        if was_running:
            try:
                await self.stop_device(device_id)
            except Exception as e:
                logger.warning("Failed to stop device %s before update: %s", device_id, e)

        try:
            await self.remove_device(device_id)
        except Exception as e:
            logger.error("Failed to remove old device %s during update: %s", device_id, e)
            raise
        config.id = device_id
        try:
            result = await self.create_device(config)
            if was_running:
                try:
                    await self.start_device(device_id)
                except Exception as e:
                    logger.warning("Failed to restart device %s after update: %s", device_id, e)
            return result
        except Exception as e:
            logger.error("Failed to create new device %s during update: %s, restoring old", device_id, e)
            try:
                await self.create_device(old_config)
                if was_running:
                    try:
                        await self.start_device(device_id)
                    except Exception as restart_err:
                        logger.warning("Failed to restart restored device %s: %s", device_id, restart_err)
            except Exception as restore_err:
                logger.critical("Failed to restore old device %s: %s. Device may be lost!", device_id, restore_err)
            raise

    def get_all_device_ids(self) -> list[str]:
        return list(self._devices.keys())

    async def start_device(self, device_id: str) -> None:
        instance = self._devices.get(device_id)
        if not instance:
            raise ValueError(f"Device not found: {device_id}")
        if instance.status == DeviceStatus.ONLINE:
            return
        try:
            instance.start()
        except Exception as e:
            logger.error("Failed to start device %s: %s", device_id, e)
            raise
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
        try:
            instance.stop()
        except Exception as e:
            logger.error("Failed to stop device %s: %s", device_id, e)
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

    def get_all_device_instances(self) -> dict[str, DeviceInstance]:
        return dict(self._devices)

    def get_scenario_config(self, scenario_id: str) -> Optional[ScenarioConfig]:
        return self._scenarios.get(scenario_id)

    def get_all_scenario_configs(self) -> dict[str, ScenarioConfig]:
        return dict(self._scenarios)

    def get_scenario_status(self, scenario_id: str) -> ScenarioStatus:
        return self._scenario_status.get(scenario_id, ScenarioStatus.STOPPED)

    def get_all_protocol_servers(self) -> dict[str, ProtocolServer]:
        return dict(self._protocol_servers)

    def get_protocol_running_port(self, protocol_name: str) -> int | str | None:
        server = self._protocol_servers.get(protocol_name)
        if server and server.status == ProtocolStatus.RUNNING:
            return server.get_running_port()
        return None

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
        server = self._protocol_servers.get(instance.protocol)
        if server and server.status == ProtocolStatus.RUNNING:
            try:
                proto_points = await server.read_points(device_id)
                if proto_points:
                    proto_map = {p.name: p for p in proto_points}
                    memory_points = instance.read_all_points()
                    merged = []
                    for mp in memory_points:
                        if mp.name in proto_map:
                            merged.append(proto_map[mp.name])
                        else:
                            merged.append(mp)
                    return merged
            except Exception as e:
                logger.warning(
                    "Failed to read points from protocol server for %s, falling back to memory: %s",
                    device_id, e,
                )
        memory_points = instance.read_all_points()
        for p in memory_points:
            p.simulated = True
        return memory_points

    async def write_device_point(self, device_id: str, point_name: str, value: Any) -> bool:
        instance = self._devices.get(device_id)
        if not instance:
            raise ValueError(f"Device not found: {device_id}")

        old_value = None
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
                            try:
                                await instance.write_point(point_name, old_value)
                            except Exception as rollback_err:
                                logger.error("Rollback failed for %s/%s: %s", device_id, point_name, rollback_err)
                        logger.warning("Protocol write failed for %s/%s, rolled back", device_id, point_name)
                        return False
                except Exception as e:
                    if found:
                        try:
                            await instance.write_point(point_name, old_value)
                        except Exception as rollback_err:
                            logger.error("Rollback failed for %s/%s: %s", device_id, point_name, rollback_err)
                    logger.warning("Protocol write error for %s/%s: %s, rolled back", device_id, point_name, e)
                    return False
            else:
                logger.warning(
                    "Write to device %s/%s succeeded in memory, but protocol %s is not running - change not visible to external clients",
                    device_id, point_name, instance.protocol,
                )
        return success

    def create_scenario(self, config: ScenarioConfig) -> ScenarioInfo:
        _validate_entity_id(config.id, "Scenario")
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

        scenario = Scenario(config, on_write_point=self.write_device_point)
        self._scenario_status[scenario_id] = ScenarioStatus.STARTING
        created_device_ids: list[str] = []

        try:
            failed_devices = []
            for device_config in config.devices:
                if device_config.id not in self._devices:
                    try:
                        await self.create_device(device_config)
                        created_device_ids.append(device_config.id)
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
                raise RuntimeError(
                    f"All {len(config.devices)} devices failed to start in scenario '{scenario_id}'. "
                    f"Failed device IDs: {failed_devices}"
                )

            if failed_devices:
                logger.warning(
                    "Scenario %s started with %d/%d device failures: %s",
                    scenario_id, len(failed_devices), len(config.devices), failed_devices
                )

            scenario.start()
            self._scenario_status[scenario_id] = ScenarioStatus.RUNNING
            self._scenario_instances[scenario_id] = scenario
            logger.info("Scenario started: %s (failed devices: %s)", scenario_id, failed_devices or "none")
        except Exception as e:
            self._scenario_status[scenario_id] = ScenarioStatus.ERROR
            for dev_id in created_device_ids:
                try:
                    await self.remove_device(dev_id)
                    logger.info("Rolled back device %s after scenario start failure", dev_id)
                except Exception as rollback_err:
                    logger.warning("Failed to rollback device %s: %s", dev_id, rollback_err)
            logger.error("Failed to start scenario %s: %s", scenario_id, e)
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

    def get_scenario(self, scenario_id: str) -> ScenarioDetail:
        config = self._scenarios.get(scenario_id)
        if not config:
            raise ValueError(f"Scenario not found: {scenario_id}")
        status = self._scenario_status.get(scenario_id, ScenarioStatus.STOPPED)
        return ScenarioDetail(
            id=config.id,
            name=config.name,
            description=config.description,
            status=status,
            device_count=len(config.devices),
            rule_count=len(config.rules),
            devices=config.devices,
            rules=config.rules,
        )

    async def start(self) -> None:
        if self._tick_task and not self._tick_task.done():
            logger.warning("Engine already running, cancelling old tick task")
            self._tick_task.cancel()
            try:
                await self._tick_task
            except asyncio.CancelledError:
                pass
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
                try:
                    await server.stop()
                except Exception as e:
                    logger.warning("Error stopping protocol server %s: %s", server.protocol_name, e)
        for instance in self._devices.values():
            try:
                instance.stop()
            except Exception as e:
                logger.warning("Error stopping device %s: %s", instance.id, e)
        logger.info("Simulation engine stopped")

    async def _tick_loop(self) -> None:
        while self._running:
            for instance in list(self._devices.values()):
                try:
                    await instance.tick()
                except Exception as e:
                    logger.warning("Tick error for device %s: %s", instance.id, e)
            for scenario in list(self._scenario_instances.values()):
                try:
                    await scenario.tick()
                except Exception as e:
                    logger.warning("Tick error for scenario %s: %s", getattr(scenario.config, 'id', 'unknown') if scenario.config else 'unknown', e)
            await asyncio.sleep(self._tick_interval)

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
