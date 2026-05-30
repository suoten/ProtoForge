import asyncio
import logging
import socket
import struct
import time
from typing import Any

from protoforge.models.device import DeviceConfig, PointValue
from protoforge.protocols.behavior import StandardDeviceBehavior, ProtocolServer, ProtocolStatus
from protoforge.core.messages import desc

logger = logging.getLogger(__name__)


class BACnetDeviceBehavior(StandardDeviceBehavior):
    pass


class BACnetServer(ProtocolServer):
    protocol_name = "bacnet"
    protocol_display_name = "BACnet"

    _BBMD_FWD_TTL = 3600

    def __init__(self):
        super().__init__()
        self._behaviors: dict[str, BACnetDeviceBehavior] = {}
        self._device_configs: dict[str, DeviceConfig] = {}
        self._device_objects: dict[str, dict] = {}
        self._host = "0.0.0.0"
        self._port = 47808
        self._device_id_base = 100
        self._bbmd_enabled = False
        self._bbmd_peers: list[tuple[str, int]] = []
        self._bbmd_fwd_table: dict[tuple[str, int], float] = {}
        self._task: asyncio.Task | None = None
        self._sock: socket.socket | None = None
        self._cov_subscriptions: dict[int, dict] = {}  # FIXED-P0: COV订阅表 {sub_id: {addr, device_id, obj_inst, cov_increment, last_values}}
        self._cov_next_id: int = 1
        self._cov_task: asyncio.Task | None = None

    async def start(self, config: dict[str, Any]) -> None:
        self._status = ProtocolStatus.STARTING
        self._host = config.get("host", "0.0.0.0")
        self._port = config.get("port", 47808)
        self._validate_port(self._port)
        self._device_id_base = config.get("device_id_base", 100)
        self._bbmd_enabled = config.get("bbmd_enabled", False)
        bbmd_peers = config.get("bbmd_peers", [])
        self._bbmd_peers = []
        for peer in bbmd_peers:
            if isinstance(peer, str) and ":" in peer:
                h, p = peer.rsplit(":", 1)
                try:
                    self._bbmd_peers.append((h, int(p)))
                except ValueError as e:
                    logger.debug("BACnet BBMD peer port parse error: %s", e)
            elif isinstance(peer, dict):
                self._bbmd_peers.append((peer.get("host", "0.0.0.0"), peer.get("port", 47808)))
        try:
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            # FIXED-P0: Windows系统需要显式启用SO_BROADCAST，否则UDP广播(Who-Is)无法工作
            try:
                self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            except OSError:
                pass  # 部分平台不支持SO_BROADCAST，忽略
            self._sock.setblocking(False)
            self._sock.bind((self._host, self._port))
            self._task = asyncio.create_task(self._serve_udp())
            self._cov_task = asyncio.create_task(self._cov_notification_loop())  # FIXED-P0: 启动COV通知推送循环
            self._status = ProtocolStatus.RUNNING
            logger.info("BACnet server started on %s:%d (BBMD: %s)",
                         self._host, self._port, self._bbmd_enabled)
            self._log_debug("system", "server_start",
                            f"BACnet service started {self._host}:{self._port}",
                            detail={"host": self._host, "port": self._port})
        except Exception as e:
            self._status = ProtocolStatus.ERROR
            logger.error("Failed to start BACnet server: %s", e)
            raise

    async def stop(self) -> None:
        try:
            if self._cov_task:  # FIXED-P0: 取消COV通知任务
                self._cov_task.cancel()
                try:
                    await self._cov_task
                except asyncio.CancelledError:
                    logger.debug("BACnet COV task cancelled")
            if self._task:
                self._task.cancel()
                try:
                    await self._task
                except asyncio.CancelledError:
                    logger.debug("BACnet task cancelled")
            if self._sock:
                try:
                    self._sock.close()
                except Exception as e:
                    logger.debug("Socket close error: %s", e)
                self._sock = None
        except Exception as e:
            logger.warning("BACnet server stop error: %s", e)
        finally:
            self._status = ProtocolStatus.STOPPED
            logger.info("BACnet server stopped")
            self._log_debug("system", "server_stop", "BACnet service stopped")

    async def _serve_udp(self) -> None:
        loop = asyncio.get_running_loop()
        while True:
            try:
                data, addr = await loop.sock_recvfrom(self._sock, 2048)
                response = self._handle_bacnet_packet(data, addr)
                if response:
                    await loop.sock_sendto(self._sock, response, addr)
                if self._bbmd_enabled and data[0] == 0x81 and len(data) >= 2 and data[1] == 0x00:
                    self._bbmd_forward(data, addr)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug("BACnet UDP error: %s", e)
                await asyncio.sleep(0.01)

    def _handle_bacnet_packet(self, data: bytes, addr: tuple) -> bytes | None:
        if len(data) < 4:
            return None
        if data[0] == 0x81 and len(data) >= 6:
            msg_type = data[1]
            if msg_type == 0x00:
                control = data[2]
                if control & 0x08:
                    invoke_id = data[3] if len(data) > 3 else 0
                    service_choice = data[4] if len(data) > 4 else 0
                    if service_choice == 0x08:
                        return self._make_who_is_response(data, addr)
                    elif service_choice == 0x0C:
                        return self._handle_read_property(data, addr, invoke_id)
                    elif service_choice == 0x0F:
                        return self._handle_write_property(data, addr, invoke_id)
                    elif service_choice == 0x0E:
                        return self._handle_read_property_multiple(data, addr, invoke_id)
                    elif service_choice == 0x05:
                        return self._handle_register_foreign_device(data, addr, invoke_id)
                    elif service_choice == 0x0D:  # FIXED-P0: SubscribeCOV服务
                        return self._handle_subscribe_cov(data, addr, invoke_id)
                    else:
                        return self._make_error_response(invoke_id, 0x0C, 2, 3)
            elif msg_type == 0x01:
                if len(data) >= 6:
                    invoke_id = data[3] if len(data) > 3 else 0
                    logger.debug("BACnet Result message received, invoke_id=%d", invoke_id)
            elif msg_type == 0x04:
                if len(data) >= 6:
                    invoke_id = data[3] if len(data) > 3 else 0
                    reject_reason = data[4] if len(data) > 4 else 0
                    logger.debug("BACnet Reject message received, invoke_id=%d, reason=%d", invoke_id, reject_reason)
        return None

    def _decode_object_identifier(self, raw_bytes: bytes) -> tuple[int, int]:
        if len(raw_bytes) < 4:
            return (0, 0)
        obj_id = struct.unpack(">I", raw_bytes)[0]
        obj_type = (obj_id >> 22) & 0x3FF
        obj_inst = obj_id & 0x3FFFFF
        return (obj_type, obj_inst)

    def _encode_object_identifier(self, obj_type: int, obj_inst: int) -> bytes:
        obj_id = ((obj_type & 0x3FF) << 22) | (obj_inst & 0x3FFFFF)
        return struct.pack(">I", obj_id)

    def _make_error_response(self, invoke_id: int, service_choice: int,
                              error_class: int, error_code: int) -> bytes:
        resp = bytearray()
        resp.append(0x81)
        resp.append(0x0A)
        resp.append(0x00)
        resp.append(0x00)
        resp.append(0x01)
        resp.append(0x04)
        resp.append(0x00)
        resp.append(invoke_id & 0xFF)
        resp.append(0x50)
        resp.append(service_choice & 0xFF)
        resp.append(0x91)
        resp.append(error_class & 0xFF)
        resp.append(0x91)
        resp.append(error_code & 0xFF)
        resp[3] = len(resp) - 4
        return bytes(resp)

    def _make_reject_response(self, invoke_id: int, reason: int) -> bytes:
        resp = bytearray()
        resp.append(0x81)
        resp.append(0x0A)
        resp.append(0x00)
        resp.append(0x00)
        resp.append(0x01)
        resp.append(0x04)
        resp.append(0x00)
        resp.append(invoke_id & 0xFF)
        resp.append(0x40)
        resp.append(reason & 0xFF)
        resp[3] = len(resp) - 4
        return bytes(resp)

    def _handle_read_property(self, data: bytes, addr: tuple, invoke_id: int) -> bytes | None:
        if len(data) < 10:
            return self._make_reject_response(invoke_id, 4)
        obj_id_bytes = data[5:9] if len(data) >= 9 else data[5:]
        obj_type, obj_inst = self._decode_object_identifier(obj_id_bytes[:4] if len(obj_id_bytes) >= 4 else obj_id_bytes)
        prop_id = data[9] if len(data) > 9 else 85

        for device_id, device_obj in self._device_objects.items():
            behavior = self._behaviors.get(device_id)
            if not behavior:
                continue
            for i, obj in enumerate(device_obj.get("objects", [])):
                obj_idx = i + 1
                if obj_inst == 0 or obj_inst == obj_idx:
                    if prop_id == 85 or prop_id == 0x55:
                        value = behavior.get_value(obj.get("object_name", ""))
                    elif prop_id == 77 or prop_id == 0x4D:
                        value = obj.get("object_name", "")
                    elif prop_id == 28 or prop_id == 0x1C:
                        value = obj.get("description", "")
                    elif prop_id == 96 or prop_id == 0x60:
                        value = obj.get("units", "")
                    else:
                        value = behavior.get_value(obj.get("object_name", ""))
                    resp = bytearray()
                    resp.append(0x81)
                    resp.append(0x0A)
                    resp.append(0x00)
                    resp.append(0x00)
                    resp.append(0x01)
                    resp.append(0x04)
                    resp.append(0x00)
                    resp.append(invoke_id & 0xFF)
                    resp.append(0x0C | 0x80)
                    resp += self._encode_object_identifier(obj_type, obj_idx)
                    resp.append(prop_id)
                    if isinstance(value, bool):
                        resp.append(0x19)
                        resp.append(0x01 if value else 0x00)
                    elif isinstance(value, float):
                        resp.append(0x44)
                        resp += struct.pack(">f", value)
                    elif isinstance(value, int):
                        resp.append(0x22)
                        resp += struct.pack(">H", value & 0xFFFF)
                    elif isinstance(value, str):
                        encoded = value.encode("utf-8")
                        resp.append(0x75)
                        resp += struct.pack(">H", len(encoded))
                        resp += encoded
                    else:
                        resp.append(0x44)
                        try:  # FIXED-P1: float()异常保护，非数字值时回退0.0
                            resp += struct.pack(">f", float(value) if value else 0.0)
                        except (ValueError, TypeError):
                            resp += struct.pack(">f", 0.0)
                    resp[3] = len(resp) - 4
                    return bytes(resp)
        return self._make_error_response(invoke_id, 0x0C, 1, 31)

    def _handle_read_property_multiple(self, data: bytes, addr: tuple, invoke_id: int) -> bytes | None:
        if len(data) < 7:
            return self._make_reject_response(invoke_id, 4)
        resp = bytearray()
        resp.append(0x81)
        resp.append(0x0A)
        resp.append(0x00)
        resp.append(0x00)
        resp.append(0x01)
        resp.append(0x04)
        resp.append(0x00)
        resp.append(invoke_id & 0xFF)
        resp.append(0x0E | 0x80)
        offset = 5
        while offset + 4 <= len(data):
            obj_type, obj_inst = self._decode_object_identifier(data[offset:offset + 4])
            offset += 4
            if offset >= len(data):
                break
            prop_count = data[offset] if data[offset] != 0xFE else 1
            offset += 1
            obj_data = bytearray()
            obj_data += self._encode_object_identifier(obj_type, obj_inst)
            found = False
            for device_id, device_obj in self._device_objects.items():
                behavior = self._behaviors.get(device_id)
                if not behavior:
                    continue
                for i, obj in enumerate(device_obj.get("objects", [])):
                    obj_idx = i + 1
                    if obj_inst == 0 or obj_inst == obj_idx:
                        found = True
                        prop_list = bytearray()
                        prop_list.append(0x01)
                        p_offset = offset
                        for _ in range(min(prop_count, 10)):
                            if p_offset >= len(data):
                                break
                            pid = data[p_offset]
                            p_offset += 1
                            if pid == 85 or pid == 0x55:
                                value = behavior.get_value(obj.get("object_name", ""))
                            elif pid == 77:
                                value = obj.get("object_name", "")
                            elif pid == 28:
                                value = obj.get("description", "")
                            elif pid == 96:
                                value = obj.get("units", "")
                            else:
                                value = behavior.get_value(obj.get("object_name", ""))
                            prop_list.append(pid)
                            if isinstance(value, bool):
                                prop_list.append(0x19)
                                prop_list.append(0x01 if value else 0x00)
                            elif isinstance(value, float):
                                prop_list.append(0x44)
                                prop_list += struct.pack(">f", value)
                            elif isinstance(value, int):
                                prop_list.append(0x22)
                                prop_list += struct.pack(">H", value & 0xFFFF)
                            elif isinstance(value, str):
                                encoded = value.encode("utf-8")
                                prop_list.append(0x75)
                                prop_list += struct.pack(">H", len(encoded))
                                prop_list += encoded
                            else:
                                prop_list.append(0x44)
                                try:  # FIXED-P1: float()异常保护，非数字值时回退0.0
                                    prop_list += struct.pack(">f", float(value) if value else 0.0)
                                except (ValueError, TypeError):
                                    prop_list += struct.pack(">f", 0.0)
                        obj_data += prop_list
                        break
                if found:
                    break
            if not found:
                obj_data += self._encode_object_identifier(obj_type, obj_inst)
                obj_data.append(0x01)
                obj_data.append(85)
                obj_data.append(0x91)
                obj_data.append(31)
            resp += obj_data
            while offset < len(data) and data[offset] not in (0x0C, 0x0E, 0x0F):
                offset += 1
                if offset >= len(data):
                    break
        resp[3] = len(resp) - 4
        return bytes(resp)

    def _handle_write_property(self, data: bytes, addr: tuple, invoke_id: int) -> bytes | None:
        if len(data) < 10:
            return self._make_reject_response(invoke_id, 4)
        obj_id_bytes = data[5:9] if len(data) >= 9 else data[5:]
        obj_type, obj_inst = self._decode_object_identifier(obj_id_bytes[:4] if len(obj_id_bytes) >= 4 else obj_id_bytes)
        prop_id = data[9] if len(data) > 9 else 85

        for device_id, device_obj in self._device_objects.items():
            behavior = self._behaviors.get(device_id)
            if not behavior:
                continue
            for i, obj in enumerate(device_obj.get("objects", [])):
                obj_idx = i + 1
                if obj_inst == 0 or obj_inst == obj_idx:
                    tag = data[10] if len(data) > 10 else 0
                    if tag == 0x44 and len(data) >= 15:
                        value = struct.unpack(">f", data[11:15])[0]
                    elif tag == 0x55 and len(data) >= 19:
                        value = struct.unpack(">d", data[11:19])[0]
                    elif tag == 0x34 and len(data) >= 15:
                        value = struct.unpack(">i", data[11:15])[0]
                    elif tag == 0x22 and len(data) >= 13:
                        value = struct.unpack(">H", data[11:13])[0]
                    elif tag == 0x19 and len(data) >= 12:
                        value = bool(data[11])
                    else:
                        value = 0
                    point_name = obj.get("object_name", "")
                    behavior.set_value(point_name, value)
                    obj["present_value"] = value
                    resp = bytearray()
                    resp.append(0x81)
                    resp.append(0x0A)
                    resp.append(0x00)
                    resp.append(0x06)
                    resp.append(0x01)
                    resp.append(0x04)
                    resp.append(0x00)
                    resp.append(invoke_id & 0xFF)
                    resp.append(0x0F | 0x80)
                    return bytes(resp)
        return None

    def _handle_register_foreign_device(self, data: bytes, addr: tuple, invoke_id: int) -> bytes:
        if not self._bbmd_enabled:
            return self._make_error_response(invoke_id, 0x05, 5, 4)
        self._bbmd_fwd_table[addr] = time.time()
        logger.info("BACnet Foreign Device registered: %s:%d", addr[0], addr[1])
        resp = bytearray()
        resp.append(0x81)
        resp.append(0x0A)
        resp.append(0x00)
        resp.append(0x06)
        resp.append(0x01)
        resp.append(0x04)
        resp.append(0x00)
        resp.append(invoke_id & 0xFF)
        resp.append(0x05 | 0x80)
        return bytes(resp)

    def _bbmd_forward(self, data: bytes, source_addr: tuple) -> None:
        if not self._bbmd_enabled or not self._sock:
            return
        now = time.time()
        expired = [k for k, v in self._bbmd_fwd_table.items() if now - v > self._BBMD_FWD_TTL]
        for k in expired:
            del self._bbmd_fwd_table[k]
        for peer_addr in self._bbmd_peers:
            if peer_addr != source_addr:
                try:
                    self._sock.sendto(data, peer_addr)
                except Exception as e:
                    logger.debug("BBMD forward to %s failed: %s", peer_addr, e)
        for fd_addr in list(self._bbmd_fwd_table.keys()):
            if fd_addr != source_addr:
                try:
                    self._sock.sendto(data, fd_addr)
                except Exception as e:
                    logger.debug("BBMD forward to FD %s failed: %s", fd_addr, e)

    def _handle_subscribe_cov(self, data: bytes, addr: tuple, invoke_id: int) -> bytes:  # FIXED-P0: COV订阅处理
        if len(data) < 10:
            return self._make_reject_response(invoke_id, 4)
        obj_id_bytes = data[5:9] if len(data) >= 9 else data[5:]
        obj_type, obj_inst = self._decode_object_identifier(obj_id_bytes[:4] if len(obj_id_bytes) >= 4 else obj_id_bytes)
        cov_increment = 0.1
        issue_confirmed = True
        lifetime = 0
        offset = 9
        if offset < len(data):
            issue_confirmed = bool(data[offset] & 0x01)
            offset += 1
        if offset + 4 <= len(data) and data[offset] == 0x44:
            cov_increment = struct.unpack(">f", data[offset + 1:offset + 5])[0]
            offset += 5
        if offset + 4 <= len(data) and data[offset] == 0x22:
            lifetime = struct.unpack(">H", data[offset + 1:offset + 3])[0]
        sub_id = self._cov_next_id
        self._cov_next_id += 1
        device_id = None
        for did, device_obj in self._device_objects.items():
            for i, obj in enumerate(device_obj.get("objects", [])):
                if obj_inst == 0 or obj_inst == i + 1:
                    device_id = did
                    break
            if device_id:
                break
        self._cov_subscriptions[sub_id] = {
            "addr": addr, "device_id": device_id, "obj_type": obj_type,
            "obj_inst": obj_inst, "cov_increment": cov_increment,
            "lifetime": lifetime, "issue_confirmed": issue_confirmed,
            "last_values": {},
        }
        resp = bytearray()
        resp.append(0x81)
        resp.append(0x0A)
        resp.append(0x00)
        resp.append(0x00)
        resp.append(0x01)
        resp.append(0x04)
        resp.append(0x00)
        resp.append(invoke_id & 0xFF)
        resp.append(0x0D | 0x80)
        resp[3] = len(resp) - 4
        return bytes(resp)

    async def _cov_notification_loop(self) -> None:  # FIXED-P0: COV通知推送循环
        loop = asyncio.get_running_loop()
        while self._status == ProtocolStatus.RUNNING:
            try:
                dead_subs = []
                for sub_id, sub_info in list(self._cov_subscriptions.items()):
                    addr = sub_info.get("addr")
                    device_id = sub_info.get("device_id")
                    if not device_id or not addr:
                        continue
                    behavior = self._behaviors.get(device_id)
                    device_obj = self._device_objects.get(device_id)
                    if not behavior or not device_obj:
                        continue
                    objects = device_obj.get("objects", [])
                    obj_inst = sub_info.get("obj_inst", 0)
                    cov_inc = sub_info.get("cov_increment", 0.1)
                    last_vals = sub_info.get("last_values", {})
                    has_change = False
                    notifications = []
                    for i, obj in enumerate(objects):
                        idx = i + 1
                        if obj_inst != 0 and obj_inst != idx:
                            continue
                        point_name = obj.get("object_name", "")
                        value = behavior.get_value(point_name)
                        prev = last_vals.get(idx)
                        if prev is None or abs(float(value) - float(prev)) >= cov_inc:
                            has_change = True
                            notifications.append((idx, obj, value))
                            last_vals[idx] = value
                    if not has_change:
                        continue
                    for idx, obj, value in notifications:
                        resp = bytearray()
                        resp.append(0x81)
                        resp.append(0x01)
                        resp.append(0x00)
                        resp.append(0x00)
                        resp.append(0x01)
                        resp.append(0x04)
                        resp.append(0x00)
                        resp.append(sub_id & 0xFF)
                        resp.append(0x01)
                        obj_type_enc = 0
                        ot = obj.get("object_type", "analogInput")
                        type_map = {"analogInput": 0, "analogOutput": 1, "analogValue": 2,
                                    "binaryInput": 3, "binaryOutput": 4, "binaryValue": 5}
                        obj_type_enc = type_map.get(ot, 0)
                        resp += self._encode_object_identifier(obj_type_enc, idx)
                        resp.append(85)
                        if isinstance(value, float):
                            resp.append(0x44)
                            resp += struct.pack(">f", value)
                        elif isinstance(value, int):
                            resp.append(0x22)
                            resp += struct.pack(">H", value & 0xFFFF)
                        elif isinstance(value, bool):
                            resp.append(0x19)
                            resp.append(0x01 if value else 0x00)
                        else:
                            resp.append(0x44)
                            try:
                                resp += struct.pack(">f", float(value))
                            except (ValueError, TypeError):
                                resp += struct.pack(">f", 0.0)
                        resp.append(96)
                        units = obj.get("units", "")
                        encoded = units.encode("utf-8")
                        resp.append(0x75)
                        resp += struct.pack(">H", len(encoded))
                        resp += encoded
                        resp[3:5] = struct.pack(">H", len(resp) - 4)
                        if self._sock:
                            try:
                                await loop.sock_sendto(self._sock, bytes(resp), addr)
                            except Exception:
                                dead_subs.append(sub_id)
                for sid in dead_subs:
                    self._cov_subscriptions.pop(sid, None)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug("BACnet COV notification error: %s", e)
            await asyncio.sleep(1.0)

    def _make_who_is_response(self, data: bytes, addr: tuple) -> bytes:
        responses = b""
        for device_id, device_obj in self._device_objects.items():
            bacnet_id = device_obj.get("device_id", self._device_id_base)
            vendor_id = device_obj.get("vendor_id", 999)
            max_apdu = min(device_obj.get("max_apdu_length_accepted", 1024), 1476)
            resp = bytearray()
            resp += bytes([0x81, 0x0A, 0x00, 0x00])
            resp += bytes([0x01, 0x00])
            resp += bytes([0x10, 0x00])
            resp += bytes([0xC4])
            resp += self._encode_object_identifier(8, bacnet_id)
            resp += bytes([0x22, 0x04, 0x00, max_apdu & 0xFF])
            resp += bytes([0x91, 0x03])
            resp += bytes([0x33])
            resp += struct.pack(">H", vendor_id)
            resp[2:4] = struct.pack(">H", len(resp))
            responses += bytes(resp)
        return responses if responses else None

    async def create_device(self, device_config: DeviceConfig) -> str:
        device_id = device_config.id
        behavior = BACnetDeviceBehavior(device_config.points)
        proto_config = device_config.protocol_config or {}
        bacnet_device_id = proto_config.get("device_id") or proto_config.get("device_id_base") or proto_config.get("device_instance") or (self._device_id_base + len(self._device_configs))  # FIXED-P1: 兼容device_id/device_id_base/device_instance三种字段名
        bacnet_device_name = proto_config.get("device_name", device_config.name)
        network_number = proto_config.get("network_number", 0)  # FIXED-P1: BACnet网络号配置

        objects = []
        for i, point in enumerate(device_config.points):
            object_type = self._get_bacnet_object_type(point)
            obj = {
                "object_identifier": f"{object_type},{i + 1}",
                "object_name": point.name,
                "object_type": object_type,
                "present_value": behavior.get_value(point.name),
                "description": point.description,
                "units": point.unit,
                "cov_increment": 0.1,
                "reliability": "no-fault-detected",
                "out_of_service": False,
            }
            objects.append(obj)

        async with self._behaviors_lock:  # FIXED: 将_device_configs放入锁保护范围，与其他协议一致
            self._behaviors[device_id] = behavior
            self._device_configs[device_id] = device_config
            self._device_objects[device_id] = {  # FIXED-P1: 移入_behaviors_lock内保护
                "device_id": bacnet_device_id,
                "device_name": bacnet_device_name,
                "network_number": network_number,  # FIXED-P1: 存储网络号
                "vendor_name": "ProtoForge",
                "vendor_id": 999,
                "model_name": "PF-BAC-100",
                "firmware_revision": "1.0.0",
                "application_software_revision": "1.0.0",
                "protocol_version": 1,
                "protocol_revision": 24,
                "max_apdu_length_accepted": 1024,
                "segmentation_supported": "segmented-both",
                "apdu_timeout": 3000,
                "number_of_apdu_retries": 3,
                "objects": objects,
            }
        await self._update_default_device_async(device_id)

        logger.info("BACnet device created: %s (BACnet ID: %d, name: %s, %d objects)",
                     device_id, bacnet_device_id, bacnet_device_name, len(objects))
        self._log_debug("system", "device_create",
                        f"BACnet device created: {device_config.name}",
                        device_id=device_id)
        return device_id

    async def remove_device(self, device_id: str) -> None:
        async with self._behaviors_lock:  # FIXED: 将_device_configs放入锁保护范围，与其他协议一致
            self._behaviors.pop(device_id, None)
            self._device_configs.pop(device_id, None)
            self._device_objects.pop(device_id, None)  # FIXED-P1: 移入_behaviors_lock内保护
        await self._clear_default_device_async(device_id)
        logger.info("BACnet device removed: %s", device_id)
        self._log_debug("system", "device_remove",
                        f"BACnet device removed: {device_id}",
                        device_id=device_id)

    async def read_points(self, device_id: str) -> list[PointValue]:
        behavior = self._behaviors.get(device_id)
        config = self._device_configs.get(device_id)
        if not behavior or not config:
            return []

        values = []
        for point in config.points:
            val = behavior.get_value(point.name)
            values.append(PointValue(
                name=point.name,
                value=val,
                timestamp=time.time(),
            ))
        return values

    async def write_point(self, device_id: str, point_name: str, value: Any) -> bool:
        behavior = self._behaviors.get(device_id)
        if not behavior:
            return False
        success = behavior.on_write(point_name, value)
        if success:
            device_obj = self._device_objects.get(device_id, {})
            for obj in device_obj.get("objects", []):
                if obj.get("object_name") == point_name:
                    obj["present_value"] = value
        return success

    def get_config_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "host": {
                    "type": "string",
                    "default": "0.0.0.0",
                    "description": desc("listen_address", "BACnet listen address"),
                },
                "port": {
                    "type": "integer",
                    "default": 47808,
                    "description": desc("bacnet_port", "BACnet UDP port (default 47808)"),
                },
                "device_id_base": {
                    "type": "integer",
                    "default": 100,
                    "description": desc("bacnet_device_id_base", "BACnet device ID base value"),
                },
                "network_number": {
                    "type": "integer",
                    "default": 0,
                    "description": desc("bacnet_network_number", "BACnet network number (0=local)"),  # FIXED-P1
                },
                "bbmd_enabled": {
                    "type": "boolean",
                    "default": False,
                    "description": desc("bacnet_bbmd_enabled", "Enable BBMD broadcast management"),
                },
                "bbmd_peers": {
                    "type": "array",
                    "items": {"type": "string"},
                    "default": [],
                    "description": desc("bacnet_bbmd_peers", "BBMD peer list (format: host:port)"),
                },
            },
        }

    def _get_bacnet_object_type(self, point) -> str:
        access = point.access if hasattr(point, "access") else "r"
        data_type = point.data_type if hasattr(point, "data_type") else "float32"
        dt_val = data_type.value if hasattr(data_type, "value") else str(data_type)
        if access == "r":
            if dt_val == "bool":
                return "binaryInput"
            return "analogInput"
        else:
            if dt_val == "bool":
                return "binaryOutput"
            return "analogOutput"
