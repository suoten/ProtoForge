"""FANUC protocol server implementation."""

import asyncio
import logging
import struct
import time
from typing import Any

from protoforge.models.device import DeviceConfig, PointValue
from protoforge.observability.messages import desc
from protoforge.protocols.behavior import ProtocolErrorCategory, ProtocolServer, ProtocolStatus, StandardDeviceBehavior

logger = logging.getLogger(__name__)


class FanucDeviceBehavior(StandardDeviceBehavior):
    _DEFAULT_SPINDLE_SPEED = 3000
    _DEFAULT_FEED_RATE = 500
    _DEFAULT_OVERRIDE = 100
    _DEFAULT_AXIS_COUNT = 5

    def __init__(self, points: list | None = None):
        super().__init__(points)
        self._cnc_status: dict[str, Any] = {
            "alarm": 0,
            "mode": 3,
            "execution": 1,
            "motion": 0,
            "program": "O0001",
            "speed_override": self._DEFAULT_OVERRIDE,
            "feed_override": self._DEFAULT_OVERRIDE,
            "spindle_speed": self._DEFAULT_SPINDLE_SPEED,
            "feed_rate": self._DEFAULT_FEED_RATE,
            "absolute_pos": [0.0] * self._DEFAULT_AXIS_COUNT,
            "machine_pos": [0.0] * self._DEFAULT_AXIS_COUNT,
            "relative_pos": [0.0] * self._DEFAULT_AXIS_COUNT,
            "distance_pos": [0.0] * self._DEFAULT_AXIS_COUNT,
        }

    def on_write(self, point_name: str, value: Any) -> bool:
        if point_name in self._values:
            self._values[point_name] = value
            self._written_values[point_name] = value
            if point_name == "spindle_speed":
                self._cnc_status["spindle_speed"] = value
            elif point_name == "feed_rate":
                self._cnc_status["feed_rate"] = value
            elif point_name == "x_pos":
                self._cnc_status["absolute_pos"][0] = value
                self._cnc_status["machine_pos"][0] = value
            elif point_name == "y_pos":
                self._cnc_status["absolute_pos"][1] = value
                self._cnc_status["machine_pos"][1] = value
            elif point_name == "z_pos":
                self._cnc_status["absolute_pos"][2] = value
                self._cnc_status["machine_pos"][2] = value
            elif point_name == "alarm":
                self._cnc_status["alarm"] = value
            elif point_name == "mode":
                self._cnc_status["mode"] = value
            elif point_name == "execution":
                self._cnc_status["execution"] = value
            elif point_name == "motion":
                self._cnc_status["motion"] = value
            elif point_name == "program":
                self._cnc_status["program"] = str(value)
            elif point_name == "speed_override":
                self._cnc_status["speed_override"] = value
            elif point_name == "feed_override":
                self._cnc_status["feed_override"] = value
            elif point_name in ("tool_number", "sequence_number", "parts_count",
                                "running_time", "cutting_time"):
                self._cnc_status[point_name] = value
            elif point_name.startswith("abs_pos_"):
                try:
                    idx = int(point_name.rsplit("_", maxsplit=1)[-1])
                    if 0 <= idx < len(self._cnc_status["absolute_pos"]):
                        self._cnc_status["absolute_pos"][idx] = value
                except (ValueError, IndexError) as e:
                    logger.debug("FANUC on_write abs_pos index error for %s: %s", point_name, e)
            elif point_name.startswith("machine_pos_"):
                try:
                    idx = int(point_name.rsplit("_", maxsplit=1)[-1])
                    if 0 <= idx < len(self._cnc_status["machine_pos"]):
                        self._cnc_status["machine_pos"][idx] = value
                except (ValueError, IndexError) as e:
                    logger.debug("FANUC on_write machine_pos index error for %s: %s", point_name, e)
            elif point_name.startswith("rel_pos_"):
                try:
                    idx = int(point_name.rsplit("_", maxsplit=1)[-1])
                    if 0 <= idx < len(self._cnc_status["relative_pos"]):
                        self._cnc_status["relative_pos"][idx] = value
                except (ValueError, IndexError) as e:
                    logger.debug("FANUC on_write rel_pos index error for %s: %s", point_name, e)
            elif point_name.startswith("dist_pos_"):
                try:
                    idx = int(point_name.rsplit("_", maxsplit=1)[-1])
                    if 0 <= idx < len(self._cnc_status["distance_pos"]):
                        self._cnc_status["distance_pos"][idx] = value
                except (ValueError, IndexError) as e:
                    logger.debug("FANUC on_write dist_pos index error for %s: %s", point_name, e)
            return True
        return False


