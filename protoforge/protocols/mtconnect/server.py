import asyncio
import contextlib
import logging
import time
import uuid
from typing import Any
from xml.sax.saxutils import escape

from protoforge.models.device import DeviceConfig, PointValue
from protoforge.protocols.behavior import DefaultDeviceBehavior as DeviceBehavior
from protoforge.protocols.behavior import DynamicValueGenerator, ProtocolServer, ProtocolStatus

logger = logging.getLogger(__name__)


class MtConnectDeviceBehavior(DeviceBehavior):
    def __init__(self, points: list = None):
        self._points: dict[str, Any] = {}
        self._values: dict[str, Any] = {}
        self._generators: dict[str, DynamicValueGenerator] = {}
        if points:
            for p in points:
                name = p.name if hasattr(p, 'name') else p.get("name", "")
                fixed_val = p.fixed_value if hasattr(p, 'fixed_value') else p.get("fixed_value")
                self._points[name] = p
                self._values[name] = fixed_val if fixed_val is not None else 0
                self._generators[name] = DynamicValueGenerator(p)

    def generate_value(self, point_config: dict[str, Any]) -> Any:
        name = point_config.get("name", "")
        return self._values.get(name, 0)

    def on_write(self, point_name: str, value: Any) -> bool:
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

    def get_all_values(self) -> dict[str, Any]:
        return dict(self._values)


