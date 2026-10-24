"""Shared helpers for wire-level golden tests (v1.5.0 quality gate).

Golden tests talk to real protocol servers over real sockets and compare
raw response bytes against golden frames derived from the protocol
standards. Dynamic fields (transaction ids, PDU references, invoke ids)
are chosen by the client, so expected frames stay fully deterministic.

Rules for adding a golden test:
  - parse/encode on the wire strictly per the standard, not per the
    implementation (the implementation is what we are gating);
  - set every point value explicitly before sending requests;
  - prefer exact-byte assertions, document any masked region.
"""

import asyncio
import socket


def free_tcp_port() -> int:
    """Grab a free TCP port from the OS.

    FIXED(v1.8.1): 取号后必须验证"无监听者"——长回归里前面的测试若泄漏了
    监听 socket，裸 bind(0) 取号可能命中被泄漏的端口，后续测试的连接会
    打到错误的服务器上（实测：iec61850 黄金用例收到 HTTP 服务器的响应，
    断言错位 + reader 状态损坏引发连锁挂起）。重试 20 次仍失败则抛错。
    """
    for _ in range(20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        probe.settimeout(0.3)
        try:
            if probe.connect_ex(("127.0.0.1", port)) != 0:
                return port  # 无人监听 → 可用
        finally:
            probe.close()
    raise RuntimeError("free_tcp_port: 20 次取号均与既有监听冲突（疑似测试泄漏监听 socket）")


def free_udp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def recv_exactly(reader: asyncio.StreamReader, n: int, timeout: float = 5.0) -> bytes:
    return await asyncio.wait_for(reader.readexactly(n), timeout=timeout)


async def open_conn(port: int, host: str = "127.0.0.1", timeout: float = 5.0
                    ) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    """带超时的 TCP 连接（FIXED v1.8.0）。

    裸 ``asyncio.open_connection`` 无超时——在全量回归等长跑场景下，若目标
    端口被防火墙/代理 TUN 吞包（SYN 无应答），连接会无限挂起并把整个测试
    会话拖死。这里统一加超时，把"挂起"降级为"快速失败"。
    """
    return await asyncio.wait_for(asyncio.open_connection(host, port), timeout=timeout)


async def expect_silence(reader: asyncio.StreamReader, timeout: float = 0.4) -> None:
    """Assert the server sends nothing within ``timeout`` (rejects bad frames silently)."""
    try:
        data = await asyncio.wait_for(reader.read(1), timeout=timeout)
    except asyncio.TimeoutError:
        return
    raise AssertionError(f"expected silence, got {data!r}")


async def expect_eof(reader: asyncio.StreamReader, timeout: float = 3.0) -> None:
    """Assert the server closes the connection (read returns b'')."""
    try:
        data = await asyncio.wait_for(reader.read(1), timeout=timeout)
    except asyncio.TimeoutError:
        raise AssertionError("expected EOF, but connection stayed open")
    assert data == b"", f"expected EOF, got {data!r}"
