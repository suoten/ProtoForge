#!/usr/bin/env python3
"""Diagnostic test script for ProtoForge FINS (Omron) server.

Tests FINS TCP operations using raw TCP sockets against a locally
started FINS server on 127.0.0.1:9600.
"""

import sys
import os
import socket
import struct
import time
import asyncio

# Windows proactor event loop has issues with combined TCP+UDP servers;
# use the selector policy for reliable operation.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# Add project root so the protoforge package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from protoforge.protocols.fins.server import FinsServer
from protoforge.models.device import DeviceConfig, PointConfig

HOST = "127.0.0.1"
PORT = 9600
SOCKET_TIMEOUT = 5  # seconds per socket operation


# ---------------------------------------------------------------------------
# Low-level FINS TCP frame helpers
# ---------------------------------------------------------------------------

def build_frame(body: bytes) -> bytes:
    """Build a complete FINS TCP frame: FINS magic + length + body."""
    return b"FINS" + struct.pack(">I", len(body)) + body


def recv_frame(sock: socket.socket) -> bytes | None:
    """Receive a complete FINS TCP frame and return the body, or None."""
    try:
        header = _recv_exact(sock, 8)
    except (socket.timeout, ConnectionError, OSError):
        return None
    if header[:4] != b"FINS":
        return None
    body_len = struct.unpack(">I", header[4:8])[0]
    if body_len == 0:
        return b""
    try:
        return _recv_exact(sock, body_len)
    except (socket.timeout, ConnectionError, OSError):
        return None


def _recv_exact(sock: socket.socket, n: int) -> bytes:
    """Receive exactly *n* bytes from the socket."""
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("Connection closed prematurely")
        buf.extend(chunk)
    return bytes(buf)


# ---------------------------------------------------------------------------
# FINS command body builders
# ---------------------------------------------------------------------------

def build_init(client_node: int = 0) -> bytes:
    """Build FINS TCP Connection Init body (command 0x0000).

    Layout: Command(2) + Reserved(2) + Error(4) + ClientNode(1) + pad(3)
    """
    return (
        struct.pack(">H", 0x0000)            # Command
        + struct.pack(">H", 0x0000)          # Reserved
        + struct.pack(">I", 0x00000000)      # Error
        + bytes([client_node, 0x00, 0x00, 0x00])
    )


def build_data_send(mrc: int, src: int, fins_data: bytes = b"",
                    sid: int = 1) -> bytes:
    """Build FINS TCP Data Send body (command 0x0002).

    Layout: Command(2) + Reserved(2) + Error(4) + DestAddr(2) + FINS_Frame
    FINS_Frame: ICF(1)+RSV(1)+GW(1)+DNA(1)+DA1(1)+DA2(1)+SNA(1)+SA1(1)+SA2(1)+SID(1)+MRC(1)+SRC(1)+Data
    """
    body = (
        struct.pack(">H", 0x0002)            # Command
        + struct.pack(">H", 0x0000)          # Reserved
        + struct.pack(">I", 0x00000000)      # Error
        + bytes([0x00, 0x01])                # DestAddr (server node 1)
    )
    fins_hdr = bytes([
        0x80,   # ICF – request with reply
        0x00,   # RSV
        0x02,   # GW
        0x00,   # DNA (destination network)
        0x01,   # DA1 (destination node = server)
        0x00,   # DA2 (destination unit)
        0x00,   # SNA (source network)
        0x00,   # SA1 (source node = client)
        0x00,   # SA2 (source unit)
        sid,    # SID (service ID)
    ])
    body += fins_hdr + bytes([mrc, src]) + fins_data
    return body


def build_mem_read(area: int, word_addr: int, count: int) -> bytes:
    """Build Memory Area Read FINS data (MRC=0x01, SRC=0x01).

    Layout: AreaCode(1) + WordAddr(2,BE) + BitAddr(1) + WordCount(2,BE)
    """
    return (
        bytes([area])
        + struct.pack(">H", word_addr)
        + bytes([0x00])
        + struct.pack(">H", count)
    )


def build_mem_write(area: int, word_addr: int, count: int,
                    data: bytes) -> bytes:
    """Build Memory Area Write FINS data (MRC=0x01, SRC=0x02).

    Layout: AreaCode(1) + WordAddr(2,BE) + BitAddr(1) + WordCount(2,BE) + Data
    """
    return (
        bytes([area])
        + struct.pack(">H", word_addr)
        + bytes([0x00])
        + struct.pack(">H", count)
        + data
    )


# ---------------------------------------------------------------------------
# Server lifecycle
# ---------------------------------------------------------------------------