class MtConnectServer(ProtocolServer):
    protocol_name = "mtconnect"
    protocol_display_name = "MTConnect"

    def __init__(self):
        super().__init__()
        self._behaviors: dict[str, MtConnectDeviceBehavior] = {}
        self._device_configs: dict[str, DeviceConfig] = {}
        self._device_params: dict[str, dict] = {}
        self._host = "0.0.0.0"
        self._port = 7878
        self._instance_id = int(time.time())
        self._sequence = 1
        self._last_values: dict[str, Any] = {}
        self._server_task: asyncio.Task | None = None
        self._server_running = False
        self._device_uuid = str(uuid.uuid4())
        self._sample_buffer: list[dict] = []
        self._sample_buffer_max = 131072
        self._first_sequence = 1

    async def start(self, config: dict[str, Any]) -> None:
        self._status = ProtocolStatus.STARTING
        self._host = config.get("host", "0.0.0.0")
        self._port = config.get("port", 7878)
        try:
            self._server_running = True
            self._server_task = asyncio.create_task(self._serve())
            self._status = ProtocolStatus.RUNNING
            logger.info("MTConnect server started on %s:%d", self._host, self._port)
            self._log_debug("system", "server_start",
                            f"MTConnect服务启动 {self._host}:{self._port}",
                            detail={"host": self._host, "port": self._port})
        except Exception as e:
            self._status = ProtocolStatus.ERROR
            logger.error("Failed to start MTConnect server: %s", e)
            raise

    async def stop(self) -> None:
        try:
            self._server_running = False
            if self._server_task:
                self._server_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self._server_task
        except Exception as e:
            logger.warning("MTConnect server stop error: %s", e)
        finally:
            self._status = ProtocolStatus.STOPPED
            logger.info("MTConnect server stopped")
            self._log_debug("system", "server_stop", "MTConnect服务停止")

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
            logger.error("MTConnect server error: %s", e)
            self._status = ProtocolStatus.ERROR

    async def _handle_connection(self, reader: asyncio.StreamReader,
                                  writer: asyncio.StreamWriter) -> None:
        addr = writer.get_extra_info("peername")
        logger.debug("MTConnect connection from %s", addr)
        try:
            while self._server_running:
                data = await reader.read(8192)
                if not data:
                    break
                try:
                    request = data.decode("utf-8", errors="replace")
                except Exception as e:
                    logger.debug("Data decode error: %s", e)
                    break

                response = self._process_http(request)
                if response:
                    writer.write(response.encode("utf-8"))
                    await writer.drain()
                break
        except (ConnectionResetError, asyncio.CancelledError):
            pass
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception as e:
                logger.debug("Writer wait_closed error: %s", e)

    def _process_http(self, request: str) -> str | None:
        lines = request.split("\r\n")
        if not lines:
            return None

        parts = lines[0].split(" ")
        if len(parts) < 2:
            return None

        method = parts[0]
        path = parts[1]

        path_parts = path.split("?", 1)
        path_base = path_parts[0]
        query_params = {}
        if len(path_parts) > 1:
            for kv in path_parts[1].split("&"):
                if "=" in kv:
                    k, v = kv.split("=", 1)
                    query_params[k] = v

        if method == "GET":
            if path_base == "/probe" or path_base == "/" or path_base.startswith("/probe"):
                return self._make_http_response(self._build_probe())
            elif path_base == "/current" or path_base.startswith("/current"):
                return self._make_http_response(self._build_current())
            elif path_base == "/sample" or path_base.startswith("/sample"):
                from_seq = int(query_params.get("from", 0))
                count = int(query_params.get("count", 100))
                return self._make_http_response(self._build_sample(from_seq, count))
            elif path_base.startswith("/asset"):
                asset_id = query_params.get("id", "")
                count = int(query_params.get("count", 100))
                return self._make_http_response(self._build_assets(asset_id, count))

        return self._make_http_response(self._build_error("UNSUPPORTED", f"Path {path} not supported"), status=404)

    def _build_probe(self) -> str:
        devices_xml = []
        for dev_id, config in self._device_configs.items():
            params = self._device_params.get(dev_id, {})
            dev_uuid = params.get("device_uuid", self._device_uuid)
            manufacturer = params.get("manufacturer", "ProtoForge")
            data_items = []
            for point in config.points:
                data_items.append(
                    f'      <DataItem id="{escape(point.name)}" name="{escape(point.name)}" '
                    f'type="{escape(point.data_type.value if hasattr(point.data_type, "value") else str(point.data_type))}" '
                    f'category="SAMPLE"/>'
                )
            devices_xml.append(
                f'  <Device id="{escape(dev_id)}" name="{escape(config.name)}" uuid="{escape(dev_uuid)}">\n'
                f'    <Description manufacturer="{escape(manufacturer)}">Simulated Device</Description>\n'
                f'    <DataItems>\n'
                + "\n".join(data_items) + "\n"
                '    </DataItems>\n'
                '  </Device>'
            )

        return (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<MTConnectDevices xmlns="urn:mtconnect.org:MTConnectDevices:1.3">\n'
            f'  <Header creationTime="{time.strftime("%Y-%m-%dT%H:%M:%SZ")}" '
            f'instanceId="{self._instance_id}" '
            f'sender="ProtoForge" '
            f'bufferSize="131072" '
            f'version="1.3.0"/>\n'
            '<Devices>\n'
            + "\n".join(devices_xml) + "\n"
            '</Devices>\n'
            '</MTConnectDevices>'
        )

    def _build_current(self) -> str:
        streams_xml = []
        for dev_id, behavior in self._behaviors.items():
            config = self._device_configs.get(dev_id)
            if not config:
                continue
            params = self._device_params.get(dev_id, {})
            dev_uuid = params.get("device_uuid", self._device_uuid)
            events = []
            for point in config.points:
                val = behavior.get_value(point.name)
                value_key = f"{dev_id}.{point.name}"
                if val != self._last_values.get(value_key):
                    self._sequence += 1
                    self._last_values[value_key] = val
                    self._sample_buffer.append({
                        "sequence": self._sequence,
                        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "data_item_id": point.name,
                        "device_id": dev_id,
                        "device_uuid": dev_uuid,
                        "device_name": config.name,
                        "value": val,
                    })
                    if len(self._sample_buffer) > self._sample_buffer_max:
                        self._sample_buffer = self._sample_buffer[-self._sample_buffer_max:]
                        self._first_sequence = self._sample_buffer[0]["sequence"]
                events.append(
                    f'      <{escape(point.name)} dataItemId="{escape(point.name)}" '
                    f'sequence="{self._sequence}" timestamp="{time.strftime("%Y-%m-%dT%H:%M:%SZ")}">'
                    f'{escape(str(val))}</{escape(point.name)}>'
                )
            streams_xml.append(
                f'  <DeviceStream name="{escape(config.name)}" uuid="{escape(dev_uuid)}">\n'
                f'    <ComponentStream component="Device" name="{escape(config.name)}">\n'
                f'      <Samples>\n'
                + "\n".join(events) + "\n"
                '      </Samples>\n'
                '    </ComponentStream>\n'
                '  </DeviceStream>'
            )

        return (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<MTConnectStreams xmlns="urn:mtconnect.org:MTConnectStreams:1.3">\n'
            f'  <Header creationTime="{time.strftime("%Y-%m-%dT%H:%M:%SZ")}" '
            f'instanceId="{self._instance_id}" '
            f'sender="ProtoForge" '
            f'bufferSize="{self._sample_buffer_max}" '
            f'nextSequence="{self._sequence + 1}" '
            f'lastSequence="{self._sequence}" '
            f'firstSequence="{self._first_sequence}" '
            f'version="1.3.0"/>\n'
            '<Streams>\n'
            + "\n".join(streams_xml) + "\n"
            '</Streams>\n'
            '</MTConnectStreams>'
        )

    def _build_sample(self, from_seq: int = 0, count: int = 100) -> str:
        if from_seq > 0 and self._sample_buffer:
            filtered = [e for e in self._sample_buffer if e["sequence"] >= from_seq]
            entries = filtered[:count]
        elif self._sample_buffer:
            entries = self._sample_buffer[-count:]
        else:
            entries = []

        if not entries:
            return (
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                '<MTConnectStreams xmlns="urn:mtconnect.org:MTConnectStreams:1.3">\n'
                f'  <Header creationTime="{time.strftime("%Y-%m-%dT%H:%M:%SZ")}" '
                f'instanceId="{self._instance_id}" '
                f'sender="ProtoForge" '
                f'bufferSize="{self._sample_buffer_max}" '
                f'nextSequence="{self._sequence + 1}" '
                f'lastSequence="{self._sequence}" '
                f'firstSequence="{self._first_sequence}" '
                f'version="1.3.0"/>\n'
                '<Streams/>\n'
                '</MTConnectStreams>'
            )

        device_events: dict[str, list] = {}
        device_info: dict[str, dict] = {}
        for entry in entries:
            did = entry["device_id"]
            if did not in device_events:
                device_events[did] = []
                device_info[did] = {
                    "name": entry["device_name"],
                    "uuid": entry["device_uuid"],
                }
            device_events[did].append(entry)

        streams_xml = []
        for did, events in device_events.items():
            info = device_info[did]
            samples_xml = []
            for e in events:
                samples_xml.append(
                    f'      <{escape(e["data_item_id"])} dataItemId="{escape(e["data_item_id"])}" '
                    f'sequence="{e["sequence"]}" timestamp="{e["timestamp"]}">'
                    f'{escape(str(e["value"]))}</{escape(e["data_item_id"])}>'
                )
            streams_xml.append(
                f'  <DeviceStream name="{escape(info["name"])}" uuid="{escape(info["uuid"])}">\n'
                f'    <ComponentStream component="Device" name="{escape(info["name"])}">\n'
                f'      <Samples>\n'
                + "\n".join(samples_xml) + "\n"
                '      </Samples>\n'
                '    </ComponentStream>\n'
                '  </DeviceStream>'
            )

        first_seq = entries[0]["sequence"]
        last_seq = entries[-1]["sequence"]
        return (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<MTConnectStreams xmlns="urn:mtconnect.org:MTConnectStreams:1.3">\n'
            f'  <Header creationTime="{time.strftime("%Y-%m-%dT%H:%M:%SZ")}" '
            f'instanceId="{self._instance_id}" '
            f'sender="ProtoForge" '
            f'bufferSize="{self._sample_buffer_max}" '
            f'nextSequence="{last_seq + 1}" '
            f'lastSequence="{last_seq}" '
            f'firstSequence="{first_seq}" '
            f'version="1.3.0"/>\n'
            '<Streams>\n'
            + "\n".join(streams_xml) + "\n"
            '</Streams>\n'
            '</MTConnectStreams>'
        )

    def _build_assets(self, asset_id: str = "", count: int = 100) -> str:
        assets_xml = []
        for dev_id, config in self._device_configs.items():
            params = self._device_params.get(dev_id, {})
            dev_uuid = params.get("device_uuid", self._device_uuid)
            manufacturer = params.get("manufacturer", "ProtoForge")
            asset_uuid = f"PF-{dev_id}"
            if asset_id and asset_uuid != asset_id:
                continue
            description_items = []
            for point in config.points:
                dt_val = point.data_type.value if hasattr(point.data_type, "value") else str(point.data_type)
                description_items.append(
                    f'        <DataItemDescription id="{escape(point.name)}" name="{escape(point.name)}" '
                    f'type="{escape(dt_val)}" category="SAMPLE" units="{escape(point.unit)}"/>'
                )
            assets_xml.append(
                f'  <Asset assetId="{escape(asset_uuid)}" deviceUuid="{escape(dev_uuid)}" '
                f'timestamp="{time.strftime("%Y-%m-%dT%H:%M:%SZ")}">\n'
                f'    <Description manufacturer="{escape(manufacturer)}" model="ProtoForge-Sim"/>\n'
                f'    <Configuration>\n'
                + "\n".join(description_items) + "\n"
                '    </Configuration>\n'
                '  </Asset>'
            )
            if len(assets_xml) >= count:
                break

        return (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<MTConnectAssets xmlns="urn:mtconnect.org:MTConnectAssets:1.3">\n'
            f'  <Header creationTime="{time.strftime("%Y-%m-%dT%H:%M:%SZ")}" '
            f'instanceId="{self._instance_id}" sender="ProtoForge" '
            f'assetCount="{len(assets_xml)}" version="1.3.0"/>\n'
            + "\n".join(assets_xml) + "\n"
            '</MTConnectAssets>'
        )

    def _build_error(self, error_code: str, error_text: str) -> str:
        return (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<MTConnectError xmlns="urn:mtconnect.org:MTConnectError:1.3">\n'
            f'  <Header creationTime="{time.strftime("%Y-%m-%dT%H:%M:%SZ")}" '
            f'instanceId="{self._instance_id}" sender="ProtoForge" version="1.3.0"/>\n'
            f'  <Errors>\n'
            f'    <Error errorCode="{escape(error_code)}">{escape(error_text)}</Error>\n'
            f'  </Errors>\n'
            '</MTConnectError>'
        )

    def _make_http_response(self, body: str, status: int = 200) -> str:
        status_text = "OK" if status == 200 else "Not Found"
        return (
            f"HTTP/1.1 {status} {status_text}\r\n"
            f"Content-Type: text/xml; charset=utf-8\r\n"
            f"Content-Length: {len(body.encode('utf-8'))}\r\n"
            f"Connection: close\r\n"
            f"\r\n"
            f"{body}"
        )

    async def create_device(self, device_config: DeviceConfig) -> str:
        behavior = MtConnectDeviceBehavior(device_config.points)
        self._behaviors[device_config.id] = behavior
        self._device_configs[device_config.id] = device_config
        self._update_default_device(device_config.id)

        proto_config = device_config.protocol_config or {}
        self._device_params[device_config.id] = {
            "device_uuid": proto_config.get("device_uuid", str(uuid.uuid4())),
            "manufacturer": proto_config.get("manufacturer", "ProtoForge"),
        }

        logger.info("MTConnect device created: %s (uuid=%s, mfr=%s)",
                     device_config.id,
                     self._device_params[device_config.id]["device_uuid"][:8] + "...",
                     self._device_params[device_config.id]["manufacturer"])
        self._log_debug("system", "device_create",
                        f"创建MTConnect设备 {device_config.name}",
                        device_id=device_config.id)
        return device_config.id

    async def remove_device(self, device_id: str) -> None:
        self._behaviors.pop(device_id, None)
        self._device_configs.pop(device_id, None)
        self._device_params.pop(device_id, None)
        self._clear_default_device(device_id)
        logger.info("MTConnect device removed: %s", device_id)
        self._log_debug("system", "device_remove",
                        f"移除MTConnect设备 {device_id}",
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
        return behavior.on_write(point_name, value)

    def get_config_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "host": {"type": "string", "default": "0.0.0.0", "description": "MTConnect 服务器监听地址"},
                "port": {"type": "integer", "default": 7878, "description": "MTConnect 端口 (默认7878)"},
            },
        }
