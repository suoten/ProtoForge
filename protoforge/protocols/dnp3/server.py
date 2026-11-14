"""DNP3 分布式网络协议从站实现（v1.16.0，TCP 伪平衡核心子集）。

实现范围（IEC 60870-5-3 非平衡链路的 TCP 实践简化）：
  - 数据链路层：0x05 0x64 帧定界、LEN、目的/源地址、CTRL、每 16 字节块 2 字节
    CRC（多项式 0x3D65 反射，表运行时生成）；
  - 伪传输层：FIR/FIN/SEQ 分帧重组（>1 帧的应用层消息）；
  - 应用层：AC 头（FIR/FIN/CON/UNS/SEQ）、功能码 0x01 Read / 0x0D 时间同步 /
    0x02 Write（G10V2 二输出、G41V2 模拟输出）/ 0x00 应用层确认；
  - 对象组：静态 Group 1 Var 2（二输入带标志）、Group 20 Var 6（32 位模拟量
    带标志）；事件 Group 2 Var 1（二输入变化事件）、Group 20 Var 2（16 位
    模拟量变化事件），Qualifier 0x01（16 位索引前缀）；Class 0 完整性读、
    Class 1/2/3 事件读（Group 60 Var 1-4）；变化入队（bool→Class 1、
    数值→Class 2）；时间同步 Group 50 Var 1。

点位映射：point.address = DNP3 IOA（0-65535）；bool → 二输入（G1/G2），
数值 → 模拟量（G20）。

复杂度说明：链路/应用层的纯函数（crc/frame parse/build、对象编码）独立于
socket，供黄金用例门禁（tests/test_wire_golden_dnp3.py）字节级校验。
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import struct
import time
from typing import Any

from protoforge.models.device import DeviceConfig, PointValue
from protoforge.protocols.base import ProtocolServer, ProtocolStatus, shutdown_server_task
from protoforge.protocols.modbus._common import ModbusDeviceBehavior

logger = logging.getLogger(__name__)

START_BYTES = b"\x05\x64"
SRC_DEFAULT_MASTER = 0x0001  # 未指定时主站源地址
OUTSTATION_ADDR_DEFAULT = 1

# 链路控制字节功能码
FC_ACK = 0x00
FC_NACK = 0x01
FC_READ = 0x03  # Send/Confirm user data（主站→从站用户数据）
FC_SEND_NOCONFIRM = 0x04
FC_LINK_STATUS = 0x0B  # 请求链路状态
FC_STATUS_OF_LINK = 0x0A  # 从站→链路状态响应

# 应用层功能码
AF_READ = 0x01
AF_WRITE = 0x02
AF_DELAY_MEAS = 0x0D  # 时间同步请求
AF_RESPONSE = 0x81
AF_CONFIRM = 0x00

# 对象组/变体
G_BINARY_INPUT, G_BINARY_INPUT_EVENT = 1, 2
G_CONTROL_OUTPUT = 10
G_ANALOG_INPUT, G_ANALOG_INPUT_EVENT = 20, 22
G_ANALOG_OUTPUT = 40
G_TIME = 50
G_CLASS = 60

QUAL_INDEX16 = 0x01  # 16 位索引前缀
QUAL_COUNT8 = 0x00  # 1 字节数量前缀

_FLAG_ONLINE = 0x01


def _build_crc_table() -> list[int]:
    """DNP3 CRC 表：多项式 0x3D65 反射，初始 0x0000（运行时生成，免硬编码）。"""
    table = []
    for byte in range(256):
        crc = byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA6BC if crc & 1 else crc >> 1
        table.append(crc)
    return table


_CRC_TABLE = _build_crc_table()


def dnp3_crc(data: bytes) -> int:
    crc = 0x0000
    for b in data:
        crc = (crc >> 8) ^ _CRC_TABLE[(crc ^ b) & 0xFF]
    return crc


def append_crc(data: bytes) -> bytes:
    """按 16 字节块追加 CRC（最后不足 16 的块也追加 2 字节）。"""
    out = bytearray()
    for i in range(0, len(data), 16):
        chunk = data[i:i + 16]
        out += chunk
        out += struct.pack("<H", dnp3_crc(chunk))
    return bytes(out)


def strip_and_verify_crc(frame: bytes) -> bytes | None:
    """校验并剥离 CRC；非法返回 None。

    输入 = 每块 ≤16 字节数据 + 2 字节 CRC 的完整 body；
    最后一块数据长度 = 剩余 - 2（不足 16 时必须正确切分，否则会把
    CRC 字节吞进数据块导致校验必然失败）。
    """
    if not frame:
        return b""
    out = bytearray()
    i = 0
    while i < len(frame):
        remaining = len(frame) - i
        if remaining < 3:
            return None  # 至少 1 数据字节 + 2 CRC
        data_len = min(16, remaining - 2)
        chunk = frame[i:i + data_len]
        crc = frame[i + data_len:i + data_len + 2]
        if len(crc) < 2 or dnp3_crc(chunk) != struct.unpack("<H", crc)[0]:
            return None
        out += chunk
        i += data_len + 2
    return bytes(out)


def build_link_frame(dest: int, src: int, ctrl: int, user_data: bytes) -> bytes:
    """构建完整链路帧（含分块 CRC）。user_data ≤ 249 字节。

    CRC 校验域 = DST(2)+SRC(2)+CTRL(1)+user_data（共 LEN 字节），
    不含 05 64 头与 LEN 字节自身。
    """
    if len(user_data) > 249:
        raise ValueError("user data too long for one link frame")
    crc_payload = struct.pack("<HHB", dest, src, ctrl) + user_data
    return START_BYTES + bytes([len(user_data) + 5]) + append_crc(crc_payload)


def parse_link_frame(buf: bytes) -> tuple[dict[str, Any], int] | None:
    """解析一帧链路数据。

    帧布局：05 64 | LEN | DST(2) SRC(2) CTRL(1) | user_data(LEN-5) | CRC(2)
    body（含 CRC）总长 = LEN + 2。

    :return: ({dest, src, ctrl, user_data, need_ack}, 消耗字节数) 或 None（数据不足）
    :raises ValueError: 帧格式非法
    """
    start = buf.find(START_BYTES)
    if start < 0:
        return None
    if len(buf) < start + 3:
        return None
    length = buf[start + 2]
    if not 5 <= length <= 255:
        raise ValueError(f"invalid DNP3 length {length}")
    # 逐块验证（LEN 驱动）：每 16 字节 user_data 配 2 字节 CRC，
    # 最后一块 = 剩余 user_data（不足 16）。body 总长 = LEN + 2*块数，只能扫描确定。
    i = start + 3
    verified = bytearray()
    while len(verified) < length:
        block = min(16, length - len(verified))
        chunk = buf[i:i + block]
        crc = buf[i + block:i + block + 2]
        if len(chunk) < block or len(crc) < 2:
            return None  # 数据不足
        if dnp3_crc(chunk) != struct.unpack("<H", crc)[0]:
            raise ValueError("DNP3 CRC mismatch")
        verified += chunk
        i += block + 2
    dest, src, ctrl = struct.unpack("<HHB", verified[:5])
    user = bytes(verified[5:])
    fc = ctrl & 0x0F
    prm = bool(ctrl & 0x40)
    fcv = bool(ctrl & 0x10)
    return {"dest": dest, "src": src, "ctrl": ctrl, "fc": fc, "prm": prm,
            "fcv": fcv, "user_data": user,
            "need_ack": prm and fcv and fc in (2, 3)}, i


def _reassemble(fragments: list[bytes]) -> bytes:
    """伪传输层：按 FIR/FIN 重组。

    多帧时每段第一个字节是 TH（FIR/FIN/SEQ），重组需剥离；
    单帧（FIR=FIN=1）不带 TH（send 直接是应用层消息）。
    """
    if not fragments:
        return b""
    if len(fragments) == 1:
        return fragments[0]
    return b"".join(f[1:] for f in fragments)


def _split_app(apdu: bytes, max_user: int = 249) -> list[bytes]:
    """应用层消息拆分为伪传输层分段（单段 FIR=FIN=1）。"""
    if len(apdu) <= max_user:
        return [apdu]
    chunks = [apdu[i:i + max_user] for i in range(0, len(apdu), max_user)]
    out = []
    for i, ch in enumerate(chunks):
        fir = 0x80 if i == 0 else 0
        fin = 0x40 if i == len(chunks) - 1 else 0
        seq = i & 0x0F
        out.append(bytes([fir | fin | seq]) + ch)
    return out


def _strip_transport(apdu: bytes) -> bytes:
    """剥离伪传输层 TH 字节（多帧时由调用方先拼接 FRAGMENT 再剥）。"""
    return apdu[1:] if apdu else apdu


def _parse_objects(apdu: bytes) -> list[dict[str, Any]]:
    """解析应用层对象头序列（支持 Qualifier 0x00/0x01/0x06）。

    :return: [{group, variation, qualifier, start, count, payload}]
    """
    objects: list[dict[str, Any]] = []
    i = 0
    while i + 3 <= len(apdu):
        g = apdu[i]
        v = apdu[i + 1]
        q = apdu[i + 2]
        i += 3
        obj: dict[str, Any] = {"group": g, "variation": v, "qualifier": q,
                               "start": None, "count": None, "payload": b""}
        qcode = q & 0x0F
        if qcode == 0x06:  # 不带数量（全量读）
            objects.append(obj)
            continue
        if qcode in (0x00, 0x01):  # 数量前缀（1 字节） / 16 位索引+数量前缀
            if qcode == 0x00:
                if i + 1 > len(apdu):
                    break
                count = apdu[i]
                i += 1
                obj["count"] = count
                obj["payload"] = apdu[i:i + count * _OBJ_SIZE.get((g, v), 0)]
                i += count * _OBJ_SIZE.get((g, v), 0)
            else:
                if i + 2 > len(apdu):
                    break
                count = apdu[i] | (apdu[i + 1] << 8)
                i += 2
                obj["count"] = count
                obj["start"] = 0
                obj["payload"] = apdu[i:]
                i = len(apdu)
        else:
            break
        objects.append(obj)
    return objects


# 每点固定字节数（数量前缀解析用；索引前缀/变长对象走 payload 直读）
_OBJ_SIZE: dict[tuple[int, int], int] = {
    (G_TIME, 1): 6,
}


def encode_static_points(points: list[tuple[int, bool | float | int, str]]) -> bytes:
    """编码静态数据为对象序列（Group 20 Var 6 / Group 1 Var 2，Qualifier 0x01 索引前缀）。"""
    analog, binary = [], []
    for ioa, value, dt in points:
        if dt == "bool":
            binary.append((ioa, bool(value)))
        else:
            analog.append((ioa, value))
    out = bytearray()
    if binary:
        out += bytes([G_BINARY_INPUT, 2, QUAL_INDEX16])
        out += struct.pack("<H", len(binary))
        for ioa, v in binary:
            out += struct.pack("<H", ioa) + bytes([_FLAG_ONLINE | (0x80 if v else 0)])
    if analog:
        out += bytes([G_ANALOG_INPUT, 6, QUAL_INDEX16])
        out += struct.pack("<H", len(analog))
        for ioa, v in analog:
            out += struct.pack("<H", ioa) + bytes([_FLAG_ONLINE]) + struct.pack("<i", int(v))
    return bytes(out)


def encode_events(events: list[tuple[int, bool | float | int, str]]) -> bytes:
    """编码变化事件（Group 2 Var 1 / Group 20 Var 2，Qualifier 0x01 索引前缀）。"""
    analog, binary = [], []
    for ioa, value, dt in events:
        if dt == "bool":
            binary.append((ioa, bool(value)))
        else:
            analog.append((ioa, value))
    out = bytearray()
    if binary:
        out += bytes([G_BINARY_INPUT_EVENT, 1, QUAL_INDEX16])
        out += struct.pack("<H", len(binary))
        for ioa, v in binary:
            out += struct.pack("<H", ioa) + bytes([_FLAG_ONLINE | (0x80 if v else 0)])
    if analog:
        out += bytes([G_ANALOG_INPUT_EVENT, 2, QUAL_INDEX16])
        out += struct.pack("<H", len(analog))
        for ioa, v in analog:
            out += struct.pack("<H", ioa) + bytes([_FLAG_ONLINE]) + struct.pack("<h", max(-32768, min(32767, int(v))))
    return bytes(out)


def _build_response(ac_seq: int, func: int, objects: bytes, master_src: int,
                    outstation: int) -> bytes:
    ac = 0x80 | 0x40 | (ac_seq & 0x0F)  # FIR|FIN
    apdu = bytes([ac, func]) + objects
    frames = _split_app(apdu)
    last = len(frames) - 1
    return b"".join(
        build_link_frame(master_src, outstation, 0x44 | (0x80 if i < last else 0), fr)
        for i, fr in enumerate(frames)
    )


class Dnp3Server(ProtocolServer):
    """DNP3 TCP 从站（outstation，伪平衡）。默认端口 20000。"""

    protocol_name = "dnp3"
    protocol_display_name = "DNP3"
    protocol_description = "DNP3 分布式网络协议从站 - 电力/水务 SCADA 远动通信（IEEE 1815）"
    protocol_version = "1.0.0"

    def __init__(self):
        super().__init__()
        self._behaviors: dict[str, ModbusDeviceBehavior] = {}
        self._device_configs: dict[str, DeviceConfig] = {}
        self._host = "0.0.0.0"
        self._port = 20000
        self._server_task: asyncio.Task | None = None
        self._server_running = False
        self._connections: dict[asyncio.StreamWriter, dict[str, Any]] = {}
        self._outstation_addr = OUTSTATION_ADDR_DEFAULT
        # 事件缓冲：[(class, device_id, point_name, ioa, value, dt)]
        self._event_queues: dict[int, list[tuple[str, int, Any, str]]] = {1: [], 2: [], 3: []}
        self._last_values: dict[str, Any] = {}

    # -- 生命周期 -----------------------------------------------------------

    async def start(self, config: dict[str, Any]) -> None:
        self._status = ProtocolStatus.STARTING
        self._apply_connection_limit(config)
        self._host = config.get("host", "0.0.0.0")
        self._port = config.get("port", 20000)
        self._outstation_addr = int(config.get("outstation_addr", OUTSTATION_ADDR_DEFAULT))
        self._validate_port(self._port)
        self._server_running = True
        self._server_task = asyncio.create_task(self._serve())
        self._status = ProtocolStatus.RUNNING
        logger.info("DNP3 outstation started on %s:%d (addr=%d)",
                    self._host, self._port, self._outstation_addr)
        self._log_debug("system", "server_start",
                        f"DNP3 service started {self._host}:{self._port}",
                        detail={"host": self._host, "port": self._port,
                                "outstation_addr": self._outstation_addr})

    async def stop(self) -> None:
        try:
            self._server_running = False
            if self._server_task:
                self._server_task.cancel()
                await shutdown_server_task(self._server_task)
            for writer in list(self._connections.keys()):
                with contextlib.suppress(Exception):
                    writer.close()
            self._connections.clear()
        except Exception as e:
            logger.warning("DNP3 server stop error: %s", e)
        finally:
            self._status = ProtocolStatus.STOPPED
            logger.info("DNP3 server stopped")

    async def _serve(self) -> None:
        server = await asyncio.start_server(self._handle_connection, self._host, self._port)
        async with server:
            await server.serve_forever()

    # -- 设备注册与读写 -----------------------------------------------------

    async def create_device(self, device_config: DeviceConfig) -> str:
        behavior = ModbusDeviceBehavior(device_config.points)
        async with self._behaviors_lock:
            self._behaviors[device_config.id] = behavior
            self._device_configs[device_config.id] = device_config
        await self._update_default_device_async(device_config.id)
        logger.info("DNP3 device created: %s", device_config.id)
        return device_config.id

    async def remove_device(self, device_id: str) -> None:
        async with self._behaviors_lock:
            self._behaviors.pop(device_id, None)
            self._device_configs.pop(device_id, None)
        await self._clear_default_device_async(device_id)

    def get_config_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "host": {"type": "string", "default": "0.0.0.0"},
                "port": {"type": "integer", "default": 20000},
                "outstation_addr": {"type": "integer", "default": 1,
                                    "description": "从站（outstation）链路地址 1-65534"},
            },
        }

    async def read_points(self, device_id: str) -> list[PointValue]:
        behavior = self._behaviors.get(device_id)
        if not behavior:
            return []
        now = time.time()
        return [PointValue(name=p.name, value=behavior.get_value(p.name), timestamp=now)
                for p in self._device_configs.get(device_id).points]

    async def write_point(self, device_id: str, point_name: str, value: Any) -> bool:
        behavior = self._behaviors.get(device_id)
        if not behavior:
            return False
        success = behavior.on_write(point_name, value)
        if success and self._on_write:
            with contextlib.suppress(Exception):
                await self._on_write(device_id, point_name, value)
        return success

    async def sync_point_value(self, device_id: str, point_name: str, value: Any) -> None:
        """引擎 tick：更新内部值；变化时按 bool→Class1 / 数值→Class2 入事件缓冲。"""
        behavior = self._behaviors.get(device_id)
        config = self._device_configs.get(device_id)
        if not behavior or not config:
            return
        point = next((p for p in config.points if p.name == point_name), None)
        if not point:
            return
        key = f"{device_id}/{point_name}"
        if self._last_values.get(key) == value:
            return
        self._last_values[key] = value
        behavior.set_value(point_name, value)
        try:
            ioa = int(point.address)
        except (TypeError, ValueError):
            return
        dt = point.data_type.value if hasattr(point.data_type, "value") else str(point.data_type)
        cls = 1 if dt == "bool" else 2
        self._event_queues[cls].append((device_id, ioa, value, dt))

    # -- 连接处理 -----------------------------------------------------------

    async def _handle_connection(self, reader: asyncio.StreamReader,
                                 writer: asyncio.StreamWriter) -> None:
        self._active_connections += 1
        buf = b""
        fragments: list[bytes] = []
        try:
            self._log_debug("system", "client_connected", "DNP3 master connected")
            while self._server_running:
                chunk = await reader.read(4096)
                if not chunk:
                    break
                buf += chunk
                while True:
                    try:
                        parsed = parse_link_frame(buf)
                    except ValueError as e:
                        self.record_protocol_error("malformed", str(e))
                        self._log_debug("inbound", "frame_error", str(e))
                        buf = b""
                        break
                    if parsed is None:
                        break
                    frame, consumed = parsed
                    buf = buf[consumed:]
                    await self._process_frame(frame, writer, fragments)
        except (ConnectionError, asyncio.IncompleteReadError):
            pass
        except Exception as e:
            logger.warning("DNP3 connection handler error: %s", e)
        finally:
            self._active_connections = max(0, self._active_connections - 1)
            with contextlib.suppress(Exception):
                writer.close()

    async def _process_frame(self, frame: dict[str, Any], writer: asyncio.StreamWriter,
                             fragments: list[bytes]) -> None:
        dest = frame["dest"]
        if dest not in (self._outstation_addr, 0xFFFF):
            return  # 非本站/广播
        if not frame["prm"]:
            return  # 从站不处理主站侧响应帧
        src = frame["src"] or SRC_DEFAULT_MASTER
        if frame["need_ack"]:
            writer.write(build_link_frame(src, self._outstation_addr, FC_ACK, b""))
            await writer.drain()
        fc = frame["fc"]
        if fc in (FC_READ, FC_SEND_NOCONFIRM):
            if frame["user_data"]:
                fragments.append(frame["user_data"])
                th = frame["user_data"][0]
                if not (th & 0x40):  # 未 FIN：等后续分段
                    return
                apdu = _reassemble(fragments)
                fragments.clear()
                responses = await self._process_app_message(apdu, src)
                for resp in responses:
                    writer.write(resp)
                    await writer.drain()
            else:
                # 纯链路层确认请求（背景扫描）：回 ACK
                writer.write(build_link_frame(src, self._outstation_addr, FC_ACK, b""))
                await writer.drain()
        elif fc == FC_LINK_STATUS:
            writer.write(build_link_frame(src, self._outstation_addr, FC_STATUS_OF_LINK, b""))
            await writer.drain()

    # -- 应用层 -------------------------------------------------------------

    async def _process_app_message(self, apdu: bytes, master_src: int) -> list[bytes]:
        responses: list[bytes] = []
        try:
            ac, func = apdu[0], apdu[1]
            seq = ac & 0x0F
            objects = _parse_objects(apdu[2:])
        except Exception as e:
            self.record_protocol_error("malformed", f"app parse: {e}")
            return responses

        device_id = await self._resolve_default_device()

        if func == AF_DELAY_MEAS:
            # 时间同步：应用层确认
            responses.append(self._app_confirm(master_src, seq))
            return responses
        if func == AF_CONFIRM:
            return responses

        if func == AF_READ:
            body = self._handle_read(objects, device_id)
            if body is not None:
                responses.append(_build_response(seq, AF_RESPONSE, body, master_src,
                                                 self._outstation_addr))
            return responses

        if func == AF_WRITE:
            await self._handle_write(objects, device_id)
            responses.append(self._app_confirm(master_src, seq))
            return responses

        self.record_protocol_error("unsupported", f"app func {func:#x}")
        return responses

    def _app_confirm(self, master_src: int, seq: int) -> bytes:
        ac = 0x80 | 0x40 | (seq & 0x0F)
        return build_link_frame(master_src, self._outstation_addr, 0x44,
                                bytes([ac, AF_CONFIRM]))

    async def _resolve_default_device(self) -> str | None:
        try:
            return await self._get_default_device_async()
        except Exception:
            return next(iter(self._device_configs), None)

    def _handle_read(self, objects: list[dict[str, Any]], device_id: str | None) -> bytes | None:
        if device_id is None:
            return None
        config = self._device_configs[device_id]
        behavior = self._behaviors[device_id]
        want_class0 = any(o["group"] == G_CLASS and o["variation"] == 1 for o in objects)
        want_events = {o["variation"]: True for o in objects
                       if o["group"] == G_CLASS and o["variation"] in (2, 3, 4)}
        points = [(int(p.address) if str(p.address).isdigit() else 0,
                   behavior.get_value(p.name),
                   p.data_type.value if hasattr(p.data_type, "value") else str(p.data_type))
                  for p in config.points]

        body = b""
        if want_class0 or not objects or all(o["group"] == G_CLASS for o in objects):
            body += encode_static_points(points)
        if want_events:
            drained: list[tuple[str, int, Any, str]] = []
            for cls_var, queue in ((2, self._event_queues[1]), (3, self._event_queues[2])):
                if not want_events.get(cls_var):
                    continue
                while queue:
                    drained.append(queue.pop(0))
            if drained:
                body += encode_events([(ioa, value, dt) for _, ioa, value, dt in drained])
        return body or encode_static_points(points)

    async def _handle_write(self, objects: list[dict[str, Any]], device_id: str | None) -> None:
        if device_id is None:
            return
        config = self._device_configs[device_id]
        for obj in objects:
            g, v = obj["group"], obj["variation"]
            if g == G_TIME:  # 时间同步对象（FC 0x0D 场景）——确认即可
                continue
            payload = obj.get("payload") or b""
            if not payload:
                continue
            if g == G_CONTROL_OUTPUT and v == 2 and obj.get("count"):
                # G10V2：每点 IOA16 + 1 字节（quality|value）
                for i in range(obj["count"]):
                    ioa = struct.unpack("<H", payload[i * 3:i * 3 + 2])[0]
                    val = bool(payload[i * 3 + 2] & 0x80)
                    await self._propagate_write_by_ioa(device_id, ioa, val)
            elif g == G_ANALOG_OUTPUT and v == 2 and obj.get("count"):
                for i in range(obj["count"]):
                    ioa = struct.unpack("<H", payload[i * 5:i * 5 + 2])[0]
                    val = struct.unpack("<h", payload[i * 5 + 3:i * 5 + 5])[0]
                    await self._propagate_write_by_ioa(device_id, ioa, val)

    async def _propagate_write_by_ioa(self, device_id: str, ioa: int, value: Any) -> None:
        config = self._device_configs.get(device_id)
        if not config:
            return
        point = next((p for p in config.points
                      if str(p.address).isdigit() and int(p.address) == ioa), None)
        if not point or point.access not in ("w", "rw"):
            return
        with contextlib.suppress(Exception):
            await self.write_point(device_id, point.name, value)