class FanucServer(ProtocolServer):
    protocol_name = "fanuc"
    protocol_display_name = "FANUC FOCAS (Sim)"

    FOCAS_HEADER_SIZE = 10
    DBP_MAGIC = b"DBP\x00"

    def __init__(self):
        super().__init__()
        self._behaviors: dict[str, FanucDeviceBehavior] = {}
        self._device_configs: dict[str, DeviceConfig] = {}
        self._device_params: dict[str, dict] = {}
        self._host = "0.0.0.0"
        self._port = 8193
        self._server_task: asyncio.Task | None = None
        self._server_running = False
        self._session_device_map: dict[int, str] = {}  # FIXED-P0: session_id→device_id映射，支持多CNC设备
        self._next_session_id = 1
        # FIXED: 原始报文日志开关（供学习研究 FOCAS 底层 16 进制报文），
        # 默认关闭；在高级配置中设 raw_frames=true 开启，报文出现在协议调试日志
        self._raw_frames = False

    async def start(self, config: dict[str, Any]) -> None:
        # raw_frames 兼容 boolean 与 UI 文本输入（"true"/"1"/"on" 等字符串）；
        # 注意 bool("false") 为 True，不能直接 bool() 转换
        _raw = config.get("raw_frames", False)
        if isinstance(_raw, str):
            self._raw_frames = _raw.strip().lower() in ("true", "1", "on", "yes")
        else:
            self._raw_frames = bool(_raw)
        self._status = ProtocolStatus.STARTING
        self._host = config.get("host", "0.0.0.0")
        self._port = config.get("port", 8193)
        self._validate_port(self._port)
        try:
            self._server_running = True
            self._server_task = asyncio.create_task(self._serve())
            self._status = ProtocolStatus.RUNNING
            logger.info("FANUC FOCAS server started on %s:%d", self._host, self._port)
            self._log_debug("system", "server_start",
                            f"FANUC service started {self._host}:{self._port}",
                            detail={"host": self._host, "port": self._port})
        except Exception as e:
            self._status = ProtocolStatus.ERROR
            logger.exception("Failed to start FANUC server: %s", e)
            raise

    async def stop(self) -> None:
        try:
            self._server_running = False
            if self._server_task:
                self._server_task.cancel()
                try:
                    await self._server_task
                except asyncio.CancelledError:
                    logger.debug("FANUC task cancelled")
        except Exception as e:
            logger.warning("FANUC server stop error: %s", e)
        finally:
            self._status = ProtocolStatus.STOPPED
            logger.info("FANUC server stopped")
            self._log_debug("system", "server_stop", "FANUC service stopped")

    async def _serve(self) -> None:
        try:
            server = await asyncio.start_server(
                self._handle_connection, self._host, self._port
            )
            async with server:
                await server.serve_forever()
        except asyncio.CancelledError:
            logger.debug("FANUC server task cancelled")
        except Exception as e:
            logger.exception("FANUC server error: %s", e)
            self._status = ProtocolStatus.ERROR

    async def _handle_connection(self, reader: asyncio.StreamReader,
                                  writer: asyncio.StreamWriter) -> None:
        addr = writer.get_extra_info("peername")
        logger.debug("FANUC connection from %s", addr)
        _READ_TIMEOUT = 30
        try:
            while self._server_running:
                data = await asyncio.wait_for(reader.read(4096), timeout=_READ_TIMEOUT)
                if not data:
                    break
                # FIXED: 原始报文日志（raw_frames=true 时记录收到的 16 进制字节流）
                if self._raw_frames:
                    self._log_debug("rx", "frame_rx",
                                    f"RX {len(data)} bytes from {addr}",
                                    detail={"hex": self._hex_dump(data), "peer": str(addr), "length": len(data)})
                response = self._process_focas(data)
                if response:
                    # FIXED: 原始报文日志（响应方向）
                    if self._raw_frames:
                        self._log_debug("tx", "frame_tx",
                                        f"TX {len(response)} bytes to {addr}",
                                        detail={"hex": self._hex_dump(response), "peer": str(addr), "length": len(response)})
                    writer.write(response)
                    await writer.drain()
        except (ConnectionResetError, asyncio.CancelledError, asyncio.TimeoutError, asyncio.IncompleteReadError, BrokenPipeError, ConnectionAbortedError) as e:
            self.record_protocol_error(ProtocolErrorCategory.NETWORK, str(e))
            logger.debug("Connection handler error: %s", e)  # FIXED: 添加日志记录，避免异常被静默吞掉
        except Exception as e:  # FIXED-P1: 兜底捕获所有其他异常，避免单个帧处理错误导致整个连接崩溃
            self.record_protocol_error(ProtocolErrorCategory.INTERNAL, str(e))
            logger.exception("FANUC connection handler unexpected error: %s", e)
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception as e:
                logger.debug("Writer wait_closed error: %s", e)

    _RAW_HEX_MAX_BYTES = 256  # 原始报文日志单帧最大转储字节数，防止大帧刷屏

    def _hex_dump(self, data: bytes) -> str:
        """转储为空格分隔的大写 16 进制；超出上限截断并标注总长。"""
        if len(data) <= self._RAW_HEX_MAX_BYTES:
            return data.hex(" ").upper()
        return data[:self._RAW_HEX_MAX_BYTES].hex(" ").upper() + f" … (total {len(data)} bytes)"

    def _process_focas(self, data: bytes) -> bytes | None:
        if len(data) < self.FOCAS_HEADER_SIZE:
            return None

        # FIXED: DBP 数据块协议（EdgeLite Go 版 FOCAS/Ethernet 客户端使用）。
        # 帧格式： "DBP\0" | 数据长度(uint32 LE) | 载荷
        # 载荷：   dummy(uint16 LE) | body长度(uint16 LE) | 命令码/返回码(uint16 LE) | 数据长度(uint16 LE) | 数据
        if data[:4] == self.DBP_MAGIC:
            return self._process_dbp(data)

        if data[:4] == b"FANC":
            return self._process_focas2_ethernet(data)
        else:
            return self._process_focas_legacy(data)

    # ------------------------------------------------------------------
    # DBP 数据块协议（与 EdgeLite internal/drivers/fanuc_cnc.go 帧格式对齐）
    # 请求载荷： dummy | bodyLen | 命令码 | dataLen | 请求体
    # 响应载荷： dummy | bodyLen | 返回码(0=成功) | dataLen | 响应体
    # ------------------------------------------------------------------

    # DBP 命令码（与 EdgeLite focasCmd* 常量一致，FOCAS 函数编号）
    DBP_CMD_CONNECT = 0x0016      # cnc_allclibhndl3
    DBP_CMD_DISCONNECT = 0x0014   # cnc_freelibhndl
    DBP_CMD_STATINFO = 0x0098     # cnc_statinfo
    DBP_CMD_RD_PRG_NUM = 0x0080   # cnc_rdprgnum
    DBP_CMD_EXE_PRG_NAME = 0x0026 # cnc_exeprgname
    DBP_CMD_ACTF = 0x0094         # cnc_actf 实际进给率
    DBP_CMD_ACTS = 0x0095         # cnc_acts 实际主轴转速
    DBP_CMD_RD_OVRD = 0x00A4      # cnc_rdovrd 倍率
    DBP_CMD_RD_POSITION = 0x00A2  # cnc_rdposition 坐标
    DBP_CMD_RD_ALARM = 0x00A0     # cnc_rdalaim 报警
    DBP_CMD_RD_SEQ_NUM = 0x0082   # cnc_rdseqnum 顺序号
    DBP_CMD_RD_PARAM = 0x0027     # cnc_rdparam 参数（加工计数/运行/切削时间）
    DBP_CMD_RD_TOOL_NUM = 0x015D  # cnc_rdtoolnum 当前刀号

    def _process_dbp(self, data: bytes) -> bytes | None:
        if len(data) < 8:
            return None
        payload_len = struct.unpack("<I", data[4:8])[0]
        if payload_len < 8 or payload_len > 1 << 20:
            return None
        if len(data) < 8 + payload_len:
            return None  # 半包：等待更多数据（EdgeLite 请求-响应串行，不会出现）
        payload = data[8:8 + payload_len]
        if len(payload) < 8:
            return None
        cmd = struct.unpack("<H", payload[4:6])[0]
        data_len = struct.unpack("<H", payload[6:8])[0]
        body = payload[8:8 + data_len]
        return self._dispatch_dbp(cmd, body)

    def _dbp_response(self, ret: int, out: bytes = b"") -> bytes:
        """构造 DBP 响应帧： dummy | bodyLen(4+dataLen) | ret | dataLen | data。"""
        payload = bytearray()
        payload += struct.pack("<H", 0)
        payload += struct.pack("<H", 4 + len(out))
        payload += struct.pack("<H", ret & 0xFFFF)
        payload += struct.pack("<H", len(out))
        payload += out
        frame = bytearray(self.DBP_MAGIC)
        frame += struct.pack("<I", len(payload))
        frame += payload
        return bytes(frame)

    def _dbp_device(self):
        """DBP 无会话概念，路由到默认设备（单设备场景）。"""
        device_id = self._default_device_id or (next(iter(self._behaviors), ""))
        return self._behaviors.get(device_id)

    @staticmethod
    def _exec_to_status(execution: int) -> int:
        """PF execution(1=RUN/2=STOP/3=HOLD) → EdgeLite CNCStatus 码空间(0-6)。"""
        return {1: 4, 2: 1, 3: 2}.get(execution, 0)  # running/stop/hold/reset

    @staticmethod
    def _program_number(behavior) -> int:
        if not behavior:
            return 0
        prog = str(behavior._cnc_status.get("program", "O0001"))
        digits = "".join(ch for ch in prog if ch.isdigit())
        return int(digits) if digits else 0

    def _dispatch_dbp(self, cmd: int, body: bytes) -> bytes:
        behavior = self._dbp_device()
        st = behavior._cnc_status if behavior else {}

        if cmd == self.DBP_CMD_CONNECT:
            return self._dbp_response(0)
        if cmd == self.DBP_CMD_DISCONNECT:
            return self._dbp_response(0)

        if cmd == self.DBP_CMD_STATINFO:
            # EdgeLite 解码： data[0:2]=状态码(CNCStatus 空间), data[2:4]=模式码(CNCMode 空间)，
            # 且要求 len(data) >= 10（真实 ODBST 结构更长），补齐 12 字节。
            status = self._exec_to_status(int(st.get("execution", 1)))
            mode = int(st.get("mode", 0)) & 0xFFFF
            alarm = int(st.get("alarm", 0))
            return self._dbp_response(0, struct.pack("<HHHHHH", status, mode, alarm, 0, 0, 0))

        if cmd == self.DBP_CMD_RD_PRG_NUM:
            # EdgeLite 解码： data[4:8]=程序号 int32
            prog = self._program_number(behavior)
            return self._dbp_response(0, struct.pack("<HHi", 0, 0, prog))

        if cmd == self.DBP_CMD_EXE_PRG_NAME:
            prog = str(st.get("program", "O0001")).encode("ascii", errors="replace")
            return self._dbp_response(0, prog)

        if cmd == self.DBP_CMD_ACTS:
            # EdgeLite 解码： data[0:2]=主轴实际转速 int16
            speed = int(float(st.get("spindle_speed", FanucDeviceBehavior._DEFAULT_SPINDLE_SPEED)))
            return self._dbp_response(0, struct.pack("<h", max(-32768, min(32767, speed))))

        if cmd == self.DBP_CMD_ACTF:
            # EdgeLite 解码： data[0:2]=实际进给率 int16
            feed = int(float(st.get("feed_rate", FanucDeviceBehavior._DEFAULT_FEED_RATE)))
            return self._dbp_response(0, struct.pack("<h", max(-32768, min(32767, feed))))

        if cmd == self.DBP_CMD_RD_OVRD:
            # EdgeLite 解码： data[0:2]=进给倍率, data[2:4]=主轴倍率 int16
            feed_ovrd = int(st.get("feed_override", FanucDeviceBehavior._DEFAULT_OVERRIDE))
            speed_ovrd = int(st.get("speed_override", FanucDeviceBehavior._DEFAULT_OVERRIDE))
            return self._dbp_response(0, struct.pack("<hh", feed_ovrd, speed_ovrd))

        if cmd == self.DBP_CMD_RD_POSITION:
            # 请求体： [posType uint16][axis uint16]；响应： data[0:4]=坐标 int32(1/1000 mm)
            if len(body) < 4:
                return self._dbp_response(2)
            pos_type, axis = struct.unpack("<HH", body[0:4])
            key = {0: "absolute_pos", 1: "machine_pos",
                   2: "relative_pos", 3: "distance_pos"}.get(pos_type)
            if key is None:
                return self._dbp_response(2)
            positions = st.get(key, [0.0])
            pos = float(positions[axis]) if 0 <= axis < len(positions) else 0.0
            return self._dbp_response(0, struct.pack("<i", int(pos * 1000)))

        if cmd == self.DBP_CMD_RD_ALARM:
            # EdgeLite 解码： data[0:2]=报警号 int16, data[2:34]=32字节报警信息
            alm = int(st.get("alarm", 0))
            msg = b"ALARM" if alm > 0 else b""
            msg = msg[:32].ljust(32, b"\x00")
            return self._dbp_response(0, struct.pack("<h", alm) + msg)

        if cmd == self.DBP_CMD_RD_SEQ_NUM:
            seq = int(st.get("sequence_number", 0))
            return self._dbp_response(0, struct.pack("<i", seq))

        if cmd == self.DBP_CMD_RD_PARAM:
            # 请求体： [paramNo uint16][length uint16=4]；EdgeLite 读 data 末 4 字节 int32
            if len(body) < 4:
                return self._dbp_response(2)
            param_no, _ = struct.unpack("<HH", body[0:4])
            params = {6711: "parts_count", 6751: "running_time", 6752: "cutting_time"}
            value = int(st.get(params.get(param_no, ""), 0))
            return self._dbp_response(0, struct.pack("<HHi", param_no, 4, value))

        if cmd == self.DBP_CMD_RD_TOOL_NUM:
            tool = int(st.get("tool_number", 5))
            return self._dbp_response(0, struct.pack("<h", tool))

        # 未知命令： 返回非 0 错误码（EdgeLite 按命令失败处理）
        return self._dbp_response(1)

    def _process_focas2_ethernet(self, data: bytes) -> bytes | None:
        if len(data) < 12:
            return None
        session_id = struct.unpack(">H", data[4:6])[0]
        msg_len = struct.unpack(">H", data[6:8])[0]
        if msg_len == 0 or msg_len > 4096:  # FIXED-R04: FOCAS2消息长度校验，0=无效，>4096=超出合理范围
            return None
        if len(data) < 8 + msg_len:
            return None
        payload = data[8:8 + msg_len]
        if len(payload) < 4:
            return None
        func_id = struct.unpack("<H", payload[0:2])[0]
        req_id = struct.unpack("<I", payload[2:6])[0] if len(payload) >= 6 else 0
        result = self._dispatch_focas_function(func_id, req_id, payload[6:] if len(payload) > 6 else b"", session_id)  # FIXED-P0: 传入session_id
        resp_payload = bytearray()
        resp_payload += struct.pack("<H", func_id)
        resp_payload += struct.pack("<I", req_id)
        resp_payload += result
        resp = bytearray(b"FANC")
        resp += struct.pack(">H", session_id)
        resp += struct.pack(">H", len(resp_payload))
        resp += resp_payload
        return bytes(resp)

    def _process_focas_legacy(self, data: bytes) -> bytes | None:
        func_id = struct.unpack("<H", data[0:2])[0]
        req_id = struct.unpack("<I", data[2:6])[0]
        payload = data[10:] if len(data) > 10 else b""
        result = self._dispatch_focas_function(func_id, req_id, payload)  # FIXED-P0: legacy无session_id
        resp = bytearray()
        resp += struct.pack("<H", func_id)
        resp += struct.pack("<I", req_id)
        resp += struct.pack("<I", 0x00000000)
        resp += result
        return bytes(resp)

    def _dispatch_focas_function(self, func_id: int, req_id: int, payload: bytes, session_id: int = 0) -> bytes:  # FIXED-P0: 传入session_id
        handlers = {
            0x0001: self._handle_cnc_connect,
            0x0002: self._handle_cnc_disconnect,
            0x0101: self._handle_cnc_statinfo,
            0x0102: self._handle_cnc_absolute,
            0x0103: self._handle_cnc_machine,
            0x0104: self._handle_cnc_relative,
            0x0105: self._handle_cnc_distance,
            0x0110: self._handle_cnc_rdspindlespd,
            0x0111: self._handle_cnc_rdfeed,
            0x0120: self._handle_cnc_alarm,
            0x0130: self._handle_cnc_program,
            0x0131: self._handle_cnc_sysinfo,  # FIXED-P1: CNC系列信息查询
        }
        handler = handlers.get(func_id)
        if handler:
            return handler(req_id, session_id)  # FIXED-P0: 传入session_id
        return self._make_focas_error(req_id, 0x00000001)

    def _resolve_device(self, session_id: int) -> str:  # FIXED-P0: 根据session_id路由到对应CNC设备
        device_id = self._session_device_map.get(session_id)
        if device_id and device_id in self._behaviors:
            return device_id
        return self._default_device_id or ""

    def _handle_cnc_connect(self, req_id: int, session_id: int = 0) -> bytes:  # FIXED-P0
        assigned_session = self._next_session_id
        self._next_session_id += 1
        device_ids = list(self._behaviors.keys())
        if device_ids:
            target_idx = (assigned_session - 1) % len(device_ids)
            self._session_device_map[assigned_session] = device_ids[target_idx]
        resp = bytearray()
        resp += struct.pack("<H", 0x0001)
        resp += struct.pack("<I", req_id)
        resp += struct.pack("<I", 0x00000000)
        resp += struct.pack("<I", 0x00000001)
        return bytes(resp)

    def _handle_cnc_disconnect(self, req_id: int, session_id: int = 0) -> bytes:  # FIXED-P0
        self._session_device_map.pop(session_id, None)
        resp = bytearray()
        resp += struct.pack("<H", 0x0002)
        resp += struct.pack("<I", req_id)
        resp += struct.pack("<I", 0x00000000)
        return bytes(resp)

    def _handle_cnc_statinfo(self, req_id: int, session_id: int = 0) -> bytes:  # FIXED-P0
        device_id = self._resolve_device(session_id)
        behavior = self._behaviors.get(device_id)
        status = behavior._cnc_status if behavior else {
            "alarm": 0, "mode": 3, "execution": 1, "motion": 0
        }

        resp = bytearray()
        resp += struct.pack("<H", 0x0101)
        resp += struct.pack("<I", req_id)
        resp += struct.pack("<I", 0x00000000)
        resp += struct.pack("<H", status.get("alarm", 0))
        resp += struct.pack("<H", status.get("mode", 3))
        resp += struct.pack("<H", status.get("execution", 1))
        resp += struct.pack("<H", status.get("motion", 0))
        return bytes(resp)

    def _handle_cnc_absolute(self, req_id: int, session_id: int = 0) -> bytes:  # FIXED-P0
        device_id = self._resolve_device(session_id)
        behavior = self._behaviors.get(device_id)
        axis_count = self._device_params.get(device_id, {}).get("axis_count", 3)
        positions = behavior._cnc_status.get("absolute_pos", [0.0] * axis_count) if behavior else [0.0] * axis_count

        resp = bytearray()
        resp += struct.pack("<H", 0x0102)
        resp += struct.pack("<I", req_id)
        resp += struct.pack("<I", 0x00000000)
        resp += struct.pack("<H", axis_count)
        for pos in positions[:axis_count]:
            resp += struct.pack("<d", pos)
        return bytes(resp)

    def _handle_cnc_machine(self, req_id: int, session_id: int = 0) -> bytes:  # FIXED-P0
        device_id = self._resolve_device(session_id)
        behavior = self._behaviors.get(device_id)
        axis_count = self._device_params.get(device_id, {}).get("axis_count", 3)
        positions = behavior._cnc_status.get("machine_pos", [0.0] * axis_count) if behavior else [0.0] * axis_count

        resp = bytearray()
        resp += struct.pack("<H", 0x0103)
        resp += struct.pack("<I", req_id)
        resp += struct.pack("<I", 0x00000000)
        resp += struct.pack("<H", axis_count)
        for pos in positions[:axis_count]:
            resp += struct.pack("<d", pos)
        return bytes(resp)

    def _handle_cnc_relative(self, req_id: int, session_id: int = 0) -> bytes:  # FIXED-P0
        device_id = self._resolve_device(session_id)
        behavior = self._behaviors.get(device_id)
        axis_count = self._device_params.get(device_id, {}).get("axis_count", 3)
        positions = behavior._cnc_status.get("relative_pos", [0.0] * axis_count) if behavior else [0.0] * axis_count

        resp = bytearray()
        resp += struct.pack("<H", 0x0104)
        resp += struct.pack("<I", req_id)
        resp += struct.pack("<I", 0x00000000)
        resp += struct.pack("<H", axis_count)
        for pos in positions[:axis_count]:
            resp += struct.pack("<d", pos)
        return bytes(resp)

    def _handle_cnc_distance(self, req_id: int, session_id: int = 0) -> bytes:  # FIXED-P0
        device_id = self._resolve_device(session_id)
        behavior = self._behaviors.get(device_id)
        axis_count = self._device_params.get(device_id, {}).get("axis_count", 3)
        positions = behavior._cnc_status.get("distance_pos", [0.0] * axis_count) if behavior else [0.0] * axis_count

        resp = bytearray()
        resp += struct.pack("<H", 0x0105)
        resp += struct.pack("<I", req_id)
        resp += struct.pack("<I", 0x00000000)
        resp += struct.pack("<H", axis_count)
        for pos in positions[:axis_count]:
            resp += struct.pack("<d", pos)
        return bytes(resp)

    def _handle_cnc_rdspindlespd(self, req_id: int, session_id: int = 0) -> bytes:  # FIXED-P0
        device_id = self._resolve_device(session_id)
        behavior = self._behaviors.get(device_id)
        speed = behavior._cnc_status.get("spindle_speed", 3000.0) if behavior else 3000.0  # 默认3000 rpm

        resp = bytearray()
        resp += struct.pack("<H", 0x0110)
        resp += struct.pack("<I", req_id)
        resp += struct.pack("<I", 0x00000000)
        resp += struct.pack("<d", float(speed))
        return bytes(resp)

    def _handle_cnc_rdfeed(self, req_id: int, session_id: int = 0) -> bytes:  # FIXED-P0
        device_id = self._resolve_device(session_id)
        behavior = self._behaviors.get(device_id)
        feed = behavior._cnc_status.get("feed_rate", 500.0) if behavior else 500.0  # 默认500进给速度

        resp = bytearray()
        resp += struct.pack("<H", 0x0111)
        resp += struct.pack("<I", req_id)
        resp += struct.pack("<I", 0x00000000)
        resp += struct.pack("<d", float(feed))
        return bytes(resp)

    def _handle_cnc_alarm(self, req_id: int, session_id: int = 0) -> bytes:  # FIXED-P0
        device_id = self._resolve_device(session_id)
        behavior = self._behaviors.get(device_id)
        alarm = behavior._cnc_status.get("alarm", 0) if behavior else 0

        resp = bytearray()
        resp += struct.pack("<H", 0x0120)
        resp += struct.pack("<I", req_id)
        resp += struct.pack("<I", 0x00000000)
        resp += struct.pack("<H", alarm)
        if alarm > 0:
            resp += struct.pack("<H", 1)
            resp += struct.pack("<H", alarm)
            resp += struct.pack("<H", 1)
            resp += b"ALM\x00"
        else:
            resp += struct.pack("<H", 0)
        return bytes(resp)

    def _handle_cnc_program(self, req_id: int, session_id: int = 0) -> bytes:  # FIXED-P0
        device_id = self._resolve_device(session_id)
        behavior = self._behaviors.get(device_id)
        prog = behavior._cnc_status.get("program", "O0001") if behavior else "O0001"

        resp = bytearray()
        resp += struct.pack("<H", 0x0130)
        resp += struct.pack("<I", req_id)
        resp += struct.pack("<I", 0x00000000)
        prog_bytes = prog.encode("ascii", errors="replace")
        resp += struct.pack("<H", len(prog_bytes))
        resp += prog_bytes
        return bytes(resp)

    def _handle_cnc_sysinfo(self, req_id: int, session_id: int = 0) -> bytes:  # FIXED-P1: CNC系列信息
        device_id = self._resolve_device(session_id)
        cnc_type = self._device_params.get(device_id, {}).get("cnc_type", "0i-F")
        type_map = {  # FIXED-P1: 不同CNC系列返回不同系列代码
            "16i": (0x16, 0x00), "18i": (0x18, 0x00), "21i": (0x21, 0x00),
            "30i": (0x30, 0x00), "31i": (0x31, 0x00), "32i": (0x32, 0x00),
            "0i-F": (0x00, 0x0F), "0i-TD": (0x00, 0x0D), "0i-MD": (0x00, 0x0E),
        }
        series_code, sub_code = type_map.get(cnc_type, (0x00, 0x0F))
        resp = bytearray()
        resp += struct.pack("<H", 0x0131)
        resp += struct.pack("<I", req_id)
        resp += struct.pack("<I", 0x00000000)
        resp += struct.pack("<H", series_code)
        resp += struct.pack("<H", sub_code)
        resp += struct.pack("<H", 0x0002)  # version
        resp += struct.pack("<H", 0x0001)  # axes
        return bytes(resp)

    def _make_focas_error(self, req_id: int, error_code: int) -> bytes:
        resp = bytearray()
        resp += struct.pack("<H", 0xFFFF)
        resp += struct.pack("<I", req_id)
        resp += struct.pack("<I", error_code)
        return bytes(resp)

    async def create_device(self, device_config: DeviceConfig) -> str:
        behavior = FanucDeviceBehavior(device_config.points)
        proto_config = device_config.protocol_config or {}
        async with self._behaviors_lock:
            self._behaviors[device_config.id] = behavior
            self._device_configs[device_config.id] = device_config  # FIXED: S6 - move _device_configs write inside _behaviors_lock for consistency
            self._device_params[device_config.id] = {  # FIXED-P1: 移入_behaviors_lock内保护
                "cnc_type": proto_config.get("cnc_type", "0i-F"),
                "axis_count": proto_config.get("axis_count", 3),
            }
        await self._update_default_device_async(device_config.id)

        axis_count = self._device_params[device_config.id]["axis_count"]
        for key in ["absolute_pos", "machine_pos", "relative_pos", "distance_pos"]:
            current = behavior._cnc_status[key]
            if len(current) < axis_count:
                behavior._cnc_status[key] = current + [0.0] * (axis_count - len(current))

        # FIXED: 点位初值（如 fixed_value 生成器）必须同步进 _cnc_status，
        # 否则 DBP/FOCAS 协议读到的永远是内置默认值，与设备状态脱节。
        for p in device_config.points:
            try:
                val = behavior.get_value(p.name)
            except Exception:
                continue
            if val is None:
                continue
            self._sync_cnc_field(behavior, p.name, val)

        logger.info("FANUC device created: %s (cnc_type=%s, axis=%d)",
                     device_config.id,
                     self._device_params[device_config.id]["cnc_type"],
                     axis_count)
        self._log_debug("system", "device_create",
                        f"FANUC device created: {device_config.name}",
                        device_id=device_config.id)
        return device_config.id

    async def remove_device(self, device_id: str) -> None:
        async with self._behaviors_lock:
            self._behaviors.pop(device_id, None)
            self._device_configs.pop(device_id, None)  # FIXED: S6 - move _device_configs write inside _behaviors_lock for consistency
            self._device_params.pop(device_id, None)  # FIXED-P1: 移入_behaviors_lock内保护
        await self._clear_default_device_async(device_id)
        logger.info("FANUC device removed: %s", device_id)
        self._log_debug("system", "device_remove",
                        f"FANUC device removed: {device_id}",
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

    def _sync_cnc_field(self, behavior: FanucDeviceBehavior, point_name: str, value: Any) -> None:
        """将点位值同步到 _cnc_status 对应字段（sync_point_value 与 create_device 共用）。"""
        if point_name == "spindle_speed":
            behavior._cnc_status["spindle_speed"] = value
        elif point_name == "feed_rate":
            behavior._cnc_status["feed_rate"] = value
        elif point_name == "x_pos":
            behavior._cnc_status["absolute_pos"][0] = value
            behavior._cnc_status["machine_pos"][0] = value
        elif point_name == "y_pos":
            behavior._cnc_status["absolute_pos"][1] = value
            behavior._cnc_status["machine_pos"][1] = value
        elif point_name == "z_pos":
            behavior._cnc_status["absolute_pos"][2] = value
            behavior._cnc_status["machine_pos"][2] = value
        elif point_name in ("alarm", "mode", "execution", "speed_override", "feed_override"):
            behavior._cnc_status[point_name] = value
        elif point_name == "program":
            behavior._cnc_status["program"] = str(value)
        elif point_name in ("tool_number", "sequence_number", "parts_count",
                            "running_time", "cutting_time"):
            behavior._cnc_status[point_name] = value
        elif point_name.startswith("abs_pos_"):
            try:
                idx = int(point_name.rsplit("_", maxsplit=1)[-1])
                if idx < len(behavior._cnc_status["absolute_pos"]):
                    behavior._cnc_status["absolute_pos"][idx] = value
                    behavior._cnc_status["machine_pos"][idx] = value
            except (ValueError, IndexError):
                pass

    async def sync_point_value(self, device_id: str, point_name: str, value: Any) -> None:
        """内部同步：更新 Fanuc CNC 状态数据，绕过访问控制检查。

        直接更新 _values 和 _cnc_status，不设置 _written_values，
        避免冻结生成器。
        """
        behavior = self._behaviors.get(device_id)
        if not behavior:
            return
        behavior._values[point_name] = value
        # 同步到 _cnc_status（协议处理器从这里读取数据）
        self._sync_cnc_field(behavior, point_name, value)

    def get_config_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "host": {"type": "string", "default": "0.0.0.0", "description": desc("listen_address", "FOCAS server listen address")},
                "port": {"type": "integer", "default": 8193, "description": desc("fanuc_port", "FOCAS port (default 8193)")},
                "cnc_type": {"type": "string", "default": "0i-F", "enum": ["0i-F", "0i-TD", "0i-MD", "16i", "18i", "21i", "30i", "31i", "32i"], "description": desc("cnc_type", "CNC series type")},  # FIXED-P1
                "axis_count": {"type": "integer", "default": 3, "minimum": 1, "maximum": 8, "description": desc("axis_count", "Number of CNC axes")},  # FIXED-P1
                "raw_frames": {"type": "boolean", "default": False, "description": desc("raw_frames", "Log raw hex frames (rx/tx) in the protocol debug log — for protocol study")},
            },
        }
