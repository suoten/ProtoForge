"""
ProtoForge OPC-DA (TCP-Proto) Diagnostic Test Script

Tests the OPC-DA TCP bridge server using raw TCP sockets. Validates
Browse / Read / Write operations against the ProtoForge custom OPC-DA
frame handler (not DCOM).

Protocol frame format:
    Header: MAGIC(4) "PFDA" + BodyLen(4, uint32 LE)
    Body:   Cmd(4, uint32 LE) + payload

Commands:
    0x0001 Browse    - no payload
    0x0002 Read      - TagLen(2, uint16 LE) + TagName(utf-8)
    0x0003 Write     - TagLen(2, uint16 LE) + TagName(utf-8) + TypedValue
    0x0005 GetStatus - no payload

TypedValue encoding (variable length, depends on type code):
    bool:    TypeCode(1, uint8=0)  + Value(1, uint8)
    int16:   TypeCode(1, uint8=1)  + Value(2, int16 LE)
    uint16:  TypeCode(1, uint8=2)  + Value(2, uint16 LE)
    int32:   TypeCode(1, uint8=3)  + Value(4, int32 LE)
    uint32:  TypeCode(1, uint8=4)  + Value(4, uint32 LE)
    float32: TypeCode(1, uint8=5)  + Value(4, float32 LE)
    float64: TypeCode(1, uint8=6)  + Value(8, float64 LE)
    string:  TypeCode(1, uint8=7)  + StrLen(2, uint16 LE) + StrData(utf-8)

NOTE: Due to str(DataType) returning "DataType.FLOAT32" instead of "float32"
in the server's OpcDaDeviceBehavior, float32 tags are served as float64 on
the wire. This test accounts for that by parsing TypedValue dynamically.

Usage:
    python scripts/diag_opcda.py
"""

import sys
import os
import socket
import struct
import asyncio

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from protoforge.protocols.opcda.server import OpcDaServer
from protoforge.models.device import DeviceConfig, PointConfig

HOST = "127.0.0.1"
PORT = 51340
SOCKET_TIMEOUT = 5

# Protocol constants
OPCDA_MAGIC = b"PFDA"
CMD_BROWSE = 0x0001
CMD_READ = 0x0002
CMD_WRITE = 0x0003
CMD_GET_STATUS = 0x0005

# TypedValue type codes
TYPE_BOOL = 0
TYPE_INT16 = 1
TYPE_UINT16 = 2
TYPE_INT32 = 3
TYPE_UINT32 = 4
TYPE_FLOAT32 = 5
TYPE_FLOAT64 = 6
TYPE_STRING = 7


# ---------------------------------------------------------------------------
# Low-level TCP helpers
# ---------------------------------------------------------------------------

def _recv_exact(sock: socket.socket, n: int) -> bytes:
    """Receive exactly *n* bytes from the socket."""
    data = b""
    while len(data) < n:
        chunk = sock.recv(n - len(data))
        if not chunk:
            raise ConnectionError("Connection closed by remote end")
        data += chunk
    return data


def _send_frame(sock: socket.socket, body: bytes) -> None:
    """Send a complete PFDA frame (magic + body_len + body)."""
    header = OPCDA_MAGIC + struct.pack("<I", len(body))
    sock.sendall(header + body)


def _recv_frame(sock: socket.socket) -> bytes:
    """Receive a complete PFDA frame and return the body."""
    header = _recv_exact(sock, 8)
    magic = header[0:4]
    if magic != OPCDA_MAGIC:
        raise ValueError(f"Invalid magic: {magic!r}, expected {OPCDA_MAGIC!r}")
    body_len = struct.unpack("<I", header[4:8])[0]
    if body_len > 0:
        return _recv_exact(sock, body_len)
    return b""


# ---------------------------------------------------------------------------
# TypedValue parsing
# ---------------------------------------------------------------------------

