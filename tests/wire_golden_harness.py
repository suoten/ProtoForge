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
    """Grab a free TCP port from the OS (small TOCTOU race is acceptable)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


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
