"""Panasonic MEWTOCOL protocol simulator (PLC slave side).

Implements the MEWTOCOL-COM ASCII command set for Panasonic FP series PLCs
(FP-X / FP0R / FP7 compatible mode), covering the register read/write scope
requested in Issue #11:

  - RDD / WDD   data area read/write (D=DT / L=LD / F=FL)
  - RCS / RCC   contact read, single point / word units (X / Y / R / T / C / L)
  - WCS / WCC   contact write, single point / word units (Y / R / L)

Frame format (ASCII, terminated by CR = 0x0D), cross-checked against the
reference implementations hiroeorz/mewtocol-go and OpenLogics/MewtocolNet:

  request  : % <STN:2dec> # <CMD> <params> <BCC:2hex> CR
  response : % <STN:2dec> $ <CMD:2> <data> <BCC:2hex> CR   (success, 2-char echo:
             RCS/RCC→$RC, WCS/WCC→$WC, verified via mewtocol-go README vector)
             % <STN:2dec> ! <err:2hex>    <BCC:2hex> CR   (failure, no echo)
  STN      : 2-digit DECIMAL station number (01..99); "EE" = global broadcast
             (broadcast requests are executed but NOT answered, like real PLCs)
  BCC      : XOR of the ASCII codes of ALL characters from the leading '%' up to
             (excluding) the BCC itself — i.e. the '%' is INCLUDED.

Command details (v1.4.4, fixes ConvergeLoop-era deviations):
  - RDDssssseeeee : single-char area code + 5-digit DECIMAL start/end address
    (INCLUSIVE range, count = end - start + 1). The old implementation invented
    two-char area codes ("RDDT") and a count field — real masters reject it.
  - Word transfer order: each 16-bit word is 4 hex digits, LOW BYTE FIRST
    (0x1234 -> "3412"), matching mewtocol-go's lower/upper swap in both
    directions.
  - RCSCnnnn / RCCCsssseeee : contact read in single-point (1-digit data "0/1")
    or word-unit (4 hex digits per 16 contacts, bit i = contact word*16+i) mode.
  - Error response: 2-digit code only, no command echo.

Transport:
  - TCP (Mewtocol/TCP style, default port 2049) — FP-X / FP7 Ethernet module
  - serial (RS232/RS485, configurable baud) — via pyserial; falls back to a
    TCP bridge port when pyserial is unavailable or the port cannot be opened,
    mirroring the Modbus RTU server behaviour.

Word encoding: 32-bit values (int32/uint32/float32) occupy two consecutive
registers with the LOW word at the lower address (Panasonic FP convention:
DT101:DT100 = high:low for a real at DT100).

Not in scope (per the requester): monitor registration (%RM/%WM) and PLC
status monitoring (%MS/%MG).
"""

import asyncio
import contextlib
import logging
import re
import struct
import threading
import time
from typing import Any

from protoforge.models.device import DeviceConfig, PointValue
from protoforge.protocols.behavior import (
    ProtocolErrorCategory,
    ProtocolServer,
    ProtocolStatus,
    StandardDeviceBehavior,
)

logger = logging.getLogger(__name__)

CR = "\r"

# MEWTOCOL-COM error responses carry a 2-digit code after '!' (no command echo).
# Codes follow the manual's error classification (21=BCC, 22=format, 40=undefined
# command, 41=unit/station, 50=processing); masters surface the code as-is.
ERR_BCC = "21"        # BCC check mismatch
ERR_FORMAT = "22"     # command format error (length / illegal characters)
ERR_UNSUPPORTED = "40"  # undefined command
ERR_NO_UNIT = "41"    # station has no registered device
ERR_ADDRESS = "43"    # unknown area / address out of range
ERR_PROCESS = "50"    # internal processing error

# Protocol-visible data areas (single-char codes): D=DT L=LD F=FL
WORD_AREA_MAP = {"D": "DT", "L": "LD", "F": "FL"}
BIT_AREAS = ("X", "Y", "R", "T", "C", "L")
WRITABLE_BIT_AREAS = ("Y", "R", "L")  # WCS/WCC 仅允许输出型接点区（与手册/参考实现一致）

# Internal memory areas (behavior layer); the protocol maps D/L/F onto DT/LD/FL.
# "WR" is kept for compatibility with existing point addresses (word relay).
WORD_AREAS = ("DT", "WR", "LD", "FL")

