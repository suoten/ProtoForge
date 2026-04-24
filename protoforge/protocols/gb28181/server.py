import asyncio
import logging
import socket
import time
import uuid
import xml.etree.ElementTree as ET
from typing import Any

from protoforge.models.device import DeviceConfig, PointConfig, PointValue
from protoforge.protocols.base import DeviceBehavior, ProtocolServer, ProtocolStatus

logger = logging.getLogger(__name__)


class GB28181Device:
    def __init__(self, device_id: str, server_id: str, host: str, port: int,
                 username: str = "", password: str = "", realm: str = "gb28181"):
        self.device_id = device_id
        self.server_id = server_id
        self.host = host
        self.port = port
        self.username = username or device_id
        self.password = password
        self.realm = realm
        self.sip_uri = f"sip:{device_id}@{host}:{port}"
        self.registered = False
        self.expires = 3600
        self.call_id = ""
        self.cseq = 1
        self.branch_prefix = "z9hG4bK"

    def make_register_request(self) -> str:
        self.call_id = uuid.uuid4().hex[:16]
        branch = f"{self.branch_prefix}{uuid.uuid4().hex[:12]}"
        self.cseq += 1
        return (
            f"REGISTER sip:{self.server_id} SIP/2.0\r\n"
            f"Via: SIP/2.0/UDP {self.host}:{self.port};branch={branch};rport\r\n"
            f"From: <sip:{self.device_id}@{self.host}>;tag={uuid.uuid4().hex[:8]}\r\n"
            f"To: <sip:{self.device_id}@{self.host}>\r\n"
            f"Call-ID: {self.call_id}@{self.host}\r\n"
            f"CSeq: {self.cseq} REGISTER\r\n"
            f"Contact: <sip:{self.device_id}@{self.host}:{self.port}>\r\n"
            f"Max-Forwards: 70\r\n"
            f"User-Agent: ProtoForge-GB28181/1.0\r\n"
            f"Expires: {self.expires}\r\n"
            f"Allow: REGISTER, INVITE, MESSAGE, NOTIFY, SUBSCRIBE\r\n"
            f"Content-Length: 0\r\n\r\n"
        )

    def make_catalog_response(self, sn: str) -> str:
        device_name = "ProtoForge-Camera"
        manufacturer = "ProtoForge"
        model = "PF-CAM-100"
        xml_body = (
            f'<?xml version="1.0" encoding="GB2312"?>\r\n'
            f'<Response>\r\n'
            f'<CmdType>Catalog</CmdType>\r\n'
            f'<SN>{sn}</SN>\r\n'
            f'<DeviceID>{self.device_id}</DeviceID>\r\n'
            f'<SumNum>1</SumNum>\r\n'
            f'<DeviceList Num="1">\r\n'
            f'<Item>\r\n'
            f'<DeviceID>{self.device_id}</DeviceID>\r\n'
            f'<Name>{device_name}</Name>\r\n'
            f'<Manufacturer>{manufacturer}</Manufacturer>\r\n'
            f'<Model>{model}</Model>\r\n'
            f'<Owner>Owner</Owner>\r\n'
            f'<CivilCode>340200</CivilCode>\r\n'
            f'<Block>Block</Block>\r\n'
            f'<Address>Address</Address>\r\n'
            f'<Parental>0</Parental>\r\n'
            f'<SafetyWay>0</SafetyWay>\r\n'
            f'<RegisterWay>1</RegisterWay>\r\n'
            f'<Secrecy>0</Secrecy>\r\n'
            f'<Status>ON</Status>\r\n'
            f'<Longitude>0.0</Longitude>\r\n'
            f'<Latitude>0.0</Latitude>\r\n'
            f'</Item>\r\n'
            f'</DeviceList>\r\n'
            f'</Response>'
        )
        return xml_body

    def make_heartbeat_response(self, sn: str) -> str:
        xml_body = (
            f'<?xml version="1.0" encoding="GB2312"?>\r\n'
            f'<Response>\r\n'
            f'<CmdType>Keepalive</CmdType>\r\n'
            f'<SN>{sn}</SN>\r\n'
            f'<DeviceID>{self.device_id}</DeviceID>\r\n'
            f'<Status>OK</Status>\r\n'
            f'</Response>'
        )
        return xml_body

    def make_sdp_answer(self, media_ip: str, media_port: int, ssrc: str,
                        stream_type: str = "Play") -> str:
        ssrc_full = ssrc if len(ssrc) == 10 else f"0{ssrc}"
        sdp = (
            f"v=0\r\n"
            f"o=- 0 0 IN IP4 {media_ip}\r\n"
            f"s={stream_type}\r\n"
            f"c=IN IP4 {media_ip}\r\n"
            f"t=0 0\r\n"
            f"m=video {media_port} RTP/AVP 96 97 98\r\n"
            f"a=recvonly\r\n"
            f"a=rtpmap:96 PS/90000\r\n"
            f"a=rtpmap:97 MPEG4/90000\r\n"
            f"a=rtpmap:98 H264/90000\r\n"
            f"y={ssrc_full}\r\n"
            f"f=v/2/4///a///\r\n"
        )
        return sdp

    def make_control_response(self, sn: str) -> str:
        xml_body = (
            f'<?xml version="1.0" encoding="GB2312"?>\r\n'
            f'<Response>\r\n'
            f'<CmdType>DeviceControl</CmdType>\r\n'
            f'<SN>{sn}</SN>\r\n'
            f'<DeviceID>{self.device_id}</DeviceID>\r\n'
            f'<Result>OK</Result>\r\n'
            f'</Response>'
        )
        return xml_body

    def make_config_response(self, sn: str) -> str:
        xml_body = (
            f'<?xml version="1.0" encoding="GB2312"?>\r\n'
            f'<Response>\r\n'
            f'<CmdType>DeviceConfig</CmdType>\r\n'
            f'<SN>{sn}</SN>\r\n'
            f'<DeviceID>{self.device_id}</DeviceID>\r\n'
            f'<Result>OK</Result>\r\n'
            f'</Response>'
        )
        return xml_body

    def make_register_with_auth(self, nonce: str) -> str:
        import hashlib
        ha1 = hashlib.md5(f"{self.username}:{self.realm}:{self.password}".encode()).hexdigest()
        ha2 = hashlib.md5(f"REGISTER:sip:{self.server_id}".encode()).hexdigest()
        response = hashlib.md5(f"{ha1}:{nonce}:{ha2}".encode()).hexdigest()

        self.cseq += 1
        branch = f"{self.branch_prefix}{uuid.uuid4().hex[:12]}"
        return (
            f"REGISTER sip:{self.server_id} SIP/2.0\r\n"
            f"Via: SIP/2.0/UDP {self.host}:{self.port};branch={branch};rport\r\n"
            f"From: <sip:{self.device_id}@{self.host}>;tag={uuid.uuid4().hex[:8]}\r\n"
            f"To: <sip:{self.device_id}@{self.host}>\r\n"
            f"Call-ID: {self.call_id}@{self.host}\r\n"
            f"CSeq: {self.cseq} REGISTER\r\n"
            f"Contact: <sip:{self.device_id}@{self.host}:{self.port}>\r\n"
            f"Authorization: Digest username=\"{self.username}\", realm=\"{self.realm}\", "
            f"nonce=\"{nonce}\", uri=\"sip:{self.server_id}\", response=\"{response}\"\r\n"
            f"Max-Forwards: 70\r\n"
            f"User-Agent: ProtoForge-GB28181/1.0\r\n"
            f"Expires: {self.expires}\r\n"
            f"Content-Length: 0\r\n\r\n"
        )


