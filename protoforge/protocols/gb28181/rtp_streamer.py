import asyncio
import contextlib
import logging
import struct

logger = logging.getLogger(__name__)


class BitWriter:
    def __init__(self):
        self._bits = []

    def write_bits(self, value: int, num_bits: int) -> None:
        for i in range(num_bits - 1, -1, -1):
            self._bits.append((value >> i) & 1)

    def write_ue(self, value: int) -> None:
        code = value + 1
        num_bits = code.bit_length()
        for _ in range(num_bits - 1):
            self._bits.append(0)
        self.write_bits(code, num_bits)

    def write_se(self, value: int) -> None:
        if value > 0:
            self.write_ue(2 * value - 1)
        elif value < 0:
            self.write_ue(-2 * value)
        else:
            self.write_ue(0)

    def byte_align(self) -> None:
        remainder = len(self._bits) % 8
        if remainder != 0:
            for _ in range(8 - remainder):
                self._bits.append(0)

    def write_rbsp_trailing(self) -> None:
        self._bits.append(1)
        self.byte_align()

    def to_bytes(self) -> bytes:
        self.byte_align()
        result = bytearray()
        for i in range(0, len(self._bits), 8):
            byte_val = 0
            for j in range(8):
                byte_val = byte_val << 1 | self._bits[i + j] if i + j < len(self._bits) else byte_val << 1
            result.append(byte_val)
        return bytes(result)


def _generate_sps(width: int = 352, height: int = 288) -> bytes:
    w_mbs = width // 16
    h_mbs = height // 16
    bw = BitWriter()
    bw.write_bits(66, 8)
    bw.write_bits(0xC0, 8)
    bw.write_bits(30, 8)
    bw.write_ue(0)
    bw.write_ue(0)
    bw.write_ue(0)
    bw.write_ue(0)
    bw.write_ue(0)
    bw.write_bits(0, 1)
    bw.write_ue(w_mbs - 1)
    bw.write_ue(h_mbs - 1)
    bw.write_bits(1, 1)
    bw.write_bits(1, 1)
    bw.write_bits(0, 1)
    bw.write_bits(0, 1)
    bw.write_rbsp_trailing()
    return b'\x00\x00\x00\x01\x67' + bw.to_bytes()


def _generate_pps() -> bytes:
    bw = BitWriter()
    bw.write_ue(0)
    bw.write_ue(0)
    bw.write_bits(0, 1)
    bw.write_bits(0, 1)
    bw.write_ue(0)
    bw.write_ue(0)
    bw.write_ue(0)
    bw.write_bits(0, 1)
    bw.write_bits(0, 2)
    bw.write_se(0)
    bw.write_se(0)
    bw.write_se(0)
    bw.write_bits(0, 1)
    bw.write_bits(0, 1)
    bw.write_bits(0, 1)
    bw.write_rbsp_trailing()
    return b'\x00\x00\x00\x01\x68' + bw.to_bytes()


def _generate_idr_slice(width: int = 352, height: int = 288) -> bytes:
    w_mbs = width // 16
    h_mbs = height // 16
    total_mbs = w_mbs * h_mbs
    bw = BitWriter()
    bw.write_ue(0)
    bw.write_ue(7)
    bw.write_ue(0)
    bw.write_bits(0, 4)
    bw.write_ue(0)
    bw.write_bits(0, 4)
    bw.write_bits(0, 1)
    bw.write_bits(0, 1)
    bw.write_se(0)
    for _ in range(total_mbs):
        bw.write_ue(1)
    bw.write_rbsp_trailing()
    return b'\x00\x00\x00\x01\x65' + bw.to_bytes()


def _add_emulation_prevention(data: bytes) -> bytes:
    result = bytearray()
    i = 0
    while i < len(data):
        if i + 2 < len(data) and data[i] == 0 and data[i + 1] == 0 and data[i + 2] in (0, 1, 2, 3):
            result.append(data[i])
            result.append(data[i + 1])
            result.append(0x03)
            result.append(data[i + 2])
            i += 3
        else:
            result.append(data[i])
            i += 1
    return bytes(result)


def generate_h264_iframe(width: int = 352, height: int = 288) -> bytes:
    sps = b'\x00\x00\x00\x01\x67' + _add_emulation_prevention(_generate_sps(width, height)[5:])
    pps = b'\x00\x00\x00\x01\x68' + _add_emulation_prevention(_generate_pps()[5:])
    idr = b'\x00\x00\x00\x01\x65' + _add_emulation_prevention(_generate_idr_slice(width, height)[5:])
    return sps + pps + idr