# Frame budget: MEWTOCOL max frame length is 118 chars incl. CR.
# "%01$RD" (6) + BCC (2) = 8 overhead -> max 27 words (108 data chars) per read.
MAX_WORD_COUNT = 27
MAX_BIT_WORD_COUNT = 27

_POINT_ADDR_RE = re.compile(r"^([A-Za-z]+)(\d+)$")


def bcc(chars: str) -> str:
    """XOR check code: XOR of ASCII codes of all input characters, output as 2 hex chars.

    NOTE: callers MUST include the leading '%' — the MEWTOCOL BCC covers the
    entire frame from '%' up to (excluding) the BCC itself.
    """
    acc = 0
    for ch in chars:
        acc ^= ord(ch)
    return f"{acc:02X}"


def word_to_hex(word: int) -> str:
    """16-bit word -> 4 hex chars, LOW BYTE FIRST (0x1234 -> "3412")."""
    w = int(word) & 0xFFFF
    return f"{w & 0xFF:02X}{(w >> 8) & 0xFF:02X}"


def hex_to_word(text: str) -> int:
    """4 hex chars (low byte first) -> 16-bit int."""
    return int(text[2:4] + text[0:2], 16)


def _span_for(data_type: Any) -> int:
    """Number of 16-bit words occupied by a data type (0 = not word-mappable)."""
    name = getattr(data_type, "value", str(data_type))
    return {
        "bool": 1, "int16": 1, "uint16": 1,
        "int32": 2, "uint32": 2, "float32": 2,
    }.get(name, 0)


def _words_to_value(words: list[int], data_type: Any) -> Any:
    name = getattr(data_type, "value", str(data_type))
    if name in ("float32", "int32", "uint32"):
        raw = (words[1] << 16) | (words[0] & 0xFFFF)  # low word at lower address
        if name == "uint32":
            return raw
        if name == "int32":
            return raw - 0x1_0000_0000 if raw & 0x8000_0000 else raw
        return struct.unpack(">f", struct.pack(">I", raw))[0]
    if name == "int16":
        w = words[0] & 0xFFFF
        return w - 0x1_0000 if w & 0x8000 else w
    return words[0] & 0xFFFF  # uint16 / bool-as-word


def _value_to_words(value: Any, data_type: Any) -> list[int]:
    name = getattr(data_type, "value", str(data_type))
    if name in ("float32", "int32", "uint32"):
        if name == "float32":
            raw = struct.unpack(">I", struct.pack(">f", float(value or 0.0)))[0]
        else:
            iv = int(value or 0) & 0xFFFF_FFFF
            raw = iv
        return [raw & 0xFFFF, (raw >> 16) & 0xFFFF]  # low word first
    w = int(value or 0) & 0xFFFF
    return [w]


