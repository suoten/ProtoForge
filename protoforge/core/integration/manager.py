import asyncio
import logging
import time
from typing import Any, Optional

from protoforge.core.event_bus import (
    EventBus,
    DeviceCreatedEvent,
    DeviceStartedEvent,
    DeviceStoppedEvent,
    DeviceRemovedEvent,
    IntegrationConnectionEvent,
    IntegrationHealthAlertEvent,
)
from protoforge.core.integration.channel import ChannelBase, HttpChannel, ChannelFactory, WebSocketChannel, ChannelManager
from protoforge.core.integration.protocol import ProtocolMapper, DataTypeMapper
from protoforge.core.integration.state import ConnectionStateMachine, ConnectionState
from protoforge.core.integration.retry import RetryPolicy, IntegrationError, NetworkError
from protoforge.core.integration.auth import IntegrationAuth
from protoforge.core.integration.metrics import IntegrationMetrics
from protoforge.core.integration.validator import MappingValidator

logger = logging.getLogger(__name__)


class AlarmReactionRule:
    def __init__(
        self,
        rule_id: str = "",
        source_device_id: str = "",
        alarm_severity: str = "",
        action: str = "stop_device",
        target_device_id: str = "",
        action_params: dict[str, Any] | None = None,
        enabled: bool = True,
    ):
        self.rule_id = rule_id
        self.source_device_id = source_device_id
        self.alarm_severity = alarm_severity
        self.action = action
        self.target_device_id = target_device_id
        self.action_params = action_params or {}
        self.enabled = enabled

    def matches(self, source_device_id: str, severity: str) -> bool:
        if not self.enabled:
            return False
        if self.source_device_id and self.source_device_id != source_device_id:
            return False
        if self.alarm_severity and self.alarm_severity != severity:
            return False
        return True