async def start_server() -> FinsServer:
    """Create and start a FINS server with a test device."""
    server = FinsServer()
    config = DeviceConfig(
        id="test-fins",
        name="Test FINS Device",
        protocol="fins",
        points=[
            PointConfig(
                name="temperature",
                address="D0",
                data_type="float32",
                access="rw",
                fixed_value=25.0,
            ),
            PointConfig(
                name="pressure",
                address="D2",
                data_type="int16",
                access="rw",
                fixed_value=100,
            ),
        ],
    )
    await server.create_device(config)
    await server.start({"host": HOST, "port": PORT})
    return server


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------

def test_connection_init(sock: socket.socket) -> bool:
    """Test 1: FINS TCP Connection Init (command 0x0000)."""
    print("\n--- Test 1: FINS TCP Connection Init ---")
    try:
        sock.sendall(build_frame(build_init(client_node=0)))
        resp = recv_frame(sock)
        if resp is None:
            print("  FAIL: no response received")
            return False
        if len(resp) < 10:
            print(f"  FAIL: response too short ({len(resp)} bytes, need >= 10)")
            return False

        cmd    = struct.unpack(">H", resp[0:2])[0]
        err    = struct.unpack(">I", resp[4:8])[0]
        c_node = resp[8]
        s_node = resp[9]

        print(f"  Command      : 0x{cmd:04X}  (expect 0x0001)")
        print(f"  Error        : 0x{err:08X}  (expect 0x00000000)")
        print(f"  Client Node  : {c_node}")
        print(f"  Server Node  : {s_node}")

        if cmd != 0x0001:
            print("  FAIL: unexpected command in response")
            return False
        if err != 0:
            print("  FAIL: non-zero error code")
            return False

        print("  PASS")
        return True
    except Exception as e:
        print(f"  FAIL: {e}")
        return False


def do_memory_read(sock: socket.socket, area: int, addr: int,
                   count: int, sid: int = 1,
                   label: str = "") -> tuple[bool, bytes]:
    """Perform a Memory Area Read and return (success, raw_word_data)."""
    tag = label or f"Memory Area Read Area=0x{area:02X} Addr={addr} Count={count}"
    print(f"\n--- {tag} ---")
    try:
        fins_data = build_mem_read(area, addr, count)
        sock.sendall(build_frame(build_data_send(0x01, 0x01, fins_data, sid)))
        resp = recv_frame(sock)
        if resp is None:
            print("  FAIL: no response received")
            return False, b""
        # Response: Cmd(2)+Rsv(2)+Err(4)+FINSHeader(10)+EndCode(2)+Data
        if len(resp) < 20:
            print(f"  FAIL: response too short ({len(resp)} bytes, need >= 20)")
            return False, b""

        end_code = struct.unpack(">H", resp[18:20])[0]
        data     = resp[20:]

        print(f"  End Code : 0x{end_code:04X}  (expect 0x0000)")
        print(f"  Data len : {len(data)} bytes  (expect {count * 2})")

        if end_code != 0:
            print("  FAIL: non-zero end code")
            return False, b""
        if len(data) != count * 2:
            print("  FAIL: data length mismatch")
            return False, b""

        for i in range(count):
            w = struct.unpack(">H", data[i * 2 : i * 2 + 2])[0]
            print(f"  D{addr + i} = 0x{w:04X}")

        print("  PASS")
        return True, data
    except Exception as e:
        print(f"  FAIL: {e}")
        return False, b""


def do_memory_write(sock: socket.socket, area: int, addr: int,
                    count: int, write_data: bytes,
                    sid: int = 2) -> bool:
    """Perform a Memory Area Write and return success."""
    print(f"\n--- Memory Area Write Area=0x{area:02X} Addr={addr} Count={count} ---")
    try:
        fins_data = build_mem_write(area, addr, count, write_data)
        sock.sendall(build_frame(build_data_send(0x01, 0x02, fins_data, sid)))
        resp = recv_frame(sock)
        if resp is None:
            print("  FAIL: no response received")
            return False
        if len(resp) < 20:
            print(f"  FAIL: response too short ({len(resp)} bytes, need >= 20)")
            return False

        end_code = struct.unpack(">H", resp[18:20])[0]
        print(f"  End Code : 0x{end_code:04X}  (expect 0x0000)")

        if end_code != 0:
            print("  FAIL: non-zero end code")
            return False

        print("  PASS")
        return True
    except Exception as e:
        print(f"  FAIL: {e}")
        return False