class MewtocolDeviceBehavior(StandardDeviceBehavior):
    """Per-device memory model: sparse word areas + bit areas with point sync.

    Generator values are synced into the memory areas on access (mirroring the
    MC/SLMP server fix), so %RD always returns fresh generated values.
    """

    def __init__(self, points: list | None = None):
        super().__init__(points)
        self._word_areas: dict[str, dict[int, int]] = {}
        self._bit_areas: dict[str, dict[int, bool]] = {}
        # name -> (area, address); word span derived from data type
        self._word_points: dict[str, tuple[str, int, int]] = {}
        self._bit_points: dict[str, tuple[str, int]] = {}
        if points:
            for p in points:
                name = p.name if hasattr(p, "name") else p.get("name", "")
                address = str(getattr(p, "address", "") or "")
                m = _POINT_ADDR_RE.match(address.strip())
                if not m:
                    continue
                area = m.group(1).upper()
                index = int(m.group(2))
                if area in WORD_AREAS:
                    span = _span_for(getattr(p, "data_type", "uint16"))
                    if span:
                        self._word_points[name] = (area, index, span)
                        self._sync_word_point(name, self._values.get(name, 0))
                elif area in BIT_AREAS:
                    self._bit_points[name] = (area, index)
                    self._sync_bit_point(name, bool(self._values.get(name, 0)))

    # -- memory sync ---------------------------------------------------

    def _sync_word_point(self, name: str, value: Any) -> None:
        mapping = self._word_points.get(name)
        if not mapping:
            return
        area, addr, _span = mapping
        dtype = getattr(self._points.get(name), "data_type", "uint16")
        words = _value_to_words(value, dtype)
        mem = self._word_areas.setdefault(area, {})
        for i, w in enumerate(words):
            mem[addr + i] = w & 0xFFFF

    def _sync_bit_point(self, name: str, value: Any) -> None:
        mapping = self._bit_points.get(name)
        if not mapping:
            return
        area, addr = mapping
        self._bit_areas.setdefault(area, {})[addr] = bool(value)

    # -- StandardDeviceBehavior overrides ------------------------------

    def get_value(self, point_name: str) -> Any:
        """Generate/supply the value AND sync it into the memory areas.

        Without the sync, %RD reads stale/initial words for dynamic generators
        (same root cause previously fixed on the MC/SLMP server).
        """
        value = super().get_value(point_name)
        if point_name in self._word_points:
            self._sync_word_point(point_name, value)
        elif point_name in self._bit_points:
            self._sync_bit_point(point_name, value)
        return value

    def set_value(self, point_name: str, value: Any) -> None:
        super().set_value(point_name, value)
        if point_name in self._word_points:
            self._sync_word_point(point_name, value)
        elif point_name in self._bit_points:
            self._sync_bit_point(point_name, value)

    def on_write(self, point_name: str, value: Any) -> bool:
        ok = super().on_write(point_name, value)
        if ok:
            if point_name in self._word_points:
                self._sync_word_point(point_name, value)
            elif point_name in self._bit_points:
                self._sync_bit_point(point_name, value)
        return ok

    # -- area access used by the frame handler --------------------------

    def read_words(self, area: str, addr: int, count: int) -> list[int]:
        """Read ``count`` words; mapped dynamic points are refreshed first."""
        for name, (p_area, p_addr, span) in self._word_points.items():
            if p_area == area and p_addr < addr + count and p_addr + span > addr:
                self.get_value(name)
        mem = self._word_areas.get(area, {})
        return [int(mem.get(addr + i, 0)) & 0xFFFF for i in range(count)]

    def write_words(self, area: str, addr: int, words: list[int]) -> list[str]:
        """Write words into memory; return names of mapped points affected."""
        mem = self._word_areas.setdefault(area, {})
        for i, w in enumerate(words):
            mem[addr + i] = int(w) & 0xFFFF
        affected: list[str] = []
        for name, (p_area, p_addr, span) in self._word_points.items():
            if p_area != area or p_addr + span <= addr or p_addr >= addr + len(words):
                continue
            dtype = getattr(self._points.get(name), "data_type", "uint16")
            own = [int(mem.get(p_addr + i, 0)) for i in range(span)]
            value = _words_to_value(own, dtype)
            if self.on_write(name, value):
                affected.append(name)
        return affected

    def read_bits(self, area: str, addr: int, count: int) -> list[bool]:
        for name, (p_area, p_addr) in self._bit_points.items():
            if p_area == area and addr <= p_addr < addr + count:
                self.get_value(name)
        mem = self._bit_areas.get(area, {})
        return [bool(mem.get(addr + i, False)) for i in range(count)]

    def write_bits(self, area: str, addr: int, bits: list[bool]) -> list[str]:
        mem = self._bit_areas.setdefault(area, {})
        for i, b in enumerate(bits):
            mem[addr + i] = bool(b)
        affected: list[str] = []
        for name, (p_area, p_addr) in self._bit_points.items():
            if p_area == area and addr <= p_addr < addr + len(bits):
                if self.on_write(name, bool(mem[p_addr])):
                    affected.append(name)
        return affected


