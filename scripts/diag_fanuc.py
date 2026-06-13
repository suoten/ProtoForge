"""
FANUC FOCAS2 Diagnostic Test Script

Tests basic FOCAS2 operations against the ProtoForge FANUC server:
  1. CNC Connect
  2. CNC StatInfo
  3. CNC Read (absolute position)
  4. CNC Disconnect

Usage:  python scripts/diag_fanuc.py
"""

import sys
import os
import socket
import struct
import asyncio
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from protoforge.protocols.fanuc.server import FanucServer
from protoforge.models.device import DeviceConfig, PointConfig

HOST = "127.0.0.1"
PORT = 8193
TIMEOUT = 5  # seconds per socket operation


# ---------------------------------------------------------------------------
# FOCAS2 Ethernet frame helpers
# ---------------------------------------------------------------------------
# Frame layout (FOCAS2 Ethernet):
#   [4B]  magic       b"FANC"
#   [2B]  session_id  big-endian uint16
#   [2B]  msg_len     big-endian uint16  (length of payload that follows)
#   [N]   payload
#
# Payload layout:
#   [2B]  func_id     little-endian uint16
#   [4B]  req_id      little-endian uint32
#   [...] function-specific data

FUNC_CONNECT = 0x0001
FUNC_DISCONNECT = 0x0002
FUNC_STATINFO = 0x0101
FUNC_ABSOLUTE = 0x0102


def build_focas2_frame(session_id: int, func_id: int, req_id: int, extra: bytes = b"") -> bytes:
    """Build a FOCAS2 Ethernet frame."""
    payload = struct.pack("<H", func_id) + struct.pack("<I", req_id) + extra
    frame = b"FANC"
    frame += struct.pack(">H", session_id)
    frame += struct.pack(">H", len(payload))
    frame += payload
    return frame


def parse_focas2_frame(data: bytes):
    """Parse a FOCAS2 Ethernet response frame.

    The server's _process_focas2_ethernet builds the response payload as:
        func_id (2B LE) + req_id (4B LE) + handler_result

    And each handler also prepends func_id + req_id to its own result,
    so the full payload is:
        func_id (2B LE) + req_id (4B LE) + func_id (2B LE) + req_id (4B LE) + data

    Returns (session_id, func_id, req_id, data_bytes).
    """
    if len(data) < 8:
        raise ValueError(f"Response too short: {len(data)} bytes")
    magic = data[:4]
    if magic != b"FANC":
        raise ValueError(f"Bad magic: {magic!r}")
    session_id = struct.unpack(">H", data[4:6])[0]
    msg_len = struct.unpack(">H", data[6:8])[0]
    payload = data[8 : 8 + msg_len]
    if len(payload) < 6:
        raise ValueError(f"Payload too short: {len(payload)} bytes")
    # Outer func_id + req_id (from _process_focas2_ethernet)
    func_id = struct.unpack("<H", payload[0:2])[0]
    req_id = struct.unpack("<I", payload[2:6])[0]
    # Inner func_id + req_id (from the handler itself)
    if len(payload) >= 12:
        # handler_func_id = struct.unpack("<H", payload[6:8])[0]
        # handler_req_id = struct.unpack("<I", payload[8:12])[0]
        data_bytes = payload[12:]
    else:
        data_bytes = b""
    return session_id, func_id, req_id, data_bytes


# ---------------------------------------------------------------------------
# Socket helpers
# ---------------------------------------------------------------------------

def sock_send_recv(sock: socket.socket, frame: bytes) -> bytes:
    """Send a frame and receive the response with timeout."""
    sock.sendall(frame)
    # Read header first (8 bytes), then read the declared payload length
    header = _recv_exact(sock, 8)
    if header[:4] != b"FANC":
        raise ValueError(f"Bad response magic: {header[:4]!r}")
    msg_len = struct.unpack(">H", header[6:8])[0]
    payload = _recv_exact(sock, msg_len) if msg_len > 0 else b""
    return header + payload


def _recv_exact(sock: socket.socket, n: int) -> bytes:
    """Receive exactly *n* bytes from the socket."""
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("Connection closed while reading")
        buf.extend(chunk)
    return bytes(buf)


# ---------------------------------------------------------------------------
# Server setup (runs in a background thread with its own event loop)
# ---------------------------------------------------------------------------