def _parse_typed_value(data: bytes, offset: int) -> tuple[float, int, int]:
    """Parse a TypedValue starting at *offset*.

    Returns (value_as_float, type_code, bytes_consumed).
    """
    type_code = data[offset]
    if type_code == TYPE_BOOL:
        val = float(data[offset + 1])
        return val, type_code, 2
    elif type_code == TYPE_INT16:
        val = float(struct.unpack("<h", data[offset + 1:offset + 3])[0])
        return val, type_code, 3
    elif type_code == TYPE_UINT16:
        val = float(struct.unpack("<H", data[offset + 1:offset + 3])[0])
        return val, type_code, 3
    elif type_code == TYPE_INT32:
        val = float(struct.unpack("<i", data[offset + 1:offset + 5])[0])
        return val, type_code, 5
    elif type_code == TYPE_UINT32:
        val = float(struct.unpack("<I", data[offset + 1:offset + 5])[0])
        return val, type_code, 5
    elif type_code == TYPE_FLOAT32:
        val = float(struct.unpack("<f", data[offset + 1:offset + 5])[0])
        return val, type_code, 5
    elif type_code == TYPE_FLOAT64:
        val = struct.unpack("<d", data[offset + 1:offset + 9])[0]
        return val, type_code, 9
    elif type_code == TYPE_STRING:
        slen = struct.unpack("<H", data[offset + 1:offset + 3])[0]
        s = data[offset + 3:offset + 3 + slen].decode("utf-8", errors="replace")
        try:
            val = float(s)
        except ValueError:
            val = 0.0
        return val, type_code, 3 + slen
    else:
        # Unknown type, try float64 as fallback
        if offset + 9 <= len(data):
            val = struct.unpack("<d", data[offset + 1:offset + 9])[0]
            return val, type_code, 9
        return 0.0, type_code, 1


# ---------------------------------------------------------------------------
# Frame builders
# ---------------------------------------------------------------------------

def _build_browse() -> bytes:
    """Build a Browse command body."""
    return struct.pack("<I", CMD_BROWSE)


def _build_read(tag: str) -> bytes:
    """Build a Read command body for the given tag name."""
    tag_bytes = tag.encode("utf-8")
    return struct.pack("<I", CMD_READ) + struct.pack("<H", len(tag_bytes)) + tag_bytes


def _build_write_float64(tag: str, value: float) -> bytes:
    """Build a Write command body using float64 raw value.

    The server's _handle_write extracts value_data = data[6+tag_len:] and
    passes it to _unpack_typed_value(data_type, value_data).  That function
    expects raw value bytes (no type-code prefix) and unpacks according to
    the tag's data_type stored server-side.

    Since str(DataType.FLOAT32) == "DataType.FLOAT32" (not "float32"),
    _unpack_typed_value falls through to the ``elif len(data) >= 8`` branch
    which does ``struct.unpack("<d", data[:8])``.  So we send a float64
    (8 bytes) to satisfy both the minimum-length check (8 bytes) and the
    fallback unpack path.
    """
    tag_bytes = tag.encode("utf-8")
    raw_value = struct.pack("<d", value)
    return (struct.pack("<I", CMD_WRITE)
            + struct.pack("<H", len(tag_bytes))
            + tag_bytes
            + raw_value)


def _build_get_status() -> bytes:
    """Build a GetStatus command body."""
    return struct.pack("<I", CMD_GET_STATUS)


# ---------------------------------------------------------------------------
# Server setup
# ---------------------------------------------------------------------------

async def start_server() -> OpcDaServer:
    """Create and start the ProtoForge OPC-DA server with a test device."""
    server = OpcDaServer()

    config = DeviceConfig(
        id="test-opcda",
        name="Test OPCDA Device",
        protocol="opcda",
        points=[
            PointConfig(name="temperature", address="0", data_type="float32",
                        access="rw", fixed_value=25.0),
            PointConfig(name="pressure", address="1", data_type="int32",
                        access="rw", fixed_value=100),
        ],
    )

    await server.create_device(config)

    server._host = HOST
    server._port = PORT
    server._server_running = True
    from protoforge.protocols.behavior import ProtocolStatus
    server._status = ProtocolStatus.RUNNING
    server._server_task = asyncio.create_task(server._serve())
    server._sub_push_task = asyncio.create_task(server._subscription_push_loop())

    # Wait for the server to start accepting connections.
    for attempt in range(20):
        await asyncio.sleep(0.15)
        if server._server_task.done():
            exc = server._server_task.exception()
            raise RuntimeError(f"Server task exited prematurely: {exc}")
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        probe.settimeout(0.5)
        try:
            probe.connect((HOST, PORT))
            probe.close()
            break
        except (ConnectionRefusedError, OSError):
            probe.close()
    else:
        raise RuntimeError("Server did not start listening within 3 seconds")

    return server


# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------