def test_controller_read(sock: socket.socket, sid: int = 4) -> bool:
    """Test 5: Controller Read (MRC=0x05, SRC=0x01)."""
    print("\n--- Test 5: Controller Read ---")
    try:
        sock.sendall(build_frame(build_data_send(0x05, 0x01, b"", sid)))
        resp = recv_frame(sock)
        if resp is None:
            print("  FAIL: no response received")
            return False
        # Response: Cmd(2)+Rsv(2)+Err(4)+FINSHeader(10)+EndCode(2)+ControllerInfo(26)
        if len(resp) < 46:
            print(f"  FAIL: response too short ({len(resp)} bytes, need >= 46)")
            return False

        end_code = struct.unpack(">H", resp[18:20])[0]
        info     = resp[20:]

        print(f"  End Code : 0x{end_code:04X}  (expect 0x0000)")

        if end_code != 0:
            print("  FAIL: non-zero end code")
            return False

        model   = info[0]
        version = info[1]
        sys_ver = struct.unpack(">H", info[2:4])[0]
        name    = info[4:24].rstrip(b"\x00").decode("ascii", errors="replace")
        status  = struct.unpack(">H", info[24:26])[0]

        print(f"  Controller Model   : 0x{model:02X}")
        print(f"  Controller Version : 0x{version:02X}")
        print(f"  System Version     : {sys_ver >> 8}.{sys_ver & 0xFF:02d}")
        print(f"  Controller Name    : {name}")
        print(f"  Controller Status  : 0x{status:04X}")

        print("  PASS")
        return True
    except Exception as e:
        print(f"  FAIL: {e}")
        return False


# ---------------------------------------------------------------------------
# Test runner (blocking – runs in a worker thread so the event loop stays free)
# ---------------------------------------------------------------------------

def run_all_tests() -> list[tuple[str, bool]]:
    """Connect to the FINS server and run all test cases.

    This function uses blocking sockets and must be executed in a
    separate thread so the asyncio event loop can continue to drive
    the FINS server.
    """
    results: list[tuple[str, bool]] = []

    # Wait for server to be ready (retry connection)
    sock: socket.socket | None = None
    for _ in range(20):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(SOCKET_TIMEOUT)
            sock.connect((HOST, PORT))
            break
        except ConnectionRefusedError:
            sock.close()
            sock = None
            time.sleep(0.25)

    if sock is None:
        print("FATAL: server did not become ready after 5 s")
        return results

    try:
        # ---- Test 1: Connection Init ----
        results.append(
            ("Connection Init", test_connection_init(sock))
        )

        # ---- Test 2: Memory Area Read D0-D9 ----
        ok, _ = do_memory_read(
            sock, 0x82, 0, 10, sid=1,
            label="Test 2: Memory Area Read D0-D9",
        )
        results.append(("Memory Area Read D0-D9", ok))

        # ---- Test 3: Memory Area Write D0=0x1234, D1=0x5678 ----
        wdata = struct.pack(">HH", 0x1234, 0x5678)
        ok = do_memory_write(sock, 0x82, 0, 2, wdata, sid=2)
        results.append(("Memory Area Write D0,D1", ok))

        # ---- Test 4: Memory Area Read back & verify ----
        print("\n--- Test 4: Memory Area Read Back & Verify ---")
        ok, rdata = do_memory_read(
            sock, 0x82, 0, 2, sid=3,
            label="Test 4: Read Back D0-D1",
        )
        verified = False
        if ok and len(rdata) >= 4:
            d0 = struct.unpack(">H", rdata[0:2])[0]
            d1 = struct.unpack(">H", rdata[2:4])[0]
            m0 = d0 == 0x1234
            m1 = d1 == 0x5678
            print(f"  Verify D0 = 0x{d0:04X}  (expect 0x1234) : {'OK' if m0 else 'MISMATCH'}")
            print(f"  Verify D1 = 0x{d1:04X}  (expect 0x5678) : {'OK' if m1 else 'MISMATCH'}")
            verified = m0 and m1
        if verified:
            print("  PASS")
        else:
            print("  FAIL")
        results.append(("Read Back & Verify", verified))

        # ---- Test 5: Controller Read ----
        results.append(
            ("Controller Read", test_controller_read(sock))
        )

    finally:
        sock.close()

    return results


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main():
    print("=" * 60)
    print("ProtoForge FINS Server Diagnostic Test")
    print("=" * 60)

    # Start server
    print(f"\nStarting FINS server on {HOST}:{PORT} ...")
    try:
        server = await start_server()
    except Exception as e:
        print(f"FATAL: could not start server: {e}")
        return

    # Run tests in a worker thread so the event loop stays free for the server
    results = await asyncio.to_thread(run_all_tests)

    # Stop server
    await server.stop()

    # Summary
    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)
    passed = sum(1 for _, ok in results if ok)
    for name, ok in results:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    print(f"\n{passed}/{len(results)} tests passed")


if __name__ == "__main__":
    asyncio.run(main())
