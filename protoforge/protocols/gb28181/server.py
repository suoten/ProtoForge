import asyncio
import logging
import re
import socket
import time
import uuid
import xml.etree.ElementTree as ET
from typing import Any

from protoforge.models.device import DeviceConfig, PointConfig, PointValue
from protoforge.protocols.behavior import DefaultDeviceBehavior as DeviceBehavior, ProtocolServer, ProtocolStatus
from protoforge.protocols.behavior import DynamicValueGenerator

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
        self.rtp_streamer = None
        self._protoforge_device_id = ""
        self._register_interval = 3600
        self._invite_call_id = ""
        self._invite_media_ip = ""
        self._invite_media_port = 0

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
            f"Allow: REGISTER, INVITE, ACK, BYE, MESSAGE, NOTIFY, SUBSCRIBE\r\n"
            f"Content-Length: 0\r\n\r\n"
        )

    def make_catalog_response(self, sn: str) -> str:
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
            f'<Name>ProtoForge-Camera</Name>\r\n'
            f'<Manufacturer>ProtoForge</Manufacturer>\r\n'
            f'<Model>PF-CAM-100</Model>\r\n'
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
            f"a=sendonly\r\n"
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
        self._heartbeat_task: asyncio.Task | None = None
        self._rtp_tasks: list[asyncio.Task] = []

    async def start(self, config: dict[str, Any]) -> None:
        self._status = ProtocolStatus.STARTING
        self._host = config.get("host", "0.0.0.0")
        self._port = config.get("port", 5060)
        self._server_id = config.get("server_id", "34020000002000000001")

        try:
            loop = asyncio.get_running_loop()
            self._transport, _ = await loop.create_datagram_endpoint(
                lambda: _SIPProtocolHandler(self),
                local_addr=(self._host, self._port),
            )

            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

            self._status = ProtocolStatus.RUNNING
            self._log_debug("system", "server_start",
                            f"GB28181 SIP服务启动 {self._host}:{self._port}",
                            detail={"server_id": self._server_id, "port": self._port})
            logger.info("GB28181 server starting on %s:%d", self._host, self._port)
        except Exception as e:
            self._status = ProtocolStatus.ERROR
            self._log_debug("system", "server_error", f"SIP服务启动失败: {e}")
            logger.error("Failed to start GB28181 server: %s", e)
            raise

    async def stop(self) -> None:
        try:
            for gb_device in self._gb_devices.values():
                if gb_device.rtp_streamer and gb_device.rtp_streamer.is_running:
                    await gb_device.rtp_streamer.stop()
            if self._heartbeat_task:
                self._heartbeat_task.cancel()
                try:
                    await self._heartbeat_task
                except asyncio.CancelledError:
                    pass
                except Exception as e:
                    logger.warning("GB28181 heartbeat task error: %s", e)
            for t in self._rtp_tasks:
                if not t.done():
                    t.cancel()
            for t in self._rtp_tasks:
                try:
                    await t
                except (asyncio.CancelledError, Exception) as e:
                    logger.debug("GB28181 RTP task cancel error: %s", e)
            self._rtp_tasks.clear()
            if self._transport:
                self._transport.close()
        except Exception as e:
            logger.warning("GB28181 server stop error: %s", e)
        finally:
            self._status = ProtocolStatus.STOPPED
            self._log_debug("system", "server_stop", "GB28181 SIP服务停止")
            logger.info("GB28181 server stopped")

    async def create_device(self, device_config: DeviceConfig) -> str:
        behavior = GB28181DeviceBehavior(device_config.points)
        self._behaviors[device_config.id] = behavior
        self._device_configs[device_config.id] = device_config
        self._update_default_device(device_config.id)

        proto_config = device_config.protocol_config or {}
        gb_device_id = proto_config.get("device_id", device_config.id)
        sip_server_id = proto_config.get("sip_server_id", self._server_id)
        sip_server_addr = proto_config.get("sip_server_addr", "127.0.0.1")
        sip_server_port = proto_config.get("sip_server_port", 5060)
        register_interval = proto_config.get("register_interval", 3600)

        gb_device = GB28181Device(
            device_id=gb_device_id,
            server_id=sip_server_id,
            host=sip_server_addr,
            port=sip_server_port,
            username=proto_config.get("username", gb_device_id),
            password=proto_config.get("password", ""),
            realm=proto_config.get("realm", "gb28181"),
        )
        gb_device._protoforge_device_id = device_config.id
        gb_device._register_interval = register_interval
        self._gb_devices[device_config.id] = gb_device

        if self._status == ProtocolStatus.RUNNING:
            await self._register_device(gb_device)

        self._log_debug("system", "device_created",
                        f"设备创建: {device_config.name} (国标编码={gb_device_id})",
                        device_id=device_config.id,
                        detail={"gb_id": gb_device_id, "server": f"{sip_server_addr}:{sip_server_port}"})
        logger.info("GB28181 device created: %s (gb_id=%s, server=%s:%d)",
                     device_config.id, gb_device_id, sip_server_addr, sip_server_port)
        return device_config.id

    async def remove_device(self, device_id: str) -> None:
        gb = self._gb_devices.pop(device_id, None)
        if gb:
            if gb.rtp_streamer and gb.rtp_streamer.is_running:
                await gb.rtp_streamer.stop()
            gb.registered = False
        self._behaviors.pop(device_id, None)
        self._device_configs.pop(device_id, None)
        self._clear_default_device(device_id)
        self._log_debug("system", "device_removed", f"设备移除", device_id=device_id)
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
        return behavior.on_write(point_name, value)

    def get_config_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "host": {"type": "string", "default": "0.0.0.0", "description": "监听地址"},
                "port": {"type": "integer", "default": 5060, "description": "监听端口"},
                "server_id": {"type": "string", "default": "34020000002000000001", "description": "SIP服务器ID(20位编码)"},
                "srtp_enabled": {"type": "boolean", "default": False, "description": "是否启用SRTP加密"},
                "srtp_crypto_suite": {
                    "type": "string",
                    "default": "AES_CM_128_HMAC_SHA1_80",
                    "enum": ["AES_CM_128_HMAC_SHA1_80", "AES_CM_128_HMAC_SHA1_32"],
                    "description": "SRTP加密套件",
                },
            },
        }

    async def _register_device(self, gb_device: GB28181Device) -> None:
        register_msg = gb_device.make_register_request()
        try:
            server_host = gb_device.host
            server_port = gb_device.port
            if self._transport:
                self._transport.sendto(
                    register_msg.encode("utf-8"),
                    (server_host, server_port),
                )
                self._log_debug("out", "sip_register",
                                f"发送REGISTER → {server_host}:{server_port}",
                                device_id=gb_device._protoforge_device_id,
                                detail={"gb_id": gb_device.device_id,
                                        "server": f"{server_host}:{server_port}"})
                logger.info("Sent REGISTER for device %s to %s:%d",
                            gb_device.device_id, server_host, server_port)
        except Exception as e:
            self._log_debug("out", "sip_register_error",
                            f"REGISTER发送失败: {e}",
                            device_id=gb_device._protoforge_device_id)
            logger.warning("Failed to send REGISTER for %s: %s", gb_device.device_id, e)

    async def _heartbeat_loop(self) -> None:
        while self._status == ProtocolStatus.RUNNING:
            for gb_device in self._gb_devices.values():
                await self._send_keepalive(gb_device)
            refresh_interval = max(60, min(gb_device.expires for gb_device in self._gb_devices.values()) // 2) if self._gb_devices else 1800
            await asyncio.sleep(refresh_interval)

    async def _send_keepalive(self, gb_device) -> None:
        if not self._transport:
            return
        keepalive_body = f'<?xml version="1.0"?>\r\n<Notify>\r\n<CmdType>Keepalive</CmdType>\r\n<SN>{int(time.time()) % 100000}</SN>\r\n<DeviceID>{gb_device.device_id}</DeviceID>\r\n<Status>OK</Status>\r\n</Notify>'
        local_host = self._host if self._host != "0.0.0.0" else "127.0.0.1"
        local_port = self._port
        msg = (
            f"MESSAGE sip:{self._server_id}@{local_host} SIP/2.0\r\n"
            f"Via: SIP/2.0/UDP {local_host}:{local_port};rport;branch={uuid.uuid4().hex[:8]}\r\n"
            f"From: <sip:{gb_device.device_id}@{local_host}>;tag={gb_device.device_id}\r\n"
            f"To: <sip:{self._server_id}@{local_host}>\r\n"
            f"Call-ID: {uuid.uuid4().hex[:16]}@{local_host}\r\n"
            f"CSeq: {int(time.time()) % 100000} MESSAGE\r\n"
            f"Content-Type: Application/MANSCDP+xml\r\n"
            f"Content-Length: {len(keepalive_body.encode())}\r\n\r\n"
            f"{keepalive_body}"
        )
        try:
            dest_host = gb_device.host
            dest_port = gb_device.port
            self._transport.sendto(msg.encode(), (dest_host, dest_port))
        except Exception as e:
            logger.debug("Keepalive send failed for %s: %s", gb_device.device_id, e)

    def _parse_sdp(self, sdp: str) -> dict:
        result = {"media_ip": "", "media_port": 0, "media_type": ""}
        lines = sdp.strip().split("\r\n")
        conn_addr = ""
        for line in lines:
            if line.startswith("c=IN IP4 "):
                conn_addr = line[9:].strip().split("/")[0]
            elif line.startswith("m=video "):
                parts = line.split()
                if len(parts) >= 2:
                    try:
                        result["media_port"] = int(parts[1])
                    except ValueError:
                        pass
                    result["media_type"] = "video"
            elif line.startswith("m=audio "):
                parts = line.split()
                if len(parts) >= 2:
                    try:
                        result["media_port"] = int(parts[1])
                    except ValueError:
                        pass
                    result["media_type"] = "audio"
        if conn_addr:
            result["media_ip"] = conn_addr
        return result

    def handle_message(self, data: bytes, addr: tuple) -> None:
        try:
            message = data.decode("utf-8", errors="replace")
            first_line = message.split("\r\n")[0]
            self._log_debug("in", "sip_recv",
                            f"收到SIP消息 ← {addr[0]}:{addr[1]}: {first_line[:80]}",
                            detail={"from": f"{addr[0]}:{addr[1]}",
                                    "first_line": first_line[:120]})
            if "MESSAGE" in first_line:
                self._handle_message(message, addr)
            elif "INVITE" in first_line:
                self._handle_invite(message, addr)
            elif "BYE" in first_line:
                self._handle_bye(message, addr)
            elif "ACK" in first_line:
                self._handle_ack(message, addr)
            elif "200 OK" in message:
                self._handle_200_ok(message, addr)
            elif "401" in first_line:
                self._handle_401(message, addr)
            else:
                self._log_debug("in", "sip_unknown",
                                f"未处理的SIP消息: {first_line[:60]}")
        except Exception as e:
            self._log_debug("in", "sip_error", f"SIP消息处理异常: {e}")

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

            gb_device = None
            for did, dev in self._gb_devices.items():
                if dev.device_id == device_id:
                    gb_device = dev
                    break
            if not gb_device:
                self._log_debug("in", "sip_message_unknown",
                                f"未知设备MESSAGE: {cmd_type}, DeviceID={device_id}")
                return

            pf_id = gb_device._protoforge_device_id
            self._log_debug("in", f"sip_{cmd_type.lower()}",
                            f"收到{cmd_type}请求 (SN={sn})",
                            device_id=pf_id,
                            detail={"cmd": cmd_type, "sn": sn, "gb_id": device_id})

            if cmd_type == "Catalog":
                response_body = gb_device.make_catalog_response(sn)
                self._send_response(message, response_body, addr)
                self._log_debug("out", "sip_catalog_response",
                                f"发送Catalog响应 (1个设备)",
                                device_id=pf_id)
            elif cmd_type == "Keepalive":
                response_body = gb_device.make_heartbeat_response(sn)
                self._send_response(message, response_body, addr)
                self._log_debug("out", "sip_keepalive_response",
                                f"发送Keepalive响应 OK",
                                device_id=pf_id)
            elif cmd_type == "DeviceControl":
                response_body = gb_device.make_control_response(sn)
                self._send_response(message, response_body, addr)
                self._log_debug("out", "sip_control_response",
                                f"发送DeviceControl响应 OK",
                                device_id=pf_id)
            elif cmd_type == "DeviceConfig":
                response_body = gb_device.make_config_response(sn)
                self._send_response(message, response_body, addr)
                self._log_debug("out", "sip_config_response",
                                f"发送DeviceConfig响应 OK",
                                device_id=pf_id)
        except ET.ParseError:
            self._log_debug("in", "sip_xml_error", "XML解析失败")

    def _handle_200_ok(self, message: str, addr: tuple) -> None:
        call_id = ""
        for line in message.split("\r\n"):
            if line.startswith("Call-ID:"):
                call_id = line.split(":", 1)[1].strip().split("@")[0]
                break
        for gb_device in self._gb_devices.values():
            if gb_device.call_id and gb_device.call_id == call_id:
                was_registered = gb_device.registered
                gb_device.registered = True
                pf_id = gb_device._protoforge_device_id
                if not was_registered:
                    self._log_debug("in", "sip_register_ok",
                                    f"设备注册成功! 服务器已确认",
                                    device_id=pf_id,
                                    detail={"gb_id": gb_device.device_id,
                                            "server": f"{gb_device.host}:{gb_device.port}"})
                else:
                    self._log_debug("in", "sip_register_refresh",
                                    f"注册刷新成功",
                                    device_id=pf_id)
                logger.info("Device %s registered successfully", gb_device.device_id)
                break

    def _handle_401(self, message: str, addr: tuple) -> None:
        nonce_match = re.search(r'nonce="([^"]+)"', message)
        realm_match = re.search(r'realm="([^"]+)"', message)
        if not nonce_match:
            return

        nonce = nonce_match.group(1)
        realm = realm_match.group(1) if realm_match else "gb28181"

        call_id = ""
        for line in message.split("\r\n"):
            if line.startswith("Call-ID:"):
                call_id = line.split(":", 1)[1].strip().split("@")[0]
                break

        for gb_device in self._gb_devices.values():
            if not call_id:
                continue
            if gb_device.call_id != call_id:
                continue
            gb_device.realm = realm
            auth_request = gb_device.make_register_with_auth(nonce)
            pf_id = gb_device._protoforge_device_id
            try:
                if self._transport:
                    self._transport.sendto(auth_request.encode("utf-8"), addr)
                    self._log_debug("out", "sip_register_auth",
                                    f"发送带认证REGISTER (Digest认证, nonce={nonce[:8]}...)",
                                    device_id=pf_id,
                                    detail={"realm": realm, "nonce": nonce[:16]})
                    logger.info("Sent authenticated REGISTER for %s", gb_device.device_id)
            except Exception as e:
                self._log_debug("out", "sip_register_auth_error",
                                f"认证REGISTER发送失败: {e}",
                                device_id=pf_id)

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
            m = re.search(r'sip:(\d+)@', to_header)
            if m:
                device_id = m.group(1)

        if self._transport:
            trying = f"SIP/2.0 100 Trying\r\n{via}\r\n{from_header}\r\n{to_header}\r\n{call_id}\r\n{cseq}\r\nContent-Length: 0\r\n\r\n"
            self._transport.sendto(trying.encode("utf-8"), addr)

        gb_device = None
        for did, dev in self._gb_devices.items():
            if dev.device_id == device_id:
                gb_device = dev
                break
        if not gb_device:
            self._log_debug("in", "sip_invite_no_device",
                            f"INVITE但无匹配设备: {device_id}")
            return

        pf_id = gb_device._protoforge_device_id

        body_start = message.find("\r\n\r\n")
        sdp_info = {"media_ip": addr[0], "media_port": 0}
        if body_start != -1:
            sdp = message[body_start + 4:]
            sdp_info = self._parse_sdp(sdp)
            if not sdp_info["media_ip"]:
                sdp_info["media_ip"] = addr[0]

        self._log_debug("in", "sip_invite",
                        f"收到INVITE(视频请求) ← {addr[0]}:{addr[1]}",
                        device_id=pf_id,
                        detail={"gb_id": device_id,
                                "media_addr": f"{sdp_info['media_ip']}:{sdp_info['media_port']}"})

        media_ip = self._host if self._host != "0.0.0.0" else "127.0.0.1"
        try:
            base_port = 6000 + (int(device_id[-4:], 10) % 1000)
        except (ValueError, IndexError):
            base_port = 6000
        media_port = base_port
        if not hasattr(self, '_allocated_media_ports'):
            self._allocated_media_ports = set()
        while media_port in self._allocated_media_ports:
            media_port += 2
            if media_port > 6999:
                media_port = 6000
                break
        self._allocated_media_ports.add(media_port)
        self._allocated_media_ports.add(media_port + 1)
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

        gb_device._invite_call_id = call_id
        gb_device._invite_media_ip = sdp_info["media_ip"]
        gb_device._invite_media_port = sdp_info["media_port"]

        self._log_debug("out", "sip_invite_ok",
                        f"发送INVITE 200 OK + SDP (媒体: {media_ip}:{media_port})",
                        device_id=pf_id,
                        detail={"media": f"{media_ip}:{media_port}",
                                "ssrc": ssrc,
                                "waiting_ack": True})
        logger.info("Sent INVITE 200 OK with SDP for %s (media: %s:%d)", device_id, media_ip, media_port)

    def _handle_ack(self, message: str, addr: tuple) -> None:
        lines = message.split("\r\n")
        call_id = ""
        for line in lines:
            if line.startswith("Call-ID:"):
                call_id = line
                break

        for gb_device in self._gb_devices.values():
            if gb_device._invite_call_id and call_id == gb_device._invite_call_id:
                pf_id = gb_device._protoforge_device_id
                dest_ip = gb_device._invite_media_ip
                dest_port = gb_device._invite_media_port

                if dest_ip and dest_port > 0:
                    if gb_device.rtp_streamer and gb_device.rtp_streamer.is_running:
                        t = asyncio.create_task(gb_device.rtp_streamer.stop())
                        t.add_done_callback(lambda fut: fut.exception() if not fut.cancelled() else None)
                        self._rtp_tasks.append(t)
                        self._rtp_tasks = [t for t in self._rtp_tasks if not t.done()]
                    try:
                        from protoforge.protocols.gb28181.rtp_streamer import RtpStreamer
                        ssrc = int(gb_device.device_id[-10:]) if len(gb_device.device_id) >= 10 else 0
                        ssrc = ssrc % 0x3FFFFFFF
                        streamer = RtpStreamer(
                            dest_ip=dest_ip,
                            dest_port=dest_port,
                            ssrc=ssrc,
                            width=352,
                            height=288,
                            fps=25,
                        )
                        streamer.set_debug_callback(
                            lambda direction, msg_type, summary, detail=None, did=pf_id:
                                self._log_debug(direction, msg_type, summary, device_id=did, detail=detail)
                        )
                        gb_device.rtp_streamer = streamer
                        t = asyncio.ensure_future(streamer.start())
                        t.add_done_callback(lambda fut: fut.exception() if not fut.cancelled() else None)
                        self._rtp_tasks.append(t)

                        self._log_debug("out", "rtp_stream_start",
                                        f"ACK收到, 启动RTP视频流 → {dest_ip}:{dest_port}",
                                        device_id=pf_id,
                                        detail={"dest": f"{dest_ip}:{dest_port}",
                                                "ssrc": ssrc,
                                                "resolution": "352x288",
                                                "fps": 25})
                    except Exception as e:
                        self._log_debug("out", "rtp_stream_error",
                                        f"RTP流启动失败: {e}",
                                        device_id=pf_id)
                else:
                    self._log_debug("in", "sip_ack_no_media",
                                    f"ACK收到但无有效媒体地址",
                                    device_id=pf_id)
                break

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

        for gb_device in self._gb_devices.values():
            if gb_device._invite_call_id and call_id == gb_device._invite_call_id:
                pf_id = gb_device._protoforge_device_id
                if gb_device.rtp_streamer and gb_device.rtp_streamer.is_running:
                    t = asyncio.ensure_future(gb_device.rtp_streamer.stop())
                    t.add_done_callback(lambda fut: fut.exception() if not fut.cancelled() else None)
                    self._rtp_tasks.append(t)
                    self._log_debug("out", "rtp_stream_stop",
                                    "BYE收到, 停止RTP视频流",
                                    device_id=pf_id)
                gb_device._invite_call_id = ""
                break

        self._log_debug("out", "sip_bye_ok", "发送BYE 200 OK")
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