def _build_ps_header(scr: float = 0.0) -> bytes:
    pack_start_code = b'\x00\x00\x01\xBA'
    scr_base = int(scr * 90000) % (2**33)
    scr_ext = int((scr * 90000 - int(scr * 90000)) * 300) % 300
    scr_val = (scr_base << 15) | (scr_ext << 0)
    b6 = (scr_val >> 37) & 0x07
    b5 = (scr_val >> 30) & 0x7F
    b4 = (scr_val >> 23) & 0x7F
    b3 = (scr_val >> 15) & 0x7F
    b2 = (scr_val >> 8) & 0x7F
    b1 = (scr_val >> 1) & 0x7F
    b0 = (scr_val & 0x01) << 7
    header = struct.pack(
        '>BBBBBBBB',
        (b6 << 3) | 0x04 | ((b5 >> 4) & 0x03),
        ((b5 & 0x0F) << 4) | 0x04 | ((b4 >> 5) & 0x03),
        ((b4 & 0x1F) << 3) | 0x04 | ((b3 >> 5) & 0x03),
        ((b3 & 0x1F) << 3) | 0x04 | ((b2 >> 5) & 0x03),
        ((b2 & 0x1F) << 3) | 0x04 | ((b1 >> 5) & 0x03),
        ((b1 & 0x1F) << 3) | 0x04 | ((b0 >> 5) & 0x07),
    )
    mux_rate = 5000
    pack_stuffing_length = 3
    tail = struct.pack('>HB',
                       (mux_rate & 0x3FFF) << 6 | ((pack_stuffing_length & 0x07) << 3),
                       0xF8)
    return pack_start_code + header + tail + b'\xFF' * pack_stuffing_length


def _build_ps_system_header() -> bytes:
    sys_start_code = b'\x00\x00\x01\xBB'
    stream_info = b'\xFF\xFF\xFF\xFF'
    video_stream = b'\xE0\xFF\xFF\xE0'
    audio_stream = b'\xC0\xFF\xFF\xC0'
    body = stream_info + video_stream + audio_stream
    length = len(body)
    return sys_start_code + struct.pack('>H', length) + body


def _build_pes_packet(stream_id: int, pts: float, payload: bytes) -> bytes:
    pes_start_code = b'\x00\x00\x01'
    pts_val = int(pts * 90000) % (2 ** 33)
    pts_32 = pts_val & 0xFFFFFFFF
    pts_bit32 = (pts_val >> 32) & 0x01
    pts_bytes = struct.pack('>I', pts_32)
    p1 = 0x21 | (pts_bit32 << 1) | ((pts_bytes[0] >> 6) & 0x02)
    p2 = ((pts_bytes[0] & 0x3F) << 2) | 0x01 | ((pts_bytes[1] >> 6) & 0x02)
    p3 = ((pts_bytes[1] & 0x3F) << 2) | 0x01 | ((pts_bytes[2] >> 6) & 0x02)
    p4 = ((pts_bytes[2] & 0x3F) << 2) | 0x01 | ((pts_bytes[3] >> 6) & 0x02)
    p5 = ((pts_bytes[3] & 0x3F) << 2) | 0x01
    pts_data = bytes([p1, p2, p3, p4, p5])
    pes_header = bytes([0x80, 0x80, 0x05]) + pts_data
    pes_packet_length = len(pes_header) + len(payload)
    return (pes_start_code + struct.pack('>B', stream_id) +
            struct.pack('>H', pes_packet_length) + pes_header + payload)


def build_ps_frame(h264_data: bytes, pts: float = 0.0, include_system_header: bool = False) -> bytes:
    ps_header = _build_ps_header(pts)
    system_header = _build_ps_system_header() if include_system_header else b''
    pes_packet = _build_pes_packet(0xE0, pts, h264_data)
    return ps_header + system_header + pes_packet


def build_rtp_packet(payload: bytes, seq: int, timestamp: int, ssrc: int,
                     marker: bool = True, payload_type: int = 96) -> bytes:
    version = 2
    padding = 0
    extension = 0
    csrc_count = 0
    byte0 = (version << 6) | (padding << 5) | (extension << 4) | csrc_count
    byte1 = (int(marker) << 7) | payload_type
    header = struct.pack('>BBHII', byte0, byte1, seq & 0xFFFF,
                         timestamp & 0xFFFFFFFF, ssrc & 0xFFFFFFFF)
    return header + payload