def run_tests() -> list[tuple[str, bool, str]]:
    """Execute all OPC-DA TCP bridge test cases. Returns list of (name, passed, detail)."""
    results: list[tuple[str, bool, str]] = []

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(SOCKET_TIMEOUT)
    try:
        sock.connect((HOST, PORT))
    except ConnectionError as exc:
        results.append(("CONNECT", False, str(exc)))
        return results

    try:
        # ---- Test 1: Browse tags ----
        try:
            _send_frame(sock, _build_browse())
            body = _recv_frame(sock)
            status_code = struct.unpack("<I", body[0:4])[0]
            tag_count = struct.unpack("<I", body[4:8])[0]
            tags = []
            offset = 8
            for _ in range(tag_count):
                if offset + 2 > len(body):
                    break
                tlen = struct.unpack("<H", body[offset:offset + 2])[0]
                offset += 2
                if offset + tlen > len(body):
                    break
                tags.append(body[offset:offset + tlen].decode("utf-8", errors="replace"))
                offset += tlen
            detail = f"status=0x{status_code:08X}, tags={tags}"
            if status_code == 0 and "temperature" in tags and "pressure" in tags:
                results.append(("Browse tags", True, detail))
            else:
                results.append(("Browse tags", False, detail))
        except Exception as exc:
            results.append(("Browse tags", False, str(exc)))

        # ---- Test 2: Read temperature tag (initial value 25.0) ----
        try:
            _send_frame(sock, _build_read("temperature"))
            body = _recv_frame(sock)
            status_code = struct.unpack("<I", body[0:4])[0]
            value, type_code, tv_len = _parse_typed_value(body, 4)
            quality_offset = 4 + tv_len
            quality = struct.unpack("<I", body[quality_offset:quality_offset + 4])[0]
            detail = (f"status=0x{status_code:08X}, type_code={type_code}, "
                      f"value={value:.2f}, quality={quality}")
            if status_code == 0 and abs(value - 25.0) < 0.01:
                results.append(("Read tag (temperature=25.0)", True, detail))
            else:
                results.append(("Read tag (temperature=25.0)", False, detail))
        except Exception as exc:
            results.append(("Read tag (temperature=25.0)", False, str(exc)))

        # ---- Test 3: Write new value to temperature tag ----
        try:
            new_value = 42.5
            _send_frame(sock, _build_write_float64("temperature", new_value))
            body = _recv_frame(sock)
            status_code = struct.unpack("<I", body[0:4])[0]
            detail = f"status=0x{status_code:08X}, wrote={new_value}"
            if status_code == 0:
                results.append((f"Write tag (temperature={new_value})", True, detail))
            else:
                results.append((f"Write tag (temperature={new_value})", False, detail))
        except Exception as exc:
            results.append(("Write tag (temperature=42.5)", False, str(exc)))

        # ---- Test 4: Read back and verify written value ----
        try:
            _send_frame(sock, _build_read("temperature"))
            body = _recv_frame(sock)
            status_code = struct.unpack("<I", body[0:4])[0]
            value, type_code, tv_len = _parse_typed_value(body, 4)
            quality_offset = 4 + tv_len
            quality = struct.unpack("<I", body[quality_offset:quality_offset + 4])[0]
            detail = (f"status=0x{status_code:08X}, type_code={type_code}, "
                      f"value={value:.2f}, quality={quality}")
            if status_code == 0 and abs(value - 42.5) < 0.01:
                results.append(("Read back & verify (temperature=42.5)", True, detail))
            else:
                results.append(("Read back & verify (temperature=42.5)", False, detail))
        except Exception as exc:
            results.append(("Read back & verify (temperature=42.5)", False, str(exc)))

        # ---- Test 5: GetStatus ----
        try:
            _send_frame(sock, _build_get_status())
            body = _recv_frame(sock)
            status_code = struct.unpack("<I", body[0:4])[0]
            server_state = struct.unpack("<I", body[4:8])[0]
            detail = f"status=0x{status_code:08X}, server_state={server_state}"
            if status_code == 0 and server_state == 1:
                results.append(("GetStatus", True, detail))
            else:
                results.append(("GetStatus", False, detail))
        except Exception as exc:
            results.append(("GetStatus", False, str(exc)))

    finally:
        sock.close()

    return results


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main() -> None:
    print("=" * 64)
    print("ProtoForge OPC-DA (TCP-Proto) Diagnostic Test")
    print("=" * 64)

    # Start server
    print(f"\nStarting OPC-DA server on {HOST}:{PORT} ...")
    server = None
    try:
        server = await start_server()
    except Exception as exc:
        print(f"[FATAL] Failed to start server: {exc}")
        sys.exit(1)

    # Run tests in a thread so the blocking socket I/O does not stall the
    # asyncio event loop that the OPC-DA server is running on.
    print("\nRunning tests ...\n")
    results = await asyncio.to_thread(run_tests)

    # Print results
    passed = 0
    failed = 0
    for name, ok, detail in results:
        status = "PASS" if ok else "FAIL"
        if ok:
            passed += 1
        else:
            failed += 1
        print(f"  [{status}] {name}")
        if detail:
            print(f"         {detail}")

    print(f"\n{'=' * 64}")
    print(f"Results: {passed} passed, {failed} failed, {passed + failed} total")
    print("=" * 64)

    # Stop server
    print("\nStopping server ...")
    try:
        await server.stop()
    except Exception as exc:
        print(f"[WARN] Error stopping server: {exc}")

    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    asyncio.run(main())