def _run_server_in_thread(server: FanucServer, loop: asyncio.AbstractEventLoop, ready_event: threading.Event):
    """Run the asyncio server in a dedicated thread."""
    asyncio.set_event_loop(loop)

    async def _start():
        config = DeviceConfig(
            id="test-fanuc",
            name="Test FANUC Device",
            protocol="fanuc",
            points=[
                PointConfig(name="x_pos", address="D100", data_type="float64", access="r", fixed_value=100.0),
                PointConfig(name="y_pos", address="D108", data_type="float64", access="r", fixed_value=200.0),
            ],
        )
        await server.create_device(config)
        await server.start({"host": HOST, "port": PORT})
        ready_event.set()

    loop.run_until_complete(_start())
    loop.run_forever()


def start_server():
    """Start the FANUC server in a background thread. Returns (server, loop)."""
    server = FanucServer()
    server._host = HOST
    server._port = PORT
    loop = asyncio.new_event_loop()
    ready = threading.Event()

    thread = threading.Thread(target=_run_server_in_thread, args=(server, loop, ready), daemon=True)
    thread.start()
    ready.wait(timeout=10)
    return server, loop


def stop_server(server: FanucServer, loop: asyncio.AbstractEventLoop):
    """Stop the FANUC server from the main thread."""
    future = asyncio.run_coroutine_threadsafe(server.stop(), loop)
    future.result(timeout=10)
    loop.call_soon_threadsafe(loop.stop)


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------

def test_connect(sock: socket.socket):
    """Test 1: CNC Connect (func_id=0x0001)."""
    req_id = 1
    frame = build_focas2_frame(session_id=0, func_id=FUNC_CONNECT, req_id=req_id)
    raw = sock_send_recv(sock, frame)
    session_id, func_id, resp_req_id, result = parse_focas2_frame(raw)

    assert resp_req_id == req_id, f"req_id mismatch: expected {req_id}, got {resp_req_id}"
    assert func_id == FUNC_CONNECT, f"func_id mismatch: expected 0x{FUNC_CONNECT:04X}, got 0x{func_id:04X}"

    # Connect result: rc (4B LE) + assigned_session (4B LE)
    if len(result) < 8:
        return False, f"Result too short ({len(result)} bytes), expected >= 8"

    rc = struct.unpack("<I", result[0:4])[0]
    assigned_session = struct.unpack("<I", result[4:8])[0]

    if rc != 0:
        return False, f"Return code = 0x{rc:08X} (expected 0x00000000)"
    if assigned_session == 0:
        return False, "Assigned session is 0"

    return True, f"rc=0, session={assigned_session}"


def test_statinfo(sock: socket.socket):
    """Test 2: CNC StatInfo (func_id=0x0101)."""
    req_id = 2
    frame = build_focas2_frame(session_id=1, func_id=FUNC_STATINFO, req_id=req_id)
    raw = sock_send_recv(sock, frame)
    session_id, func_id, resp_req_id, result = parse_focas2_frame(raw)

    assert resp_req_id == req_id, f"req_id mismatch"
    assert func_id == FUNC_STATINFO, f"func_id mismatch"

    # StatInfo result: rc (4B LE) + alarm (2B LE) + mode (2B LE) + execution (2B LE) + motion (2B LE)
    if len(result) < 12:
        return False, f"Result too short ({len(result)} bytes), expected >= 12"

    rc = struct.unpack("<I", result[0:4])[0]
    alarm = struct.unpack("<H", result[4:6])[0]
    mode = struct.unpack("<H", result[6:8])[0]
    execution = struct.unpack("<H", result[8:10])[0]
    motion = struct.unpack("<H", result[10:12])[0]

    if rc != 0:
        return False, f"Return code = 0x{rc:08X}"

    return True, f"rc=0, alarm={alarm}, mode={mode}, exec={execution}, motion={motion}"


