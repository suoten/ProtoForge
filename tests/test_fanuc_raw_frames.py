"""FIXED: FANUC 原始报文日志（raw_frames）回归测试。

背景（用户学习研究 FOCAS 底层 16 进制报文）：协议调试日志此前只有应用层
抽象事件（server_start / device_create 等），看不到通信过程中的原始字节流。

修复后：高级配置 raw_frames=true 时，收发双向在协议调试日志输出
frame_rx / frame_tx 事件，detail.hex 为空格分隔的大写 16 进制
（超过 256 字节截断并标注总长）；默认关闭，不产生报文事件。
"""

import asyncio
import socket
import struct

import pytest

from protoforge.protocols.fanuc.server import FanucServer

TEST_PORT = 18193


def _make_frame(func_id: int = 0x0016, req_id: int = 1) -> bytes:
    """构造 legacy FOCAS 10 字节头请求（cnc_allclibhndl3 connect）."""
    return struct.pack("<HI", func_id, req_id) + b"\x00" * 4


def _make_engine_with_fanuc(raw_frames) -> tuple:
    server = FanucServer()
    events: list[tuple] = []

    def cb(direction, msg_type, summary, device_id="", detail=None):
        events.append((direction, msg_type, summary, detail or {}))

    server.set_debug_callback(cb)
    from protoforge.engine.engine import SimulationEngine
    engine = SimulationEngine()
    engine.register_protocol(server)
    return engine, server, events


async def _start_and_exchange(server: FanucServer, raw: dict) -> list:
    await server.start({"host": "127.0.0.1", "port": TEST_PORT, **raw})
    for _ in range(25):
        await asyncio.sleep(0.2)
        if server.status.value == "running":
            break
    reader, writer = await asyncio.open_connection("127.0.0.1", TEST_PORT)
    writer.write(_make_frame())
    await writer.drain()
    resp = await asyncio.wait_for(reader.read(4096), timeout=5)
    writer.close()
    try:
        await writer.wait_closed()
    except Exception:
        pass
    return resp


class TestFanucRawFrames:
    @pytest.mark.asyncio
    async def test_raw_frames_on_logs_rx_and_tx_hex(self):
        """raw_frames=true → 收发双向都有 frame_rx/frame_tx，hex 为大写 16 进制."""
        engine, server, events = _make_engine_with_fanuc(True)
        await engine.start()
        try:
            resp = await _start_and_exchange(server, {"raw_frames": True})
            assert resp, "server should respond to a valid FOCAS connect frame"
            types = [e[1] for e in events]
            assert "frame_rx" in types, f"missing frame_rx, got {types}"
            assert "frame_tx" in types, f"missing frame_tx, got {types}"
            rx = next(e for e in events if e[1] == "frame_rx")
            expected = _make_frame().hex(" ").upper()
            assert rx[3]["hex"] == expected
            assert rx[3]["length"] == len(_make_frame())
            tx = next(e for e in events if e[1] == "frame_tx")
            assert tx[3]["hex"] == resp.hex(" ").upper()
        finally:
            try:
                await server.stop()
            except Exception:
                pass
            await engine.stop()

    @pytest.mark.asyncio
    async def test_raw_frames_default_off(self):
        """默认关闭 → 不产生 frame_rx/frame_tx 事件."""
        engine, server, events = _make_engine_with_fanuc(False)
        await engine.start()
        try:
            resp = await _start_and_exchange(server, {})
            assert resp, "server should still respond normally"
            types = [e[1] for e in events]
            assert "frame_rx" not in types
            assert "frame_tx" not in types
        finally:
            try:
                await server.stop()
            except Exception:
                pass
            await engine.stop()

    @pytest.mark.asyncio
    async def test_raw_frames_string_false_stays_off(self):
        """UI 文本框输入 "false" → 必须保持关闭（bool("false") 为 True 的坑）."""
        engine, server, events = _make_engine_with_fanuc(False)
        await engine.start()
        try:
            resp = await _start_and_exchange(server, {"raw_frames": "false"})
            assert resp
            types = [e[1] for e in events]
            assert "frame_rx" not in types
            assert "frame_tx" not in types
        finally:
            try:
                await server.stop()
            except Exception:
                pass
            await engine.stop()

    @pytest.mark.asyncio
    async def test_raw_frames_string_true_turns_on(self):
        """UI 文本框输入 "true" → 开启（与 schema 文本渲染行为兼容）."""
        engine, server, events = _make_engine_with_fanuc(False)
        await engine.start()
        try:
            resp = await _start_and_exchange(server, {"raw_frames": "true"})
            assert resp
            types = [e[1] for e in events]
            assert "frame_rx" in types
        finally:
            try:
                await server.stop()
            except Exception:
                pass
            await engine.stop()

    def test_hex_dump_truncation(self):
        """超过 256 字节的帧截断转储并标注总长，不刷屏."""
        server = FanucServer()
        big = bytes(range(256)) * 3  # 768 bytes
        dump = server._hex_dump(big)
        assert "TOTAL 768" in dump.upper()
        tokens = dump.split(" ")
        assert len(tokens[0:256]) == 256 and all(t for t in tokens[:256])  # 前 256 个十六进制字节
        small = b"\xde\xad\xbe\xef"
        assert server._hex_dump(small) == "DE AD BE EF"
