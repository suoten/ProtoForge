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
