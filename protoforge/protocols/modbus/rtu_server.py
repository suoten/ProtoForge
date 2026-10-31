"""Module: rtu server."""

import asyncio
import logging
import socket
import struct
import sys
import time
from typing import Any

from protoforge.models.device import DeviceConfig, PointConfig, PointValue
from protoforge.protocols.base import ProtocolErrorCategory, ProtocolServer, ProtocolStatus
from protoforge.protocols.modbus._common import (
    WRITE_FC_AREA_MAP,
    ModbusDataStore,
    ModbusDeviceBehavior,
    crc16_modbus,
    parse_modbus_address,
    point_area,
    point_reg_count,
)

logger = logging.getLogger(__name__)

try:
    import serial  # pyserial（FIXED(Issue#36): 显式依赖，见 pyproject dependencies）
    _SERIAL_AVAILABLE = True
except ImportError:  # pragma: no cover - 环境缺依赖时给出明确报错
    serial = None  # type: ignore[assignment]
    _SERIAL_AVAILABLE = False


class ModbusRtuServer(ProtocolServer):
    protocol_name = "modbus_rtu"
    protocol_display_name = "Modbus RTU"

    _MAX_READ_COILS = 2000
    _MAX_READ_REGISTERS = 125
    _VALID_BAUDRATES = {2400, 4800, 9600, 19200, 38400, 57600, 115200}

    def __init__(self):
        super().__init__()
        self._server_task: asyncio.Task | None = None
        self._serial: Any = None  # pyserial Serial 实例（串口模式）
        self._behaviors: dict[str, ModbusDeviceBehavior] = {}
        self._device_configs: dict[str, DeviceConfig] = {}
        self._port = "/dev/ttyUSB0" if sys.platform != "win32" else "COM1"
        self._baudrate = 9600
        self._parity = "N"
        self._stopbits = 1
        self._bytesize = 8
        self._slave_map: dict[str, int] = {}
        self._next_slave_id = 1
        self._data_stores: dict[int, ModbusDataStore] = {}

    def _on_server_task_done(self, task: asyncio.Task) -> None:
        try:
            task.result()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.exception("Modbus RTU server task failed: %s", e)
            self._status = ProtocolStatus.ERROR

    def _get_data_store(self, slave_id: int) -> ModbusDataStore:
        if slave_id not in self._data_stores:
            self._data_stores[slave_id] = ModbusDataStore()
        return self._data_stores[slave_id]

    async def start(self, config: dict[str, Any]) -> None:
        self._status = ProtocolStatus.STARTING
        default_port = "/dev/ttyUSB0" if sys.platform != "win32" else "COM1"
        raw_port = config.get("port", default_port)
        mode = str(config.get("mode", "serial")).lower()
        if isinstance(raw_port, int):
            # Integration clients (edgelite push) send an int `port` meaning
            # "serve RTU-over-TCP on this TCP port" — explicit bridge mode.
            mode = "tcp_bridge"
            config.setdefault("tcp_bridge_port", raw_port)
            self._port = default_port
        else:
            self._port = raw_port
        self._baudrate = config.get("baudrate", 9600)
        if self._baudrate not in self._VALID_BAUDRATES:
            raise ValueError(
                f"Invalid baudrate {self._baudrate}. Must be one of: {sorted(self._VALID_BAUDRATES)}"
            )
        self._parity = config.get("parity", "N")
        if self._parity not in ("N", "E", "O"):
            raise ValueError(f"Parity must be N (None), E (Even), or O (Odd) (got '{self._parity}')")
        self._stopbits = config.get("stopbits", 1)
        if self._stopbits not in (1, 1.5, 2):
            raise ValueError(f"Stop bits must be 1, 1.5, or 2 (got '{self._stopbits}')")
        self._bytesize = config.get("bytesize", 8)
        if self._bytesize not in (5, 6, 7, 8):
            raise ValueError(f"Data bits (bytesize) must be 5, 6, 7, or 8 (got {self._bytesize})")

        if mode == "tcp_bridge":
            # 显式桥接模式：MBAP(TCP 帧) 直连原生帧处理器，不占用串口
            tcp_bridge_port = config.get("tcp_bridge_port", 5021)
            self._validate_port(tcp_bridge_port)
            tcp_bridge_port = self._find_available_port(tcp_bridge_port)
            logger.info("Modbus RTU starting in explicit TCP bridge mode on port %d", tcp_bridge_port)
            self._server_task = asyncio.create_task(self._serve_datastore_only(tcp_bridge_port))
            self._server_task.add_done_callback(self._on_server_task_done)
            self._status = ProtocolStatus.RUNNING
            self._log_debug("system", "server_start",
                            f"Modbus RTU TCP bridge started on port {tcp_bridge_port}",
                            detail={"mode": "tcp_bridge", "port": tcp_bridge_port})
            return

        # FIXED(Issue#36): 串口模式——真正打开并占用串口。
        # 旧实现因 pymodbus 3.13 OldAPI 失效而静默回退 TCP bridge（串口永不
        # 被打开，用户在串口监视工具里看到 COM 口"空闲"）。现改为自持串口
        # IO + 原生帧处理器（与 TCP server 共用 _process_modbus_frame），
        # 不再依赖 pymodbus 的串口 server 端；打开失败直接报明确错误，
        # 不做任何静默回退。
        if not _SERIAL_AVAILABLE:
            self._status = ProtocolStatus.ERROR
            raise RuntimeError(
                "pyserial is not installed — cannot open serial port. "
                "Install with: pip install protoforge (pyserial is a core dependency)"
            )
        try:
            self._open_serial()
        except Exception as e:
            self._serial = None
            self._status = ProtocolStatus.ERROR
            logger.error("Modbus RTU: failed to open serial port %s: %s", self._port, e)
            raise RuntimeError(
                f"无法打开串口 {self._port}（{type(e).__name__}: {e}）。"
                f"请确认：①串口存在且未被其他程序占用；②Windows 上设备管理器中有该 COM 口。"
                f"若仅需 TCP 测试，可将模式切换为 tcp_bridge。"
            ) from e

        try:
            self._server_task = asyncio.create_task(self._serve_serial_native())
            self._server_task.add_done_callback(self._on_server_task_done)
            self._status = ProtocolStatus.RUNNING
            logger.info("Modbus RTU server listening on %s @ %d baud (native serial)",
                        self._port, self._baudrate)
            self._log_debug("system", "server_start",
                            f"Modbus RTU service started: {self._port} @ {self._baudrate}",
                            detail={"port": self._port, "baudrate": self._baudrate, "mode": "serial"})
        except Exception as e:
            self._status = ProtocolStatus.ERROR
            logger.exception("Failed to start Modbus RTU server: %s", e)
            raise

    def _open_serial(self) -> None:
        """打开串口（真正占用 COM 口）。测试可覆写/patch 此方法注入假串口。"""
        ser = serial.Serial(  # type: ignore[union-attr]
            port=self._port,
            baudrate=self._baudrate,
            bytesize=self._bytesize,
            parity=self._parity,
            stopbits=self._stopbits,
            timeout=0.05,   # 阻塞读上限，保证 stop 时 executor 线程及时退出
            write_timeout=1.0,
        )
        self._serial = ser

    async def _serve_serial_native(self) -> None:
        """自持串口 RTU 帧循环：idle 分帧 → CRC 校验 → 复用 _process_modbus_frame。

        FIXED(Issue#36): pymodbus 3.13 的串口 server 端（SimData/OldAPI）在
        写值路径失效（async_setValues 返回 DEVICE_BUSY），旧代码因此整体放弃
        串口改为静默 TCP bridge。此实现绕开 pymodbus server 端，值通路与
        TCP 模式完全一致（behaviors/_data_stores）。
        """
        loop = asyncio.get_running_loop()

        def _read_some() -> bytes:
            ser = self._serial
            if ser is None or not ser.is_open:
                return b""
            n = ser.in_waiting
            return ser.read(n if n > 0 else 1)

        try:
            buf = bytearray()
            while True:
                chunk = await loop.run_in_executor(None, _read_some)
                if chunk:
                    buf.extend(chunk)
                    # RTU 帧间隔（3.5 字符 @9600bps≈4ms）——再给一拍静默时间
                    # 让整帧到齐；in_waiting 已含整帧时无需额外等待
                    tail = await loop.run_in_executor(None, _read_some)
                    if tail:
                        buf.extend(tail)
                if not buf:
                    await asyncio.sleep(0.02)
                    continue
                frame = self._extract_rtu_frame(buf)
                if frame is None:
                    # 半帧等待更多字节；连续无新数据时由上层 timeout 机制兜底
                    if not chunk:
                        await asyncio.sleep(0.02)
                    continue
                addr, resp_pdu = frame
                # Modbus 规范：广播（addr=0）只执行不响应
                if addr != 0 and resp_pdu is not None:
                    resp_frame = bytes([addr]) + resp_pdu
                    resp_frame += struct.pack("<H", crc16_modbus(resp_frame))
                    ser = self._serial
                    if ser is not None and ser.is_open:
                        await loop.run_in_executor(None, ser.write, bytes(resp_frame))
                await asyncio.sleep(0.005)
        except asyncio.CancelledError:
            logger.debug("Modbus RTU serial task cancelled")
            raise
        except Exception as e:
            logger.exception("Modbus RTU serial loop error: %s", e)
            self._status = ProtocolStatus.ERROR
            self.record_protocol_error(ProtocolErrorCategory.NETWORK, str(e))

    def _extract_rtu_frame(self, buf: bytearray) -> tuple[int, bytes | None] | None:
        """从缓冲中提取一个完整 RTU 帧：[addr][fc][data...][crc16 lo hi]。

        返回 (addr, PDU响应或None) 并消耗缓冲；帧不完整返回 None（保留缓冲）。
        """
        if len(buf) < 4:
            return None
        addr = buf[0]
        fc = buf[1]
        # 期望长度按功能码推导（请求帧）；异常/未知结构交给 CRC 兜底
        if fc in (5, 6, 0x0F, 0x10):
            if fc in (0x0F, 0x10) and len(buf) < 7:
                return None
            if len(buf) < 8:
                return None
            if fc in (0x0F, 0x10):
                byte_count = buf[6]
                expect = 7 + byte_count + 2
            else:
                expect = 8
        elif fc in (1, 2, 3, 4):
            expect = 8
        else:
            expect = 4  # 未知 fc：至少 addr+fc+crc2，交给 CRC 判定
        if len(buf) < expect:
            return None
        frame = bytes(buf[:expect])
        recv_crc = struct.unpack("<H", frame[-2:])[0]
        if crc16_modbus(frame[:-2]) != recv_crc:
            # CRC 不符：丢弃首字节（字节流错位恢复），等待重同步
            logger.debug("Modbus RTU frame CRC mismatch, resync (addr=%s fc=%s)", addr, fc)
            self.record_protocol_error(ProtocolErrorCategory.FRAME_PARSE, "RTU CRC mismatch")
            buf.pop(0)
            return None
        del buf[:expect]
        resp_pdu = self._process_modbus_frame(addr, fc, frame[2:-2])
        return addr, resp_pdu

    @staticmethod
    def _find_available_port(start_port: int, max_tries: int = 10) -> int:
        """从 start_port 开始寻找一个可用端口。"""
        for port in range(start_port, start_port + max_tries):
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.settimeout(0.5)
                    result = s.connect_ex(("127.0.0.1", port))
                    if result != 0:
                        return port  # 端口未被占用
            except Exception as e:
                logger.debug("_find_available_port: ignored exception: %s", e)
                return port  # 无法检测，假设可用
        return start_port  # 全部被占用，返回原始端口让后续报错

    async def _serve_datastore_only(self, tcp_port: int = 5021) -> None:
        logger.info("Modbus RTU running in TCP bridge mode on port %d (pymodbus serial unavailable)", tcp_port)
        try:
            server = await asyncio.start_server(
                self._handle_native_modbus_rtu, "0.0.0.0", tcp_port
            )
            async with server:
                await server.serve_forever()
        except asyncio.CancelledError:
            logger.debug("Modbus RTU server task cancelled")
        except Exception as e:
            logger.exception("Modbus RTU TCP bridge server error: %s", e)
            self._status = ProtocolStatus.ERROR

    async def _handle_native_modbus_rtu(self, reader: asyncio.StreamReader,
                                          writer: asyncio.StreamWriter) -> None:
        _RTU_CONN_TIMEOUT = 30  # FIXED-P0: TCP桥接模式添加读取超时，防止恶意客户端挂起连接
        try:
            while True:
                try:
                    header = await asyncio.wait_for(reader.readexactly(7), timeout=_RTU_CONN_TIMEOUT)
                except asyncio.TimeoutError:
                    break
                tx_id = struct.unpack(">H", header[0:2])[0]
                proto_id = struct.unpack(">H", header[2:4])[0]
                if proto_id != 0:  # FIXED-C01: MBAP Protocol ID必须为0(Modbus规范)，与TCP server保持一致
                    continue
                length = struct.unpack(">H", header[4:6])[0]
                if length < 1 or length > 253:  # FIXED-N12: MBAP length域范围校验，与TCP server保持一致
                    continue
                unit_id = header[6]
                if length > 1:
                    payload = await asyncio.wait_for(reader.readexactly(length - 1), timeout=_RTU_CONN_TIMEOUT)
                else:
                    payload = b""
                fc = payload[0] if payload else 0
                resp = self._process_modbus_frame(unit_id, fc, payload[1:])
                if resp is None:  # FIXED-C02: 广播读请求等场景返回None，跳过而非len(None)崩溃
                    continue
                mbap = struct.pack(">HHHB", tx_id, proto_id, len(resp) + 1, unit_id)
                writer.write(mbap + resp)
                await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionResetError, asyncio.CancelledError, BrokenPipeError, ConnectionAbortedError) as e:
            logger.debug("Modbus RTU connection handler error: %s", e)
        except Exception as e:  # FIXED-P1: 兜底捕获所有其他异常，避免单个帧处理错误导致整个连接崩溃
            self.record_protocol_error(ProtocolErrorCategory.INTERNAL, str(e))
            logger.exception("Modbus RTU connection handler unexpected error: %s", e)
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception as e:
                logger.debug("Modbus RTU writer close error: %s", e)

    def _check_external_write_access(
        self, slave_id: int, fc: int, start: int, count: int,
    ) -> tuple[str, str] | None:
        """检查外部写入的目标地址范围是否命中只读点位（access='r'）。

        与 TCP server 同源校验（FIXED：只读点位外部可写的语义缺口）。

        :param slave_id: 从站 ID（RTU 广播按 slave_id=1 处理，与写入目标一致）
        :param fc: 写入功能码
        :param start: 起始地址
        :param count: 写入的寄存器/线圈数量
        :return: 第一个被命中的只读点位 (device_id, point_name)，允许写入时返回 None
        """
        area = WRITE_FC_AREA_MAP.get(fc)
        if not area:
            return None
        end = start + max(count, 1)
        for device_id, s_id in self._slave_map.items():
            if s_id != slave_id:
                continue
            config = self._device_configs.get(device_id)
            if not config:
                continue
            for point in config.points:
                if point.access in ("w", "rw"):
                    continue
                try:
                    p_addr = parse_modbus_address(point.address)[0]
                    p_area = point_area(point)
                except (ValueError, TypeError):
                    continue
                if p_area != area:
                    continue
                if p_addr < end and start < p_addr + point_reg_count(point):
                    return device_id, point.name
        return None

    def _notify_external_write(self, slave_id: int, fc: int, address: int, value: Any) -> None:
        """外部 RTU-over-TCP 写入后异步触发 _on_write 回调，传播到 DeviceInstance。

        与 TCP server 的同名机制对齐：不通知时引擎侧 30 秒写入冻结建不起来，
        采集生成器会覆盖外部下发值（联调实测）。value=None 时从 store 读回实际值。
        """
        if not self._on_write:
            return
        area = WRITE_FC_AREA_MAP.get(fc)
        if not area:
            return
        target = None
        for device_id, s_id in self._slave_map.items():
            if s_id != slave_id:
                continue
            config = self._device_configs.get(device_id)
            if not config:
                continue
            for point in config.points:
                try:
                    p_addr = parse_modbus_address(point.address)[0]
                    p_area = point_area(point)
                except (ValueError, TypeError):
                    continue
                if p_area != area:
                    continue
                if p_addr <= address < p_addr + point_reg_count(point):
                    target = (device_id, point)
                    break
            if target:
                break
        if not target:
            return
        device_id, point = target
        if value is None:
            try:
                value = self._read_register(point, slave_id)
            except Exception as e:
                logger.debug("RTU read-back after external write failed for %s: %s", point.name, e)
            if value is None:
                return
        try:
            asyncio.create_task(self._fire_write_callback(device_id, point.name, value))
        except RuntimeError:
            pass

    async def _fire_write_callback(self, device_id: str, point_name: str, value: Any) -> None:
        try:
            await self._on_write(device_id, point_name, value)
        except Exception as e:
            logger.debug("Modbus RTU external write callback error for %s.%s: %s", device_id, point_name, e)

    def _reject_readonly_write(
        self, fc: int, slave_id: int, fc_name: str, start: int,
        readonly_hit: tuple[str, str],
    ) -> bytes:
        """外部写入命中只读点位时的统一拒绝处理：记日志并返回异常响应 (0x01)。"""
        device_id, point_name = readonly_hit
        logger.warning(
            "External Modbus RTU write rejected: point %s.%s is read-only (access='r'); "
            "fc=%s start=%d slave_id=%d",
            device_id, point_name, fc_name, start, slave_id,
        )
        self._log_debug(
            "inbound", "modbus_write_rejected",
            f"{fc_name}: addr={start} rejected (read-only point {device_id}.{point_name})",
            detail={"fc": fc, "start": start, "unit": slave_id,
                    "device_id": device_id, "point": point_name, "reason": "read_only"},
        )
        return bytes([fc | 0x80, 0x01])

    def _process_modbus_frame(self, unit_id: int, fc: int, data: bytes) -> bytes:  # noqa: C901
        slave_id = unit_id if unit_id else 1
        store = self._data_stores.get(slave_id)
        if not store:  # FIXED-P1: 未注册的slave_id返回异常码02，而非自动创建存储
            return bytes([fc | 0x80, 0x02])
        # FIXED-P0: 校验 data 最小长度，避免畸形报文导致 struct.unpack 崩溃
        if len(data) < 4 and fc in (0x01, 0x02, 0x03, 0x04, 0x05, 0x06):
            return bytes([fc | 0x80, 0x02])  # Illegal Data Address
        try:
            if fc == 0x01:
                start = struct.unpack(">H", data[0:2])[0]  # FIXED-P0: 移除+1偏移
                count = struct.unpack(">H", data[2:4])[0]
                if count == 0 or count > self._MAX_READ_COILS:  # FIXED(v1.5.0): count=0 按规范返回异常码03（与TCP server一致）
                    return bytes([fc | 0x80, 0x03])
                byte_count = (count + 7) // 8
                bits = bytearray(byte_count)
                for i in range(count):
                    if store.get_coil(start + i):
                        bits[i // 8] |= (1 << (i % 8))
                return bytes([fc, byte_count]) + bytes(bits)
            elif fc == 0x02:
                start = struct.unpack(">H", data[0:2])[0]  # FIXED-P0: 移除+1偏移
                count = struct.unpack(">H", data[2:4])[0]
                if count == 0 or count > self._MAX_READ_COILS:  # FIXED(v1.5.0): count=0 按规范返回异常码03
                    return bytes([fc | 0x80, 0x03])
                byte_count = (count + 7) // 8
                bits = bytearray(byte_count)
                for i in range(count):
                    if store.get_discrete_input(start + i):
                        bits[i // 8] |= (1 << (i % 8))
                return bytes([fc, byte_count]) + bytes(bits)
            elif fc == 0x03:
                start = struct.unpack(">H", data[0:2])[0]  # FIXED-P0: 移除+1偏移
                count = struct.unpack(">H", data[2:4])[0]
                if count == 0 or count > self._MAX_READ_REGISTERS:  # FIXED(v1.5.0): count=0 按规范返回异常码03（黄金用例回归）
                    return bytes([fc | 0x80, 0x03])
                byte_count = count * 2
                regs = bytearray(byte_count)
                for i in range(count):
                    val = store.get_point(3, start + i)
                    regs[i * 2:i * 2 + 2] = struct.pack(">H", val & 0xFFFF)
                return bytes([fc, byte_count]) + bytes(regs)
            elif fc == 0x04:
                start = struct.unpack(">H", data[0:2])[0]  # FIXED-P0: 移除+1偏移
                count = struct.unpack(">H", data[2:4])[0]
                if count == 0 or count > self._MAX_READ_REGISTERS:  # FIXED(v1.5.0): count=0 按规范返回异常码03
                    return bytes([fc | 0x80, 0x03])
                byte_count = count * 2
                regs = bytearray(byte_count)
                for i in range(count):
                    val = store.get_point(4, start + i)
                    regs[i * 2:i * 2 + 2] = struct.pack(">H", val & 0xFFFF)
                return bytes([fc, byte_count]) + bytes(regs)
            elif fc == 0x05:
                start = struct.unpack(">H", data[0:2])[0]  # FIXED-P0: 移除+1偏移
                val = struct.unpack(">H", data[2:4])[0]
                if val not in (0xFF00, 0x0000):  # FIXED-M02: FC05写入值必须为0xFF00(ON)或0x0000(OFF)，与TCP server保持一致
                    return bytes([fc | 0x80, 0x03])
                # access 只读校验（FIXED：只读点位外部可写的语义缺口）
                readonly_hit = self._check_external_write_access(slave_id, fc, start, 1)
                if readonly_hit:
                    return self._reject_readonly_write(fc, slave_id, "Write Single Coil", start, readonly_hit)
                store.set_coil(start, 1 if val == 0xFF00 else 0)
                self._notify_external_write(slave_id, fc, start, 1 if val == 0xFF00 else 0)
                return bytes([fc]) + data[0:4]
            elif fc == 0x06:
                start = struct.unpack(">H", data[0:2])[0]  # FIXED-P0: 移除+1偏移
                val = struct.unpack(">H", data[2:4])[0]
                # access 只读校验（FIXED：只读点位外部可写的语义缺口）
                readonly_hit = self._check_external_write_access(slave_id, fc, start, 1)
                if readonly_hit:
                    return self._reject_readonly_write(fc, slave_id, "Write Single Register", start, readonly_hit)
                store.set_point(6, start, val)
                self._notify_external_write(slave_id, fc, start, val)
                return bytes([fc]) + data[0:4]
            elif fc == 0x0F:
                # FIXED-P0: 校验最小长度
                if len(data) < 5:
                    return bytes([fc | 0x80, 0x02])
                start = struct.unpack(">H", data[0:2])[0]  # FIXED-P0: 移除+1偏移
                count = struct.unpack(">H", data[2:4])[0]
                byte_count = data[4]  # FIXED-M03: 读取byte_count字段
                expected_byte_count = (count + 7) // 8
                if byte_count != expected_byte_count:  # FIXED-M03: 校验byte_count与count的一致性
                    return bytes([fc | 0x80, 0x03])
                # access 只读校验（FIXED：只读点位外部可写的语义缺口）
                readonly_hit = self._check_external_write_access(slave_id, fc, start, count)
                if readonly_hit:
                    return self._reject_readonly_write(fc, slave_id, "Write Multiple Coils", start, readonly_hit)
                for i in range(count):
                    byte_idx = 5 + i // 8
                    bit_idx = i % 8
                    if byte_idx < len(data):
                        store.set_coil(start + i, 1 if data[byte_idx] & (1 << bit_idx) else 0)
                self._notify_external_write(slave_id, fc, start, None)
                return bytes([fc]) + data[0:4]
            elif fc == 0x10:
                # FIXED-P0: 校验最小长度
                if len(data) < 5:
                    return bytes([fc | 0x80, 0x02])
                start = struct.unpack(">H", data[0:2])[0]  # FIXED-P0: 移除+1偏移
                count = struct.unpack(">H", data[2:4])[0]
                byte_count = data[4]  # FIXED-M03: 读取byte_count字段
                if byte_count != count * 2:  # FIXED-M03: 校验byte_count与count的一致性
                    return bytes([fc | 0x80, 0x03])
                # access 只读校验（FIXED：只读点位外部可写的语义缺口）
                readonly_hit = self._check_external_write_access(slave_id, fc, start, count)
                if readonly_hit:
                    return self._reject_readonly_write(fc, slave_id, "Write Multiple Registers", start, readonly_hit)
                for i in range(count):
                    offset = 5 + i * 2
                    if offset + 2 <= len(data):
                        val = struct.unpack(">H", data[offset:offset + 2])[0]
                        store.set_point(16, start + i, val)
                self._notify_external_write(slave_id, fc, start, None)
                return bytes([fc]) + data[0:4]
            elif fc == 0x16:
                if len(data) < 6:  # FIXED-P1: FC0x16需addr(2)+and_mask(2)+or_mask(2)=6字节，原值10错误
                    return bytes([fc | 0x80, 0x02])
                ref_addr = struct.unpack(">H", data[0:2])[0]  # FIXED-P0: 移除+1偏移
                and_mask = struct.unpack(">H", data[2:4])[0]
                or_mask = struct.unpack(">H", data[4:6])[0]
                # access 只读校验（FIXED：只读点位外部可写的语义缺口）
                readonly_hit = self._check_external_write_access(slave_id, fc, ref_addr, 1)
                if readonly_hit:
                    return self._reject_readonly_write(fc, slave_id, "Mask Write Register", ref_addr, readonly_hit)
                current = store.get_point(3, ref_addr)
                new_val = (current & and_mask) | (or_mask & ~and_mask)
                new_val = new_val & 0xFFFF
                store.set_point(16, ref_addr, new_val)
                self._notify_external_write(slave_id, fc, ref_addr, new_val)
                return bytes([fc]) + data[0:6]
            elif fc == 0x17:
                if len(data) < 9:  # FIXED-P1: FC0x17需r_start(2)+r_count(2)+w_start(2)+w_count(2)+w_byte_count(1)=9字节，原值10错误
                    return bytes([fc | 0x80, 0x02])
                read_start = struct.unpack(">H", data[0:2])[0]  # FIXED-P0: 移除+1偏移
                read_count = struct.unpack(">H", data[2:4])[0]
                write_start = struct.unpack(">H", data[4:6])[0]  # FIXED-P0: 移除+1偏移
                write_count = struct.unpack(">H", data[6:8])[0]
                # access 只读校验：FC17 写入部分同样不允许命中只读点位（FIXED：语义缺口）
                readonly_hit = self._check_external_write_access(slave_id, fc, write_start, write_count)
                if readonly_hit:
                    return self._reject_readonly_write(fc, slave_id, "Read/Write Multiple Registers", write_start, readonly_hit)
                data[8] if len(data) > 8 else 0
                for i in range(write_count):
                    offset = 9 + i * 2
                    if offset + 2 <= len(data):
                        val = struct.unpack(">H", data[offset:offset + 2])[0]
                        store.set_point(16, write_start + i, val)
                self._notify_external_write(slave_id, 0x10, write_start, None)
                byte_count = read_count * 2
                regs = bytearray(byte_count)
                for i in range(read_count):
                    val = store.get_point(3, read_start + i)
                    regs[i * 2:i * 2 + 2] = struct.pack(">H", val & 0xFFFF)
                return bytes([fc, byte_count]) + bytes(regs)
            else:
                return bytes([fc | 0x80, 0x01])
        except (IndexError, struct.error):
            return bytes([fc | 0x80, 0x02])

    async def stop(self) -> None:
        try:
            if self._server_task:
                self._server_task.cancel()
                try:
                    await self._server_task
                except asyncio.CancelledError:
                    logger.debug("Modbus RTU task cancelled")
                except Exception as e:
                    logger.warning("Modbus RTU server task error: %s", e)
        except Exception as e:
            logger.warning("Modbus RTU server stop error: %s", e)
        finally:
            # FIXED(Issue#36): 串口模式下释放 COM 口（读线程 timeout=0.05 保证及时退出）
            ser = self._serial
            self._serial = None
            if ser is not None:
                try:
                    ser.close()
                except Exception as e:
                    logger.debug("Modbus RTU serial close error: %s", e)
            self._status = ProtocolStatus.STOPPED
            logger.info("Modbus RTU server stopped")
            self._log_debug("system", "server_stop", "Modbus RTU service stopped")

    async def create_device(self, device_config: DeviceConfig) -> str:
        behavior = ModbusDeviceBehavior(device_config.points)
        async with self._behaviors_lock:
            self._behaviors[device_config.id] = behavior
            self._device_configs[device_config.id] = device_config
        await self._update_default_device_async(device_config.id)

        proto_config = device_config.protocol_config or {}
        slave_id = proto_config.get("slave_id", self._next_slave_id)
        if not isinstance(slave_id, int) or slave_id < 1 or slave_id > 247:
            raise ValueError(
                f"Modbus slave_id must be between 1 and 247 (got {slave_id}). "
                "0 is broadcast, 248-255 are reserved per Modbus specification."
            )
        async with self._behaviors_lock:
            self._slave_map[device_config.id] = slave_id
            self._next_slave_id = max(self._next_slave_id, slave_id + 1)

        if self._status == ProtocolStatus.RUNNING:
            self._get_data_store(slave_id)
            # FIXED(Issue#8): 不再创建 ModbusDeviceContext/ModbusSequentialDataBlock，
            # pymodbus 3.13+ 中这些类已废弃且 API 不兼容。原生帧处理器直接读写 _data_stores。
            self._apply_device_to_context(device_config)

        logger.info("Modbus RTU device created: %s (slave_id=%d)", device_config.id, slave_id)
        self._log_debug("system", "device_created",
                        f"Modbus RTU device created: {device_config.name} (slave_id={slave_id})",
                        device_id=device_config.id,
                        detail={"slave_id": slave_id, "points": len(device_config.points)})
        return device_config.id

    async def remove_device(self, device_id: str) -> None:
        async with self._behaviors_lock:  # FIXED: W3 - add _behaviors_lock protection for _behaviors and _device_configs access
            self._behaviors.pop(device_id, None)
            self._device_configs.pop(device_id, None)
            slave_id = self._slave_map.pop(device_id, None)  # FIXED-P1: 移入_behaviors_lock保护，防止与帧处理并发
            if slave_id is not None:
                self._data_stores.pop(slave_id, None)
        await self._clear_default_device_async(device_id)
        logger.info("Modbus RTU device removed: %s", device_id)
        self._log_debug("system", "device_remove",
                        f"Removed Modbus RTU device: {device_id}",
                        device_id=device_id)

    async def read_points(self, device_id: str) -> list[PointValue]:
        behavior = self._behaviors.get(device_id)
        if not behavior:
            return []
        config = self._device_configs.get(device_id)
        if not config:
            return []
        slave_id = self._slave_map.get(device_id, 1)
        now = time.time()
        result = []
        for point in config.points:
            # FIXED(Issue#8): 从 store 读取（非 behavior），支持外部 Modbus 写入反映——
            # 与 TCP server 保持一致，否则外部写入的数据在 read_points 中丢失。
            value = self._read_register(point, slave_id)
            result.append(PointValue(name=point.name, value=value, timestamp=now))
        return result

    async def write_point(self, device_id: str, point_name: str, value: Any) -> bool:
        behavior = self._behaviors.get(device_id)
        if not behavior:
            return False

        # 检查点位是否存在且可写
        config = self._device_configs.get(device_id)
        if config:
            point = next((p for p in config.points if p.name == point_name), None)
            if point is None:
                return False
            if point.access not in ("w", "rw"):
                return False

        success = behavior.on_write(point_name, value)
        if success:
            self._apply_device_to_context(
                self._device_configs.get(device_id, DeviceConfig(id=device_id, name="", protocol="modbus_rtu"))
            )
            if self._on_write:
                try:
                    await self._on_write(device_id, point_name, value)
                except Exception as cb_err:
                    logger.debug("Modbus RTU on_write 回调失败 (device=%s, point=%s): %s", device_id, point_name, cb_err)
        return success

    def get_config_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "port": {"type": "string", "default": "/dev/ttyUSB0", "description": "Serial port path (Linux: /dev/ttyUSB0, Windows: COM1)"},
                "baudrate": {"type": "integer", "default": 9600, "description": "Baud rate"},
                "parity": {"type": "string", "default": "N", "description": "Parity (N/E/O)"},
                "stopbits": {"type": "integer", "default": 1, "description": "Stop bits"},
                "bytesize": {"type": "integer", "default": 8, "description": "Data bits"},
            },
        }

    def _write_point_to_store(self, point: PointConfig, value: Any, store: ModbusDataStore) -> None:
        """将单个点位的值写入 Modbus 数据存储（提取自 _apply_device_to_context）。"""
        try:
            addr, area = parse_modbus_address(point.address)
            if area == "coil":
                store.coils[addr] = int(bool(value))
            elif area == "discrete":
                store.discrete_inputs[addr] = int(bool(value))
            elif area == "input":
                store.input_regs[addr] = int(value) & 0xFFFF
            elif point.data_type.value in ("bool",):
                store.coils[addr] = int(bool(value))
            elif point.data_type.value in ("float32",):
                data = struct.pack(">f", float(value))
                store.holding_regs[addr] = struct.unpack(">H", data[0:2])[0]
                store.holding_regs[addr + 1] = struct.unpack(">H", data[2:4])[0]
            elif point.data_type.value in ("float64",):
                data = struct.pack(">d", float(value))
                for j in range(4):
                    store.holding_regs[addr + j] = struct.unpack(">H", data[j * 2:j * 2 + 2])[0]
            elif point.data_type.value in ("int32",):
                data = struct.pack(">i", int(value))
                store.holding_regs[addr] = struct.unpack(">H", data[0:2])[0]
                store.holding_regs[addr + 1] = struct.unpack(">H", data[2:4])[0]
            elif point.data_type.value in ("uint32",):
                data = struct.pack(">I", int(value))
                store.holding_regs[addr] = struct.unpack(">H", data[0:2])[0]
                store.holding_regs[addr + 1] = struct.unpack(">H", data[2:4])[0]
            elif point.data_type.value in ("string",):
                encoded = str(value).encode("utf-8")
                for j in range(0, min(len(encoded), 62), 2):
                    store.holding_regs[addr + j // 2] = struct.unpack(">H", encoded[j:j+2].ljust(2, b'\x00'))[0]
            else:
                store.holding_regs[addr] = int(value) & 0xFFFF
        except (ValueError, TypeError) as e:
            logger.warning("Failed to write register %s: %s", point.address, e)

    def _apply_device_to_context(self, config: DeviceConfig) -> None:
        behavior = self._behaviors.get(config.id)
        slave_id = self._slave_map.get(config.id, 1)
        store = self._get_data_store(slave_id)
        for point in config.points:
            value = behavior.get_value(point.name) if behavior else 0
            self._write_point_to_store(point, value, store)

    async def sync_point_value(self, device_id: str, point_name: str, value: Any) -> None:
        """内部同步：直接更新 Modbus 数据存储，绕过访问控制检查。"""
        config = self._device_configs.get(device_id)
        if not config:
            return
        point = next((p for p in config.points if p.name == point_name), None)
        if not point:
            return
        slave_id = self._slave_map.get(device_id, 1)
        store = self._get_data_store(slave_id)
        self._write_point_to_store(point, value, store)

    def _read_register(self, point: PointConfig, slave_id: int = 1) -> Any | None:
        store = self._get_data_store(slave_id)
        try:
            address, area = parse_modbus_address(point.address)
            dt = point.data_type.value

            # FIXED: 根据 area 选择正确的寄存器存储区，与 _write_point_to_store 保持一致。
            if area == "coil":
                regs_store = store.coils
                is_bit_area = True
            elif area == "discrete":
                regs_store = store.discrete_inputs
                is_bit_area = True
            elif area == "input":
                regs_store = store.input_regs
                is_bit_area = False
            else:  # holding or auto
                regs_store = store.coils if dt in ("bool",) else store.holding_regs
                is_bit_area = dt in ("bool",)

            if is_bit_area or dt in ("bool",):
                return bool(regs_store.get(address, 0))
            elif dt in ("float32",):
                regs = [regs_store.get(address + i, 0) for i in range(2)]
                return struct.unpack(">f", struct.pack(">HH", *regs))[0]
            elif dt in ("float64",):
                regs = [regs_store.get(address + i, 0) for i in range(4)]
                return struct.unpack(">d", struct.pack(">HHHH", *regs))[0]
            elif dt in ("int32",):
                regs = [regs_store.get(address + i, 0) for i in range(2)]
                return struct.unpack(">i", struct.pack(">HH", *regs))[0]
            elif dt in ("uint32",):
                regs = [regs_store.get(address + i, 0) for i in range(2)]
                return struct.unpack(">I", struct.pack(">HH", *regs))[0]
            elif dt in ("int16",):
                raw = regs_store.get(address, 0)
                return struct.unpack(">h", struct.pack(">H", raw & 0xFFFF))[0]
            elif dt in ("string",):
                result = bytearray()
                for i in range(32):
                    w = regs_store.get(address + i, 0)
                    result += struct.pack(">H", w)
                    if w & 0xFF == 0:
                        break
                return result.rstrip(b'\x00').decode("utf-8", errors="replace")
            else:
                return regs_store.get(address, 0)
        except (ValueError, TypeError, struct.error) as e:
            logger.warning("Failed to read register %s: %s", point.address, e)
            return None