class IntegrationManager:
    def __init__(
        self,
        event_bus: EventBus,
        enabled: bool = False,
        edgelite_url: str = "",
        username: str = "admin",
        password: str = "",
    ):
        self._event_bus = event_bus
        self._enabled = enabled
        self._edgelite_url = edgelite_url
        self._username = username
        self._password = password
        self._channel: Optional[ChannelBase] = None
        self._auth: Optional[IntegrationAuth] = None
        self._state = ConnectionStateMachine(on_change=self._on_state_change)
        self._retry = RetryPolicy()
        self._metrics = IntegrationMetrics()
        self._protocol_mapper = ProtocolMapper()
        self._data_type_mapper = DataTypeMapper()
        self._validator = MappingValidator(self._protocol_mapper, self._data_type_mapper)
        self._device_status_cache: dict[str, str] = {}
        self._alarm_reaction_rules: list[AlarmReactionRule] = []
        self._backhaul_data: dict[str, list[dict[str, Any]]] = {}
        self._running = False

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def state(self) -> ConnectionStateMachine:
        return self._state

    @property
    def metrics(self) -> IntegrationMetrics:
        return self._metrics

    @property
    def protocol_mapper(self) -> ProtocolMapper:
        return self._protocol_mapper

    @property
    def data_type_mapper(self) -> DataTypeMapper:
        return self._data_type_mapper

    @property
    def validator(self) -> MappingValidator:
        return self._validator

    def configure(self, edgelite_url: str, username: str = "admin", password: str = "") -> None:
        self._edgelite_url = edgelite_url
        self._username = username
        self._password = password
        self._enabled = bool(edgelite_url)

    async def start(self) -> None:
        if not self._enabled or not self._edgelite_url:
            logger.info("IntegrationManager disabled, no EdgeLite URL configured")
            return

        self._running = True
        self._auth = IntegrationAuth(
            base_url=self._edgelite_url,
            username=self._username,
            password=self._password,
        )

        self._event_bus.on("DeviceCreatedEvent", self._on_device_created)
        self._event_bus.on("DeviceStartedEvent", self._on_device_started)
        self._event_bus.on("DeviceStoppedEvent", self._on_device_stopped)
        self._event_bus.on("DeviceRemovedEvent", self._on_device_removed)

        try:
            await self._connect()
        except Exception as e:
            self._cleanup_event_handlers()
            self._running = False
            logger.warning("IntegrationManager initial connection failed, cleaned up: %s", e)
            return

        logger.info("IntegrationManager started, target: %s", self._edgelite_url)

    def _cleanup_event_handlers(self) -> None:
        self._event_bus.off("DeviceCreatedEvent", self._on_device_created)
        self._event_bus.off("DeviceStartedEvent", self._on_device_started)
        self._event_bus.off("DeviceStoppedEvent", self._on_device_stopped)
        self._event_bus.off("DeviceRemovedEvent", self._on_device_removed)

    async def stop(self) -> None:
        self._running = False
        self._cleanup_event_handlers()

        if self._channel:
            await self._channel.close()
            self._channel = None
        if self._auth:
            await self._auth.close()
        logger.info("IntegrationManager stopped")

    async def _connect(self) -> None:
        if not await self._state.transition(ConnectionState.CONNECTING):
            logger.warning("Cannot transition to CONNECTING from current state: %s", self._state.state.value)
            return
        try:
            channel = ChannelFactory.create("http", base_url=self._edgelite_url, auth=self._auth)
            await channel.connect()
            self._channel = channel
            await self._state.transition(ConnectionState.CONNECTED)
            self._metrics.set_connected()
        except Exception as e:
            await self._state.transition(ConnectionState.DISCONNECTED)
            logger.warning("Connection failed: %s", e)

    async def _ensure_connected(self) -> bool:
        if self._channel and self._channel.is_connected:
            return True
        try:
            await self._connect()
            return self._channel is not None and self._channel.is_connected
        except Exception as e:
            logger.debug("Connection check failed: %s", e)
            return False

    async def push_device(self, device: Any, protoforge_host: str = "127.0.0.1") -> dict[str, Any]:
        if not self._enabled:
            return {"ok": False, "skipped": True, "reason": "Integration not enabled"}

        from protoforge.core.edgelite import convert_device_to_edgelite, get_edgelite_config_from_device
        payload = convert_device_to_edgelite(device, protoforge_host, self._protocol_mapper, self._data_type_mapper)
        if payload is None:
            return {"ok": False, "skipped": True, "reason": "Protocol not supported by EdgeLite"}

        points_data = getattr(device, "points", []) or []
        points_list = []
        for p in points_data:
            if hasattr(p, "model_dump"):
                points_list.append(p.model_dump())
            elif hasattr(p, "__dict__"):
                points_list.append(p.__dict__)
            else:
                points_list.append(p)

        report = self._validator.validate(
            device_id=payload.get("device_id", ""),
            protocol=payload.get("protocol", ""),
            points=points_list,
            driver_config=payload.get("config", {}),
        )
        if not report.compatible:
            return {"ok": False, "skipped": True, "reason": "Compatibility check failed", "report": report}

        start_time = time.time()
        try:
            if not await self._ensure_connected():
                return {"ok": False, "error": "Not connected to EdgeLite"}

            result = await self._retry.execute(
                self._channel.send,
                {"type": "push_device", "payload": payload},
            )
            latency_ms = (time.time() - start_time) * 1000
            if result and result.get("ok"):
                self._metrics.record_push_success(latency_ms)
            else:
                self._metrics.record_push_failure()
            return result or {"ok": False, "error": "No response"}
        except IntegrationError as e:
            self._metrics.record_push_failure()
            return {"ok": False, "error": str(e)}
        except Exception as e:
            self._metrics.record_push_failure()
            return {"ok": False, "error": str(e)}

    async def delete_device(self, device_id: str) -> dict[str, Any]:
        if not self._enabled or not await self._ensure_connected():
            return {"ok": False, "error": "Not connected"}
        try:
            return await self._channel.send({"type": "delete_device", "payload": {"device_id": device_id}})
        except Exception as e:
            return {"ok": False, "error": str(e)}

    async def batch_push(self, devices: list[Any], protoforge_host: str = "127.0.0.1", concurrency: int = 10) -> dict[str, Any]:
        if not self._enabled:
            return {"ok": False, "skipped": True, "reason": "Integration not enabled"}

        semaphore = asyncio.Semaphore(concurrency)
        results = {"total": len(devices), "success": 0, "failure": 0, "details": []}

        async def _push_one(dev: Any) -> dict[str, Any]:
            async with semaphore:
                return await self.push_device(dev, protoforge_host)

        tasks = [_push_one(d) for d in devices]
        task_results = await asyncio.gather(*tasks, return_exceptions=True)

        for r in task_results:
            if isinstance(r, Exception):
                results["failure"] += 1
                results["details"].append({"ok": False, "error": str(r)})
            elif r.get("ok"):
                results["success"] += 1
                results["details"].append(r)
            else:
                results["failure"] += 1
                results["details"].append(r)

        results["ok"] = results["failure"] == 0
        return results

    def add_alarm_reaction_rule(self, rule: AlarmReactionRule) -> None:
        self._alarm_reaction_rules.append(rule)
        logger.info("Added alarm reaction rule: %s", rule.rule_id)

    def remove_alarm_reaction_rule(self, rule_id: str) -> None:
        self._alarm_reaction_rules = [r for r in self._alarm_reaction_rules if r.rule_id != rule_id]

    def get_alarm_reaction_rules(self) -> list[AlarmReactionRule]:
        return list(self._alarm_reaction_rules)

    async def handle_backhaul_message(self, message: dict[str, Any]) -> None:
        msg_type = message.get("type", "")
        payload = message.get("payload", {})

        if msg_type == "device_status_changed":
            device_id = payload.get("device_id", "")
            new_status = payload.get("new_status", "")
            self._device_status_cache[device_id] = new_status
            self._metrics.record_sync_event()
            logger.info("Device %s status changed to %s (from EdgeLite)", device_id, new_status)

        elif msg_type == "device_fault":
            device_id = payload.get("device_id", "")
            logger.warning("Device %s fault reported from EdgeLite: %s", device_id, payload)

        elif msg_type == "point_data":
            device_id = payload.get("device_id", "")
            self._backhaul_data.setdefault(device_id, []).append({
                "point_name": payload.get("point_name", ""),
                "value": payload.get("value", 0.0),
                "quality": payload.get("quality", "good"),
                "timestamp": message.get("timestamp", time.time()),
            })
            if len(self._backhaul_data[device_id]) > 1000:
                self._backhaul_data[device_id] = self._backhaul_data[device_id][-1000:]
            self._metrics.record_data_backhaul()

        elif msg_type in ("alarm_fired", "alarm_recovered"):
            await self._handle_alarm_from_edgelite(payload, msg_type)
            self._metrics.record_alarm_forward()

    async def _handle_alarm_from_edgelite(self, payload: dict[str, Any], msg_type: str) -> None:
        source_device_id = payload.get("device_id", "")
        severity = payload.get("severity", "")
        logger.info("Alarm from EdgeLite: %s device=%s severity=%s", msg_type, source_device_id, severity)

        if msg_type == "alarm_fired":
            for rule in self._alarm_reaction_rules:
                if rule.matches(source_device_id, severity):
                    await self._execute_alarm_reaction(rule, payload)

    async def _execute_alarm_reaction(self, rule: AlarmReactionRule, alarm_payload: dict[str, Any]) -> None:
        target_id = rule.target_device_id or rule.source_device_id
        logger.info("Executing alarm reaction: rule=%s action=%s target=%s",
                    rule.rule_id, rule.action, target_id)

        if rule.action == "stop_device":
            if self._channel and self._channel.is_connected:
                try:
                    await self._channel.send({
                        "type": "device_control",
                        "payload": {"device_id": target_id, "action": "stop_collect"},
                    })
                except Exception as e:
                    logger.error("Alarm reaction stop_device failed: %s", e)

        elif rule.action == "inject_fault":
            if self._channel and self._channel.is_connected:
                try:
                    await self._channel.send({
                        "type": "device_control",
                        "payload": {
                            "device_id": target_id,
                            "action": "inject_fault",
                            "params": rule.action_params,
                        },
                    })
                except Exception as e:
                    logger.error("Alarm reaction inject_fault failed: %s", e)

        elif rule.action == "adjust_generator":
            logger.info("Adjust generator for %s: %s", target_id, rule.action_params)

    def get_backhaul_data(self, device_id: str = "", limit: int = 100) -> list[dict[str, Any]]:
        if device_id:
            data = self._backhaul_data.get(device_id, [])
            return data[-limit:]
        all_data = []
        for dev_id, entries in self._backhaul_data.items():
            all_data.extend(entries[-limit:])
        all_data.sort(key=lambda x: x.get("timestamp", 0), reverse=True)
        return all_data[:limit]

    def get_device_status_cache(self) -> dict[str, str]:
        return dict(self._device_status_cache)

    async def _on_device_created(self, event: DeviceCreatedEvent) -> None:
        proto_config = event.protocol_config or {}
        el_url = proto_config.get("edgelite_url", "")
        if not el_url:
            return
        logger.info("IntegrationManager: handling DeviceCreatedEvent for %s", event.device_id)

    async def _on_device_started(self, event: DeviceStartedEvent) -> None:
        if self._channel and self._channel.is_connected:
            try:
                await self._channel.send({
                    "type": "device_control",
                    "payload": {"device_id": event.device_id, "action": "start_collect"},
                })
                self._metrics.record_sync_event()
            except Exception as e:
                logger.warning("Failed to send start_collect for %s: %s", event.device_id, e)

    async def _on_device_stopped(self, event: DeviceStoppedEvent) -> None:
        if self._channel and self._channel.is_connected:
            try:
                await self._channel.send({
                    "type": "device_control",
                    "payload": {"device_id": event.device_id, "action": "stop_collect"},
                })
                self._metrics.record_sync_event()
            except Exception as e:
                logger.warning("Failed to send stop_collect for %s: %s", event.device_id, e)

    async def _on_device_removed(self, event: DeviceRemovedEvent) -> None:
        self._backhaul_data.pop(event.device_id, None)
        if self._channel and self._channel.is_connected:
            try:
                await self._channel.send({
                    "type": "delete_device",
                    "payload": {"device_id": event.device_id},
                })
                self._metrics.record_sync_event()
            except Exception as e:
                logger.warning("Failed to send delete_device for %s: %s", event.device_id, e)

    def _on_state_change(self, old_state: ConnectionState, new_state: ConnectionState) -> None:
        if new_state == ConnectionState.CONNECTED:
            self._metrics.set_connected()
        elif new_state == ConnectionState.DISCONNECTED:
            self._metrics.set_disconnected()

    def is_connected(self) -> bool:
        return self._channel is not None and self._channel.is_connected

    async def send_device_control(self, device_id: str, action: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self._channel or not self._channel.is_connected:
            raise IntegrationError("Not connected to EdgeLite")
        payload: dict[str, Any] = {"device_id": device_id, "action": action}
        if params:
            payload["params"] = params
        return await self._channel.send({"type": "device_control", "payload": payload})

    async def send_message(self, message: dict[str, Any]) -> dict[str, Any] | None:
        if not self._channel or not self._channel.is_connected:
            raise IntegrationError("Not connected to EdgeLite")
        return await self._channel.send(message)

    def get_status(self) -> dict[str, Any]:
        return {
            "enabled": self._enabled,
            "edgelite_url": self._edgelite_url,
            "connection_state": self._state.state.value,
            "metrics": self._metrics.to_dict(),
        }