class MewtocolServer(ProtocolServer):
    """Panasonic MEWTOCOL-COM simulator (TCP + serial, FP-X/FP7 register R/W)."""

    protocol_name = "mewtocol"
    protocol_display_name = "Panasonic MEWTOCOL"
    protocol_description = "松下FP系列PLC通信协议（FP-X/FP7），支持DT/WR/LD/FL字区与X/Y/R/T/C/L触点区读写"
    protocol_version = "1.0.0"

    def __init__(self):
        super().__init__()
        self._behaviors: dict[str, MewtocolDeviceBehavior] = {}
        self._device_configs: dict[str, DeviceConfig] = {}
        self._station_map: dict[int, str] = {}  # station number -> device_id
        self._global_station = -1  # "EE" 全局广播路由到默认设备（执行但不回应）
        self._host = "0.0.0.0"
        self._port = 2049
        self._server_task: asyncio.Task | None = None
        self._server_running = False
        self._connections: dict[asyncio.StreamWriter, dict[str, Any]] = {}
        # serial mode
        self._serial_thread: threading.Thread | None = None
        self._serial_stop = threading.Event()
        self._serial_port_obj: Any = None
        self._serial_is_serial_mode = False
        self._tcp_bridge_port: int | None = None

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------
    async def start(self, config: dict[str, Any]) -> None:
        self._status = ProtocolStatus.STARTING
        self._loop = asyncio.get_running_loop()  # 串口线程需用 call_soon_threadsafe 回写引擎
        self._host = config.get("host", "0.0.0.0")
        raw_port = config.get("port", 2049)
        if isinstance(self._host, str) and (
            self._host.startswith("/dev/") or self._host.upper().startswith("COM")
        ):
            # serial mode (like Modbus RTU): host is the serial device path
            self._port = raw_port if isinstance(raw_port, int) else 2049
            self._start_serial(config)
            return

        self._validate_port(raw_port)
        self._port = raw_port
        self._server_running = True
        self._serial_is_serial_mode = False
        self._server_task = asyncio.create_task(self._serve())
        self._status = ProtocolStatus.RUNNING
        logger.info("MEWTOCOL server starting on %s:%d (TCP)", self._host, self._port)
        self._log_debug("system", "server_start", f"MEWTOCOL service started {self._host}:{self._port}",
                        detail={"host": self._host, "port": self._port, "transport": "tcp"})

    def _start_serial(self, config: dict[str, Any]) -> None:
        """Start in serial mode; fall back to TCP bridge when serial is unusable."""
        try:
            import serial as pyserial  # noqa: F401
            has_serial = True
        except ImportError:
            has_serial = False

        opened = None
        if has_serial:
            try:
                import serial as pyserial
                opened = pyserial.Serial(
                    port=self._host,
                    baudrate=int(config.get("baud_rate", 9600)),
                    bytesize=int(config.get("data_bits", 8)),
                    parity=config.get("parity", "none")[0].upper() if config.get("parity") else "N",
                    stopbits=float(config.get("stop_bits", 1)),
                    timeout=0.2,
                )
            except Exception as e:
                logger.warning("Failed to open serial port %s: %s", self._host, e)
                opened = None

        bridge_port = int(config.get("tcp_bridge_port", self._port + 1))
        if opened is None:
            self._validate_port(bridge_port)
            self._tcp_bridge_port = bridge_port
            self._server_running = True
            self._serial_is_serial_mode = False
            self._server_task = asyncio.create_task(self._serve())
            self._status = ProtocolStatus.RUNNING
            logger.warning("MEWTOCOL serial port %s unavailable, TCP bridge mode on port %d",
                           self._host, bridge_port)
            self._log_debug("system", "server_start",
                            f"MEWTOCOL serial port {self._host} unavailable, TCP bridge on port {bridge_port}",
                            detail={"host": self._host, "bridge_port": bridge_port, "transport": "tcp_bridge"})
            return

        self._serial_port_obj = opened
        self._serial_is_serial_mode = True
        self._serial_stop.clear()
        self._serial_thread = threading.Thread(
            target=self._serial_loop, name="mewtocol-serial", daemon=True
        )
        self._serial_thread.start()
        self._status = ProtocolStatus.RUNNING
        logger.info("MEWTOCOL server started in serial mode on %s (%d baud)",
                    self._host, opened.baudrate)
        self._log_debug("system", "server_start",
                        f"MEWTOCOL service started on serial {self._host}",
                        detail={"host": self._host, "baud_rate": opened.baudrate, "transport": "serial"})

    async def stop(self) -> None:
        self._server_running = False
        self._serial_stop.set()
        if self._serial_port_obj is not None:
            with contextlib.suppress(Exception):
                self._serial_port_obj.close()
            self._serial_port_obj = None
        if self._serial_thread is not None and self._serial_thread.is_alive():
            self._serial_thread.join(timeout=2)
            self._serial_thread = None
        try:
            if self._server_task:
                self._server_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self._server_task
            for writer in list(self._connections.keys()):
                with contextlib.suppress(Exception):
                    writer.close()
            self._connections.clear()
        except Exception as e:
            logger.warning("MEWTOCOL server stop error: %s", e)
        finally:
            self._status = ProtocolStatus.STOPPED
            logger.info("MEWTOCOL server stopped")
            self._log_debug("system", "server_stop", "MEWTOCOL service stopped")

    async def _serve(self) -> None:
        try:
            server = await asyncio.start_server(self._handle_connection, self._host, self._port)
            async with server:
                await server.serve_forever()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.exception("MEWTOCOL server error: %s", e)
            self._status = ProtocolStatus.ERROR

    # ------------------------------------------------------------------
    # TCP connection handling
    # ------------------------------------------------------------------
    async def _handle_connection(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.on_client_connect()
        peer = writer.get_extra_info("peername", default=("?", "?"))
        self._log_debug("recv", "connection", f"MEWTOCOL client connected: {peer[0]}:{peer[1]}")
        self._connections[writer] = {"peer": peer}
        buf = ""
        try:
            while self._server_running:
                try:
                    chunk = await asyncio.wait_for(reader.read(1024), timeout=300)
                except asyncio.TimeoutError:
                    break
                except (asyncio.IncompleteReadError, ConnectionError):
                    break
                if not chunk:
                    break
                buf += chunk.decode("ascii", errors="replace")
                while CR in buf:
                    frame, buf = buf.split(CR, 1)
                    response = self._process_frame(frame)
                    if response:
                        writer.write(response.encode("ascii"))
                        await writer.drain()
        except Exception as e:
            self.record_protocol_error(ProtocolErrorCategory.NETWORK, str(e))
            logger.debug("MEWTOCOL connection error: %s", e)
        finally:
            self.on_client_disconnect()
            self._connections.pop(writer, None)
            with contextlib.suppress(Exception):
                writer.close()
            self._log_debug("recv", "connection", f"MEWTOCOL client disconnected: {peer[0]}:{peer[1]}")

    # ------------------------------------------------------------------
    # serial loop (blocking thread)
    # ------------------------------------------------------------------
    def _serial_loop(self) -> None:
        port = self._serial_port_obj
        buf = ""
        while self._server_running and not self._serial_stop.is_set() and port is not None:
            try:
                data = port.read(256)
                if data:
                    buf += data.decode("ascii", errors="replace")
                    while CR in buf:
                        frame, buf = buf.split(CR, 1)
                        response = self._process_frame(frame)
                        if response:
                            port.write(response.encode("ascii"))
                else:
                    time.sleep(0.02)
            except Exception as e:
                self.record_protocol_error(ProtocolErrorCategory.NETWORK, str(e))
                logger.warning("MEWTOCOL serial loop error: %s", e)
                break

    # ------------------------------------------------------------------
    # frame processing (pure, unit-testable)
    # ------------------------------------------------------------------
    def _process_frame(self, raw: str) -> str | None:
        """Process one MEWTOCOL request frame (without CR); return response incl. CR.

        Returns None for frames that cannot even be attributed to a station
        (nothing to answer to), and for global ("EE") broadcasts — real PLCs
        execute those silently without responding.
        """
        text = raw.strip()
        if not text.startswith("%") or len(text) < 9:
            self.record_protocol_error(ProtocolErrorCategory.FRAME_PARSE, f"bad frame: {raw[:32]!r}")
            return None

        # BCC covers ALL chars from '%' up to (excluding) the BCC itself
        given_bcc = text[-2:].upper()
        core = text[:-2]
        if bcc(core) != given_bcc:
            self.record_protocol_error(ProtocolErrorCategory.FRAME_PARSE, "BCC mismatch")
            stn = core[1:3]
            return self._build_response(stn, error=ERR_BCC)

        stn, marker, cmdtext = core[1:3], core[3:4], core[4:]
        if marker != "#":
            self.record_protocol_error(ProtocolErrorCategory.FRAME_PARSE, f"bad request marker {marker!r}")
            return self._build_response(stn, error=ERR_FORMAT)

        # station number: 2-digit DECIMAL (01..99); "EE" = global broadcast
        try:
            if stn.upper() == "EE":
                station = self._global_station
            else:
                station = int(stn, 10)
        except ValueError:
            self.record_protocol_error(ProtocolErrorCategory.FRAME_PARSE, f"bad station: {stn!r}")
            return None

        device_id = self._station_map.get(station) or self._default_device_id
        behavior = self._behaviors.get(device_id or "")

        # commands are 2 chars (RD/WD) or 3 chars (RCS/RCC/WCS/WCC)
        cmd3 = cmdtext[:3].upper()
        cmd2 = cmdtext[:2].upper()
        if cmd3 in ("RCS", "RCC", "WCS", "WCC"):
            cmd, params = cmd3, cmdtext[3:]
        else:
            cmd, params = cmd2, cmdtext[2:]

        if cmd not in ("RD", "WD", "RCS", "RCC", "WCS", "WCC"):
            self._log_debug("recv", "frame", f"unsupported MEWTOCOL command {cmd!r}",
                            device_id=device_id, detail={"params": params[:40]})
            return self._build_response(stn, error=ERR_UNSUPPORTED)
        if behavior is None:
            return self._build_response(stn, error=ERR_NO_UNIT)

        broadcast = stn.upper() == "EE"
        try:
            if cmd == "RD":
                resp = self._handle_rd(behavior, params)
            elif cmd == "WD":
                resp = self._handle_wd(behavior, params)
            elif cmd == "RCS":
                resp = self._handle_rcs(behavior, params)
            elif cmd == "RCC":
                resp = self._handle_rcc(behavior, params)
            elif cmd == "WCS":
                resp = self._handle_wcs(behavior, params)
            else:  # WCC
                resp = self._handle_wcc(behavior, params)
        except Exception as e:  # noqa: BLE001 — 协议层兜底：任何处理异常都不得断连
            logger.warning("MEWTOCOL handler error for %r: %s", cmdtext[:32], e)
            resp = ERR_PROCESS
        if broadcast:
            return None  # 全局广播：执行但不回应（与真实 PLC 一致）
        if isinstance(resp, str) and resp in (ERR_FORMAT, ERR_ADDRESS, ERR_PROCESS):
            return self._build_response(stn, error=resp)
        # 响应只回显命令前两个字符：RCS/RCC→$RC、WCS/WCC→$WC（真实 PLC 行为，
        # mewtocol-go README 向量 %01#RCSX00001D → %01$RC021 证实）
        return self._build_response(stn, cmd=cmd[:2], data=resp)

    # -- per-command handlers ------------------------------------------
    # Handlers return: data string (success) / ERR_* string (protocol error)
    # / None (no response, e.g. malformed broadcast).

    def _parse_range_params(self, params: str, width: int = 5) -> tuple[str, int, int, int] | None:
        """Parse <area:1><start:N><end:N>; return (area_code, start, end, count)."""
        if len(params) < 1 + width * 2:
            return None
        area = params[0].upper()
        try:
            start = int(params[1:1 + width], 10)
            end = int(params[1 + width:1 + width * 2], 10)
        except ValueError:
            return None
        if end < start:
            return None
        return area, start, end, end - start + 1

    def _handle_rd(self, behavior: MewtocolDeviceBehavior, params: str) -> str:
        parsed = self._parse_range_params(params)
        if not parsed or parsed[0] not in WORD_AREA_MAP:
            return ERR_FORMAT
        area_code, start, _end, count = parsed
        if count > MAX_WORD_COUNT:
            return ERR_FORMAT
        words = behavior.read_words(WORD_AREA_MAP[area_code], start, count)
        data = "".join(word_to_hex(w) for w in words)
        self._log_debug("recv", "frame", f"RDD {area_code}{start}..{_end} x{count}",
                        detail={"words": words[:8]})
        return data

    def _handle_wd(self, behavior: MewtocolDeviceBehavior, params: str) -> str:
        parsed = self._parse_range_params(params)
        if not parsed or parsed[0] not in WORD_AREA_MAP:
            return ERR_FORMAT
        area_code, start, _end, count = parsed
        if count > MAX_WORD_COUNT:
            return ERR_FORMAT
        hex_data = params[11:]
        if len(hex_data) != count * 4 or any(c not in "0123456789ABCDEFabcdef" for c in hex_data):
            return ERR_FORMAT
        words = [hex_to_word(hex_data[i * 4:(i + 1) * 4]) for i in range(count)]
        affected = behavior.write_words(WORD_AREA_MAP[area_code], start, words)
        device_id = next((d for d, b in self._behaviors.items() if b is behavior), "") or ""
        self._propagate_writes(device_id, affected)
        self._log_debug("recv", "frame", f"WDD {area_code}{start} x{count}",
                        detail={"affected": affected})
        return ""  # $WD 无数据

    def _handle_rcs(self, behavior: MewtocolDeviceBehavior, params: str) -> str:
        if len(params) < 5:
            return ERR_FORMAT
        area = params[0].upper()
        if area not in BIT_AREAS:
            return ERR_FORMAT
        try:
            contact_no = int(params[1:5], 10)
        except ValueError:
            return ERR_FORMAT
        bits = behavior.read_bits(area, contact_no, 1)
        self._log_debug("recv", "frame", f"RCS {area}{contact_no} -> {int(bits[0])}")
        return "1" if bits[0] else "0"

    def _handle_rcc(self, behavior: MewtocolDeviceBehavior, params: str) -> str:
        parsed = self._parse_range_params(params, width=4)
        if not parsed or parsed[0] not in BIT_AREAS:
            return ERR_FORMAT
        area, start_word, _end_word, count = parsed
        if count > MAX_BIT_WORD_COUNT:
            return ERR_FORMAT
        data_parts = []
        for w in range(count):
            bits = behavior.read_bits(area, (start_word + w) * 16, 16)
            word_val = sum(int(bool(b)) << i for i, b in enumerate(bits))
            data_parts.append(word_to_hex(word_val))
        self._log_debug("recv", "frame", f"RCC {area} words {start_word}..{_end_word}")
        return "".join(data_parts)

    def _handle_wcs(self, behavior: MewtocolDeviceBehavior, params: str) -> str:
        if len(params) < 6:
            return ERR_FORMAT
        area = params[0].upper()
        if area not in WRITABLE_BIT_AREAS:
            return ERR_ADDRESS
        try:
            contact_no = int(params[1:5], 10)
            state = int(params[5], 10)
        except ValueError:
            return ERR_FORMAT
        if state not in (0, 1):
            return ERR_FORMAT
        affected = behavior.write_bits(area, contact_no, [bool(state)])
        device_id = next((d for d, b in self._behaviors.items() if b is behavior), "") or ""
        self._propagate_writes(device_id, affected)
        self._log_debug("recv", "frame", f"WCS {area}{contact_no}={state}",
                        detail={"affected": affected})
        return ""  # $WCS 无数据

    def _handle_wcc(self, behavior: MewtocolDeviceBehavior, params: str) -> str:
        parsed = self._parse_range_params(params, width=4)
        if not parsed or parsed[0] not in WRITABLE_BIT_AREAS:
            return ERR_ADDRESS if parsed and parsed[0] not in BIT_AREAS else ERR_FORMAT
        area, start_word, _end_word, count = parsed
        if count > MAX_BIT_WORD_COUNT:
            return ERR_FORMAT
        hex_data = params[9:]
        if len(hex_data) != count * 4 or any(c not in "0123456789ABCDEFabcdef" for c in hex_data):
            return ERR_FORMAT
        affected = []
        for i in range(count):
            word_val = hex_to_word(hex_data[i * 4:(i + 1) * 4])
            bits = [bool((word_val >> k) & 1) for k in range(16)]
            affected.extend(behavior.write_bits(area, (start_word + i) * 16, bits))
        device_id = next((d for d, b in self._behaviors.items() if b is behavior), "") or ""
        self._propagate_writes(device_id, affected)
        self._log_debug("recv", "frame", f"WCC {area} words {start_word}..{_end_word}",
                        detail={"affected": affected[:16]})
        return ""  # $WCC 无数据

    def _propagate_writes(self, device_id: str, affected: list[str]) -> None:
        """Propagate external protocol writes to the engine DeviceInstance.

        Serial 模式下本方法在工作线程被调用，需用 call_soon_threadsafe
        把协程调度回事件循环；TCP 模式直接 create_task。
        """
        if not affected or not device_id or self._on_write is None:
            return
        behavior = self._behaviors.get(device_id)
        if not behavior:
            return
        for name in affected:
            with contextlib.suppress(Exception):
                coro = self._on_write(device_id, name, behavior.get_value(name))
                loop = getattr(self, "_loop", None)
                if loop is not None and loop.is_running():
                    try:
                        running = asyncio.get_running_loop()
                    except RuntimeError:
                        running = None
                    if running is loop:
                        loop.create_task(coro)
                    else:
                        loop.call_soon_threadsafe(loop.create_task, coro)
                elif loop is not None:
                    loop.call_soon_threadsafe(loop.create_task, coro)

    # -- response builder -----------------------------------------------

    def _build_response(self, stn: str, cmd: str = "", data: str = "",
                        error: str | None = None) -> str:
        """Build a response frame (incl. BCC + CR).

        Success:  % <STN> $ <CMD> <data> <BCC> CR
        Failure:  % <STN> ! <err:2> <BCC> CR   (no command echo, per manual)
        BCC covers ALL chars from '%' up to (excluding) the BCC itself.
        """
        if error:
            payload = f"%{stn}!{error}"
        else:
            payload = f"%{stn}${cmd}{data}"
        return f"{payload}{bcc(payload)}{CR}"

    # ------------------------------------------------------------------
    # device registry
    # ------------------------------------------------------------------
    async def create_device(self, device_config: DeviceConfig) -> str:
        device_id = device_config.id
        proto_config = device_config.protocol_config or {}
        station = proto_config.get("station_number", 1)
        if not isinstance(station, int) or not 1 <= station <= 99:
            raise ValueError(f"MEWTOCOL station_number must be an integer 1-99 (got {station!r})")
        async with self._behaviors_lock:
            # FIXED-P1: 站号冲突校验必须在任何注册动作之前，避免留下半注册状态
            existing = self._station_map.get(station)
            if existing and existing != device_id:
                raise ValueError(
                    f"MEWTOCOL station number {station} is already used by device {existing}. "
                    f"Station numbers must be unique (protocol_config.station_number)."
                )
            behavior = MewtocolDeviceBehavior(device_config.points)
            self._behaviors[device_id] = behavior
            self._device_configs[device_id] = device_config
            self._station_map[station] = device_id
        await self._update_default_device_async(device_id)
        logger.info("MEWTOCOL device created: %s (station=%d, %d points)",
                    device_id, station, len(device_config.points))
        self._log_debug("system", "device_create",
                        f"MEWTOCOL device created: {device_config.name} (station={station})",
                        device_id=device_id, detail={"station_number": station,
                                                     "points": len(device_config.points)})
        return device_id

    async def remove_device(self, device_id: str) -> None:
        async with self._behaviors_lock:
            self._behaviors.pop(device_id, None)
            config = self._device_configs.pop(device_id, None)
            if config:
                station = (config.protocol_config or {}).get("station_number", 1)
                if self._station_map.get(station) == device_id:
                    self._station_map.pop(station, None)
        await self._clear_default_device_async(device_id)
        logger.info("MEWTOCOL device removed: %s", device_id)
        self._log_debug("system", "device_remove", f"MEWTOCOL device removed: {device_id}",
                        device_id=device_id)

    # ------------------------------------------------------------------
    # engine integration
    # ------------------------------------------------------------------
    async def read_points(self, device_id: str) -> list[PointValue]:
        behavior = self._behaviors.get(device_id)
        if not behavior:
            return []
        now = time.time()
        result = []
        for name in behavior._points:
            value = behavior.get_value(name)
            result.append(PointValue(name=name, value=value, timestamp=now))
        return result

    async def write_point(self, device_id: str, point_name: str, value: Any) -> bool:
        behavior = self._behaviors.get(device_id)
        if not behavior:
            return False
        return behavior.on_write(point_name, value)

    async def sync_point_value(self, device_id: str, point_name: str, value: Any) -> None:
        behavior = self._behaviors.get(device_id)
        if behavior:
            behavior.set_value(point_name, value)

    # ------------------------------------------------------------------
    # schema
    # ------------------------------------------------------------------
    def get_config_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "host": {
                    "type": "string", "default": "0.0.0.0",
                    "description": "TCP 监听地址；填 COM3 / /dev/ttyUSB0 等串口路径时以串口模式启动",
                },
                "port": {
                    "type": "number", "default": 2049,
                    "description": "TCP 监听端口（Mewtocol/TCP）",
                },
                "tcp_bridge_port": {
                    "type": "number", "default": 2050,
                    "description": "串口不可用时的 TCP bridge 端口（串口模式专属）",
                },
                "baud_rate": {"type": "number", "default": 9600, "description": "串口波特率"},
                "data_bits": {"type": "number", "default": 8, "description": "串口数据位"},
                "parity": {"type": "string", "default": "none", "enum": ["none", "even", "odd"],
                           "description": "串口校验位"},
                "stop_bits": {"type": "number", "default": 1, "description": "串口停止位"},
            },
        }

    def generate_value(self, point_config: dict[str, Any]) -> Any:
        behavior = MewtocolDeviceBehavior()
        return behavior.generate_value(point_config)

    def on_write(self, point_name: str, value: Any) -> bool:
        return False