def test_absolute(sock: socket.socket):
    """Test 3: CNC Read Absolute Position (func_id=0x0102)."""
    req_id = 3
    frame = build_focas2_frame(session_id=1, func_id=FUNC_ABSOLUTE, req_id=req_id)
    raw = sock_send_recv(sock, frame)
    session_id, func_id, resp_req_id, result = parse_focas2_frame(raw)

    assert resp_req_id == req_id, f"req_id mismatch"
    assert func_id == FUNC_ABSOLUTE, f"func_id mismatch"

    # Absolute result: rc (4B LE) + axis_count (2B LE) + positions (axis_count * 8B LE float64)
    if len(result) < 6:
        return False, f"Result too short ({len(result)} bytes), expected >= 6"

    rc = struct.unpack("<I", result[0:4])[0]
    axis_count = struct.unpack("<H", result[4:6])[0]

    if rc != 0:
        return False, f"Return code = 0x{rc:08X}"

    expected_pos_bytes = axis_count * 8
    if len(result) < 6 + expected_pos_bytes:
        return False, f"Position data truncated: got {len(result) - 6} bytes, expected {expected_pos_bytes}"

    positions = []
    for i in range(axis_count):
        pos = struct.unpack("<d", result[6 + i * 8 : 6 + (i + 1) * 8])[0]
        positions.append(pos)

    # Verify x_pos=100.0 and y_pos=200.0 are present in the first two axes
    detail = f"rc=0, axes={axis_count}, positions={[round(p, 2) for p in positions]}"
    if axis_count >= 2 and positions[0] == 100.0 and positions[1] == 200.0:
        return True, detail
    elif axis_count >= 2:
        return True, detail + " (x/y values differ from configured 100.0/200.0)"
    else:
        return True, detail + " (fewer than 2 axes)"


def test_disconnect(sock: socket.socket):
    """Test 4: CNC Disconnect (func_id=0x0002)."""
    req_id = 4
    frame = build_focas2_frame(session_id=1, func_id=FUNC_DISCONNECT, req_id=req_id)
    raw = sock_send_recv(sock, frame)
    session_id, func_id, resp_req_id, result = parse_focas2_frame(raw)

    assert resp_req_id == req_id, f"req_id mismatch"
    assert func_id == FUNC_DISCONNECT, f"func_id mismatch"

    # Disconnect result: rc (4B LE)
    if len(result) < 4:
        return False, f"Result too short ({len(result)} bytes), expected >= 4"

    rc = struct.unpack("<I", result[0:4])[0]

    if rc != 0:
        return False, f"Return code = 0x{rc:08X}"

    return True, "rc=0, disconnected"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=" * 60)
    print("  ProtoForge FANUC FOCAS2 Diagnostic Test")
    print("=" * 60)

    # Start server in background thread
    print("\n[Setup] Starting FANUC FOCAS2 server ...")
    try:
        server, loop = start_server()
        time.sleep(0.3)  # extra settle time
        print(f"[Setup] Server listening on {HOST}:{PORT}")
    except Exception as e:
        print(f"[FAIL] Could not start server: {e}")
        sys.exit(1)

    tests = [
        ("CNC Connect", test_connect),
        ("CNC StatInfo", test_statinfo),
        ("CNC Read (Absolute)", test_absolute),
        ("CNC Disconnect", test_disconnect),
    ]

    passed = 0
    failed = 0

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(TIMEOUT)
        sock.connect((HOST, PORT))
        print(f"[Setup] TCP connection established to {HOST}:{PORT}\n")

        for name, test_fn in tests:
            try:
                ok, detail = test_fn(sock)
                status = "PASS" if ok else "FAIL"
            except (socket.timeout, TimeoutError):
                ok, status, detail = False, "FAIL", f"Timeout after {TIMEOUT}s"
            except ConnectionError as e:
                ok, status, detail = False, "FAIL", f"Connection error: {e}"
            except Exception as e:
                ok, status, detail = False, "FAIL", f"Unexpected error: {e}"

            if ok:
                passed += 1
            else:
                failed += 1

            print(f"  [{status}] {name}: {detail}")

        sock.close()

    except (socket.timeout, TimeoutError):
        print(f"\n[FAIL] Could not connect to server within {TIMEOUT}s")
        failed = len(tests)
    except ConnectionRefusedError:
        print("\n[FAIL] Connection refused — server may not be listening")
        failed = len(tests)
    except Exception as e:
        print(f"\n[FAIL] Socket error: {e}")
        failed = len(tests)
    finally:
        print("\n[Teardown] Stopping server ...")
        try:
            stop_server(server, loop)
        except Exception as e:
            print(f"[Teardown] Warning: {e}")

    print("\n" + "=" * 60)
    print(f"  Results: {passed} passed, {failed} failed out of {len(tests)} tests")
    print("=" * 60)

    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