class GB28181DeviceBehavior(DeviceBehavior):
    def __init__(self, points: list[PointConfig]):
        self._points = {p.name: p for p in points}
        self._values: dict[str, Any] = {}
        for p in points:
            self._values[p.name] = p.fixed_value if p.fixed_value is not None else 0

    async def generate_value(self, point_config: dict[str, Any]) -> Any:
        name = point_config.get("name", "")
        return self._values.get(name, 0)

    async def on_write(self, point_name: str, value: Any) -> bool:
        if point_name in self._values:
            self._values[point_name] = value
            return True
        return False

    def set_value(self, point_name: str, value: Any) -> None:
        self._values[point_name] = value

    def get_value(self, point_name: str) -> Any:
        return self._values.get(point_name, 0)


class GB28181Server(ProtocolServer):
    protocol_name = "gb28181"
    protocol_display_name = "GB28181"

    def __init__(self):
        super().__init__()
        self._behaviors: dict[str, GB28181DeviceBehavior] = {}
        self._device_configs: dict[str, DeviceConfig] = {}
        self._gb_devices: dict[str, GB28181Device] = {}
        self._transport: asyncio.DatagramTransport | None = None
        self._host = "0.0.0.0"
        self._port = 5060
        self._server_id = "34020000002000000001"
        self._listen_task: asyncio.Task | None = None
        self._heartbeat_task: asyncio.Task | None = None

    async def start(self, config: dict[str, Any]) -> None:
        self._status = ProtocolStatus.STARTING
        self._host = config.get("host", "0.0.0.0")
        self._port = config.get("port", 5060)
        self._server_id = config.get("server_id", "34020000002000000001")

        try:
            loop = asyncio.get_event_loop()
            self._transport, _ = await loop.create_datagram_endpoint(
                lambda: _SIPProtocolHandler(self),
                local_addr=(self._host, self._port),
            )

            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

            self._status = ProtocolStatus.RUNNING
            logger.info("GB28181 server starting on %s:%d", self._host, self._port)
        except Exception as e:
            self._status = ProtocolStatus.ERROR
            logger.error("Failed to start GB28181 server: %s", e)
            raise

    async def stop(self) -> None:
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.warning("GB28181 heartbeat task error: %s", e)
        if self._transport:
            self._transport.close()
        self._status = ProtocolStatus.STOPPED
        logger.info("GB28181 server stopped")

    async def create_device(self, device_config: DeviceConfig) -> str:
        behavior = GB28181DeviceBehavior(device_config.points)
        self._behaviors[device_config.id] = behavior
        self._device_configs[device_config.id] = device_config

        proto_config = device_config.protocol_config
        gb_device = GB28181Device(
            device_id=device_config.id,
            server_id=self._server_id,
            host=proto_config.get("device_host", "127.0.0.1"),
            port=proto_config.get("device_port", self._port + 1),
            username=proto_config.get("username", ""),
            password=proto_config.get("password", ""),
            realm=proto_config.get("realm", "gb28181"),
        )
        self._gb_devices[device_config.id] = gb_device

        if self._status == ProtocolStatus.RUNNING:
            await self._register_device(gb_device)

        logger.info("GB28181 device created: %s", device_config.id)
        return device_config.id

    async def remove_device(self, device_id: str) -> None:
        self._behaviors.pop(device_id, None)
        self._device_configs.pop(device_id, None)
        gb = self._gb_devices.pop(device_id, None)
        if gb:
            gb.registered = False
        logger.info("GB28181 device removed: %s", device_id)

    async def read_points(self, device_id: str) -> list[PointValue]:
        behavior = self._behaviors.get(device_id)
        if not behavior:
            return []
        config = self._device_configs.get(device_id)
        if not config:
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
        return await behavior.on_write(point_name, value)

    def get_config_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "host": {"type": "string", "default": "0.0.0.0", "description": "监听地址"},
                "port": {"type": "integer", "default": 5060, "description": "监听端口"},
                "server_id": {"type": "string", "default": "34020000002000000001", "description": "SIP服务器ID(20位编码)"},
            },
        }

    async def _register_device(self, gb_device: GB28181Device) -> None:
        register_msg = gb_device.make_register_request()
        try:
            server_host = gb_device.host
            server_port = self._port
            if self._transport:
                self._transport.sendto(
                    register_msg.encode("utf-8"),
                    (server_host, server_port),
                )
                logger.info("Sent REGISTER for device %s", gb_device.device_id)
        except Exception as e:
            logger.warning("Failed to send REGISTER for %s: %s", gb_device.device_id, e)

    async def _heartbeat_loop(self) -> None:
        while self._status == ProtocolStatus.RUNNING:
            for gb_device in self._gb_devices.values():
                if gb_device.registered:
                    await self._register_device(gb_device)
            await asyncio.sleep(60)

    def handle_message(self, data: bytes, addr: tuple) -> None:
        try:
            message = data.decode("utf-8", errors="replace")
            first_line = message.split("\r\n")[0]
            if "MESSAGE" in first_line:
                self._handle_message(message, addr)
            elif "INVITE" in first_line:
                self._handle_invite(message, addr)
            elif "BYE" in first_line:
                self._handle_bye(message, addr)
            elif "200 OK" in message:
                self._handle_200_ok(message)
            elif "401" in first_line:
                self._handle_401(message, addr)
        except Exception as e:
            logger.debug("Error handling SIP message: %s", e)

    def _handle_message(self, message: str, addr: tuple) -> None:
        body_start = message.find("\r\n\r\n")
        if body_start == -1:
            return
        body = message[body_start + 4:]
        try:
            root = ET.fromstring(body)
            cmd_type = root.findtext("CmdType", "")
            sn = root.findtext("SN", "0")
            device_id = root.findtext("DeviceID", "")

            gb_device = self._gb_devices.get(device_id)
            if not gb_device:
                return

            if cmd_type == "Catalog":
                response_body = gb_device.make_catalog_response(sn)
                self._send_response(message, response_body, addr)
                logger.info("Sent Catalog response for %s", device_id)
            elif cmd_type == "Keepalive":
                response_body = gb_device.make_heartbeat_response(sn)
                self._send_response(message, response_body, addr)
                logger.info("Sent Keepalive response for %s", device_id)
            elif cmd_type == "DeviceControl":
                response_body = gb_device.make_control_response(sn)
                self._send_response(message, response_body, addr)
                logger.info("Sent DeviceControl response for %s", device_id)
            elif cmd_type == "DeviceConfig":
                response_body = gb_device.make_config_response(sn)
                self._send_response(message, response_body, addr)
                logger.info("Sent DeviceConfig response for %s", device_id)
        except ET.ParseError:
            logger.debug("Failed to parse XML body")

    def _handle_200_ok(self, message: str) -> None:
        for gb_device in self._gb_devices.values():
            if gb_device.call_id and gb_device.call_id in message:
                gb_device.registered = True
                logger.info("Device %s registered successfully", gb_device.device_id)
                break

    def _handle_401(self, message: str, addr: tuple) -> None:
        import re
        nonce_match = re.search(r'nonce="([^"]+)"', message)
        realm_match = re.search(r'realm="([^"]+)"', message)
        if not nonce_match:
            return

        nonce = nonce_match.group(1)
        if realm_match:
            realm = realm_match.group(1)
        else:
            realm = "gb28181"

        for gb_device in self._gb_devices.values():
            gb_device.realm = realm
            auth_request = gb_device.make_register_with_auth(nonce)
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                sock.settimeout(3)
                sock.sendto(auth_request.encode("utf-8"), addr)
                sock.close()
                logger.info("Sent authenticated REGISTER for %s", gb_device.device_id)
            except Exception as e:
                logger.warning("Failed to send auth REGISTER: %s", e)

    def _handle_invite(self, message: str, addr: tuple) -> None:
        lines = message.split("\r\n")
        via = ""
        from_header = ""
        to_header = ""
        call_id = ""
        cseq = ""
        for line in lines:
            if line.startswith("Via:"):
                via = line
            elif line.startswith("From:"):
                from_header = line
            elif line.startswith("To:"):
                to_header = line
            elif line.startswith("Call-ID:"):
                call_id = line
            elif line.startswith("CSeq:"):
                cseq = line

        device_id = ""
        if to_header:
            import re
            m = re.search(r'sip:(\d+)@', to_header)
            if m:
                device_id = m.group(1)

        gb_device = self._gb_devices.get(device_id)
        if not gb_device:
            for did, dev in self._gb_devices.items():
                gb_device = dev
                break
        if not gb_device:
            return

        media_ip = self._host if self._host != "0.0.0.0" else "127.0.0.1"
        media_port = 6000 + hash(device_id) % 1000
        ssrc = device_id[-10:] if len(device_id) >= 10 else f"0{device_id}"

        sdp_body = gb_device.make_sdp_answer(media_ip, media_port, ssrc)
        sdp_bytes = sdp_body.encode("utf-8")

        response = (
            f"SIP/2.0 200 OK\r\n"
            f"{via}\r\n"
            f"{from_header}\r\n"
            f"{to_header};tag={uuid.uuid4().hex[:8]}\r\n"
            f"{call_id}\r\n"
            f"{cseq}\r\n"
            f"Contact: <sip:{gb_device.device_id}@{gb_device.host}:{gb_device.port}>\r\n"
            f"Content-Type: application/sdp\r\n"
            f"Content-Length: {len(sdp_bytes)}\r\n\r\n"
        )
        if self._transport:
            self._transport.sendto(response.encode("utf-8") + sdp_bytes, addr)
        logger.info("Sent INVITE 200 OK with SDP for %s (media: %s:%d)", device_id, media_ip, media_port)

    def _handle_bye(self, message: str, addr: tuple) -> None:
        lines = message.split("\r\n")
        via = ""
        from_header = ""
        to_header = ""
        call_id = ""
        cseq = ""
        for line in lines:
            if line.startswith("Via:"):
                via = line
            elif line.startswith("From:"):
                from_header = line
            elif line.startswith("To:"):
                to_header = line
            elif line.startswith("Call-ID:"):
                call_id = line
            elif line.startswith("CSeq:"):
                cseq = line

        response = (
            f"SIP/2.0 200 OK\r\n"
            f"{via}\r\n"
            f"{from_header}\r\n"
            f"{to_header}\r\n"
            f"{call_id}\r\n"
            f"{cseq}\r\n"
            f"Content-Length: 0\r\n\r\n"
        )
        if self._transport:
            self._transport.sendto(response.encode("utf-8"), addr)
        logger.info("Sent BYE 200 OK")

    def _send_response(self, original_message: str, body: str, addr: tuple) -> None:
        if not self._transport:
            return
        lines = original_message.split("\r\n")
        via = ""
        from_header = ""
        to_header = ""
        call_id = ""
        cseq = ""
        for line in lines:
            if line.startswith("Via:"):
                via = line
            elif line.startswith("From:"):
                from_header = line
            elif line.startswith("To:"):
                to_header = line
            elif line.startswith("Call-ID:"):
                call_id = line
            elif line.startswith("CSeq:"):
                cseq = line

        body_bytes = body.encode("gb2312", errors="replace")
        response = (
            f"SIP/2.0 200 OK\r\n"
            f"{via}\r\n"
            f"{from_header}\r\n"
            f"{to_header};tag={uuid.uuid4().hex[:8]}\r\n"
            f"{call_id}\r\n"
            f"{cseq}\r\n"
            f"Contact: <sip:{self._server_id}@{self._host}:{self._port}>\r\n"
            f"Content-Type: Application/MANSCDP+xml\r\n"
            f"Content-Length: {len(body_bytes)}\r\n\r\n"
        )
        self._transport.sendto(response.encode("utf-8") + body_bytes, addr)


class _SIPProtocolHandler(asyncio.DatagramProtocol):
    def __init__(self, server: GB28181Server):
        self._server = server

    def datagram_received(self, data: bytes, addr: tuple) -> None:
        self._server.handle_message(data, addr)

    def error_received(self, exc: Exception) -> None:
        logger.debug("SIP protocol error: %s", exc)