class RtpStreamer:
    def __init__(self, dest_ip: str, dest_port: int, ssrc: int,
                 width: int = 352, height: int = 288, fps: int = 25):
        self._dest_ip = dest_ip
        self._dest_port = dest_port
        self._ssrc = ssrc
        self._width = width
        self._height = height
        self._fps = fps
        self._seq = 0
        self._rtp_timestamp = 0
        self._transport = None
        self._running = False
        self._task = None
        self._h264_iframe = generate_h264_iframe(width, height)
        self._frame_count = 0
        self._on_debug_log = None

    def set_debug_callback(self, callback):
        self._on_debug_log = callback

    def _log(self, direction: str, msg_type: str, summary: str, detail: dict = None):
        if self._on_debug_log:
            self._on_debug_log(direction, msg_type, summary, detail)

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def dest_addr(self) -> str:
        return f"{self._dest_ip}:{self._dest_port}"

    @property
    def frame_count(self) -> int:
        return self._frame_count

    async def start(self) -> None:
        if self._running:
            return
        loop = asyncio.get_running_loop()
        try:
            self._transport, _ = await loop.create_datagram_endpoint(
                asyncio.DatagramProtocol,
                local_addr=('0.0.0.0', 0),
            )
        except Exception as e:
            self._log("out", "rtp_error", f"RTP传输创建失败: {e}")
            raise
        self._running = True
        self._task = asyncio.create_task(self._stream_loop())
        self._log("out", "rtp_start",
                  f"RTP视频流开始推送 → {self._dest_ip}:{self._dest_port}",
                  {"ssrc": self._ssrc, "fps": self._fps,
                   "resolution": f"{self._width}x{self._height}"})

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        if self._transport:
            self._transport.close()
            self._transport = None
        self._log("out", "rtp_stop",
                  f"RTP视频流停止 (共推送{self._frame_count}帧)",
                  {"total_frames": self._frame_count})

    async def _stream_loop(self) -> None:
        frame_interval = 1.0 / self._fps
        timestamp_increment = 90000 // self._fps
        include_sys_header = True
        try:
            while self._running:
                pts = self._frame_count / self._fps
                ps_frame = build_ps_frame(
                    self._h264_iframe,
                    pts=pts,
                    include_system_header=include_sys_header,
                )
                include_sys_header = False
                mtu = 1400
                if len(ps_frame) <= mtu:
                    packet = build_rtp_packet(
                        ps_frame, self._seq, self._rtp_timestamp,
                        self._ssrc, marker=True,
                    )
                    self._seq = (self._seq + 1) & 0xFFFF
                    if self._transport:
                        try:
                            self._transport.sendto(packet, (self._dest_ip, self._dest_port))
                        except Exception as e:
                            logger.debug("RTP sendto error: %s", e)
                else:
                    offset = 0
                    while offset < len(ps_frame):
                        chunk = ps_frame[offset:offset + mtu]
                        is_last = (offset + mtu) >= len(ps_frame)
                        packet = build_rtp_packet(
                            chunk, self._seq, self._rtp_timestamp,
                            self._ssrc, marker=is_last,
                        )
                        self._seq = (self._seq + 1) & 0xFFFF
                        if self._transport:
                            try:
                                self._transport.sendto(packet, (self._dest_ip, self._dest_port))
                            except Exception as e:
                                logger.debug("RTP sendto error: %s", e)
                                break
                        offset += mtu
                        if not is_last:
                            await asyncio.sleep(0.0005)

                self._rtp_timestamp = (self._rtp_timestamp + timestamp_increment) & 0xFFFFFFFF
                self._frame_count += 1

                if self._frame_count % 25 == 0:
                    self._log("out", "rtp_stats",
                              f"RTP流状态: {self._frame_count}帧, {self._width}x{self._height}@{self._fps}fps",
                              {"frames": self._frame_count, "seq": self._seq,
                               "dest": f"{self._dest_ip}:{self._dest_port}"})

                await asyncio.sleep(frame_interval)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            self._log("out", "rtp_error", f"RTP流异常: {e}")
            logger.error("RTP stream error: %s", e)
