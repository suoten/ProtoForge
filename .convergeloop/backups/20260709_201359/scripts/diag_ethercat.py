"""
ProtoForge EtherCAT Diagnostic Test Script

Tests the EtherCAT TCP-sim server using raw TCP sockets.
Validates ESC register reads, process data read/write, and
working counter responses against the ProtoForge EtherCAT
frame handler.

Usage:
    python scripts/diag_ethercat.py
"""

import sys
import os
import socket
import struct
import asyncio

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from protoforge.protocols.ethercat.server import EtherCATServer
from protoforge.models.device import DeviceConfig, PointConfig

HOST = "127.0.0.1"
PORT = 34980
SOCKET_TIMEOUT = 5

# EtherCAT command codes
ECAT_CMD_NOP = 0x00
ECAT_CMD_APRD = 0x01
ECAT_CMD_LRD = 0x0A
ECAT_CMD_LWR = 0x0B

# ESC register addresses (in the 0x1000-0x1FFF range readable by the server)
ECAT_DL_STATUS = 0x0110
ECAT_AL_STATUS = 0x0130

# AL states
ECAT_STATE_INIT = 0x01


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


def build_ecat_frame(cmd: int, idx: int, address: int,
                     data: bytes = b"", irq: int = 0,
                     more_follow: bool = False) -> bytes:
    """Build a complete EtherCAT TCP frame.

    Wire format (what the server reads):
        [2 bytes: payload length LE]
        [1 byte: cmd] [1 byte: idx]
        [4 bytes: address LE]
        [2 bytes: length_flags LE]  (lower 11 bits = data len, bit 15 = more)
        [2 bytes: irq LE]
        [data_len bytes: data]
    """
    data_len = len(data)
    length_flags = data_len | ((1 if more_follow else 0) << 15)
    payload = struct.pack("<BB", cmd, idx)
    payload += struct.pack("<I", address)
    payload += struct.pack("<H", length_flags)
    payload += struct.pack("<H", irq)
    payload += data
    header = struct.pack("<H", len(payload))
    return header + payload


def parse_ecat_response(raw: bytes) -> dict:
    """Parse an EtherCAT TCP response into a dict.

    Response layout:
        [2 bytes: frame length LE]
        [1 byte: cmd] [1 byte: idx]
        [4 bytes: address LE]
        [2 bytes: length_flags LE]
        [2 bytes: irq LE]
        [2 bytes: reserved LE]
        [2 bytes: working_counter LE]
        [result_data bytes]
    """
    if len(raw) < 16:
        raise ValueError(f"Response too short: {len(raw)} bytes")
    frame_len = struct.unpack("<H", raw[0:2])[0]
    cmd = raw[2]
    idx = raw[3]
    address = struct.unpack("<I", raw[4:8])[0]
    length_flags = struct.unpack("<H", raw[8:10])[0]
    irq = struct.unpack("<H", raw[10:12])[0]
    reserved = struct.unpack("<H", raw[12:14])[0]
    working_counter = struct.unpack("<H", raw[14:16])[0]
    result_data = raw[16:]
    resp_data_len = length_flags & 0x07FF
    return {
        "frame_len": frame_len,
        "cmd": cmd,
        "idx": idx,
        "address": address,
        "length_flags": length_flags,
        "irq": irq,
        "reserved": reserved,
        "working_counter": working_counter,
        "data": result_data,
        "data_len": resp_data_len,
    }


def send_recv(sock: socket.socket, frame: bytes) -> dict:
    """Send an EtherCAT frame and return the parsed response."""
    sock.sendall(frame)
    # Read the 2-byte length header
    resp_header = _recv_exact(sock, 2)
    resp_len = struct.unpack("<H", resp_header)[0]
    # Read the remaining payload
    resp_payload = _recv_exact(sock, resp_len) if resp_len > 0 else b""
    return parse_ecat_response(resp_header + resp_payload)


# ---------------------------------------------------------------------------
# Server setup
# ---------------------------------------------------------------------------

async def start_server() -> EtherCATServer:
    """Create and start the ProtoForge EtherCAT server with a test device."""
    server = EtherCATServer()

    # Start the server first (initializes ESC regs, SM channels, FMMU, etc.)
    await server.start({"host": HOST, "port": PORT})

    # Create a test device with one float32 rw point
    config = DeviceConfig(
        id="test-ecat",
        name="Test EtherCAT Device",
        protocol="ethercat",
        points=[
            PointConfig(name="temperature", address="0", data_type="float32",
                        access="rw", fixed_value=25.0),
        ],
    )
    await server.create_device(config)

    # Wait for the server to start accepting connections
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
    """Execute all EtherCAT test cases. Returns list of (name, passed, detail)."""
    results: list[tuple[str, bool, str]] = []

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(SOCKET_TIMEOUT)
    try:
        sock.connect((HOST, PORT))
    except ConnectionError as exc:
        results.append(("CONNECT", False, str(exc)))
        return results

    idx_counter = 0

    try:
        # ---- Test 1: NOP command ----
        idx_counter += 1
        try:
            frame = build_ecat_frame(ECAT_CMD_NOP, idx_counter, 0x00000000)
            resp = send_recv(sock, frame)
            wc = resp["working_counter"]
            if wc == 0x0001:
                results.append(("NOP command (working_counter=1)", True,
                                f"wc=0x{wc:04X}"))
            else:
                results.append(("NOP command (working_counter=1)", False,
                                f"expected wc=0x0001, got wc=0x{wc:04X}"))
        except Exception as exc:
            results.append(("NOP command (working_counter=1)", False, str(exc)))

        # ---- Test 2: Read AL status register (0x0130) ----
        idx_counter += 1
        try:
            frame = build_ecat_frame(ECAT_CMD_APRD, idx_counter, ECAT_AL_STATUS,
                                     data=b"\x00")
            resp = send_recv(sock, frame)
            wc = resp["working_counter"]
            data = resp["data"]
            if wc == 0x0001 and len(data) >= 1 and data[0] == ECAT_STATE_INIT:
                results.append(("Read AL status register (0x0130)", True,
                                f"AL status=0x{data[0]:02X} (INIT), wc=0x{wc:04X}"))
            else:
                al_val = data[0] if data else None
                results.append(("Read AL status register (0x0130)", False,
                                f"expected 0x01, got 0x{al_val:02X}, wc=0x{wc:04X}, "
                                f"data_len={len(data)}"))
        except Exception as exc:
            results.append(("Read AL status register (0x0130)", False, str(exc)))

        # ---- Test 3: Read DL status register (0x0110) ----
        idx_counter += 1
        try:
            frame = build_ecat_frame(ECAT_CMD_APRD, idx_counter, ECAT_DL_STATUS,
                                     data=b"\x00\x00")
            resp = send_recv(sock, frame)
            wc = resp["working_counter"]
            data = resp["data"]
            dl_val = struct.unpack("<H", data[:2])[0] if len(data) >= 2 else None
            if wc == 0x0001 and dl_val == 0x0004:
                results.append(("Read DL status register (0x0110)", True,
                                f"DL status=0x{dl_val:04X}, wc=0x{wc:04X}"))
            else:
                results.append(("Read DL status register (0x0110)", False,
                                f"expected 0x0004, got 0x{dl_val:04X}, wc=0x{wc:04X}"))
        except Exception as exc:
            results.append(("Read DL status register (0x0110)", False, str(exc)))

        # ---- Test 4: Read process data (initial value 25.0) ----
        idx_counter += 1
        try:
            frame = build_ecat_frame(ECAT_CMD_LRD, idx_counter, 0x10000000,
                                     data=b"\x00\x00\x00\x00")
            resp = send_recv(sock, frame)
            wc = resp["working_counter"]
            data = resp["data"]
            if wc == 0x0001 and len(data) >= 4:
                value = struct.unpack("<f", data[:4])[0]
                if abs(value - 25.0) < 0.01:
                    results.append(("Read process data (initial 25.0)", True,
                                    f"value={value:.2f}, wc=0x{wc:04X}"))
                else:
                    results.append(("Read process data (initial 25.0)", False,
                                    f"expected 25.0, got {value:.2f}, wc=0x{wc:04X}"))
            else:
                results.append(("Read process data (initial 25.0)", False,
                                f"wc=0x{wc:04X}, data_len={len(data)}, "
                                f"data={data.hex()}"))
        except Exception as exc:
            results.append(("Read process data (initial 25.0)", False, str(exc)))

        # ---- Test 5: Write process data (42.5) ----
        idx_counter += 1
        try:
            write_value = 42.5
            write_data = struct.pack("<f", write_value)
            frame = build_ecat_frame(ECAT_CMD_LWR, idx_counter, 0x10000000,
                                     data=write_data)
            resp = send_recv(sock, frame)
            wc = resp["working_counter"]
            if wc == 0x0001:
                results.append(("Write process data (42.5)", True,
                                f"wc=0x{wc:04X}"))
            else:
                results.append(("Write process data (42.5)", False,
                                f"expected wc=0x0001, got wc=0x{wc:04X}"))
        except Exception as exc:
            results.append(("Write process data (42.5)", False, str(exc)))

        # ---- Test 6: Read back process data (verify 42.5) ----
        idx_counter += 1
        try:
            frame = build_ecat_frame(ECAT_CMD_LRD, idx_counter, 0x10000000,
                                     data=b"\x00\x00\x00\x00")
            resp = send_recv(sock, frame)
            wc = resp["working_counter"]
            data = resp["data"]
            if wc == 0x0001 and len(data) >= 4:
                value = struct.unpack("<f", data[:4])[0]
                if abs(value - 42.5) < 0.01:
                    results.append(("Read back process data (verify 42.5)", True,
                                    f"value={value:.2f}, wc=0x{wc:04X}"))
                else:
                    results.append(("Read back process data (verify 42.5)", False,
                                    f"expected 42.5, got {value:.2f}, wc=0x{wc:04X}"))
            else:
                results.append(("Read back process data (verify 42.5)", False,
                                f"wc=0x{wc:04X}, data_len={len(data)}, "
                                f"data={data.hex()}"))
        except Exception as exc:
            results.append(("Read back process data (verify 42.5)", False, str(exc)))

        # ---- Test 7: Write process data (0.0) to reset ----
        idx_counter += 1
        try:
            write_data = struct.pack("<f", 0.0)
            frame = build_ecat_frame(ECAT_CMD_LWR, idx_counter, 0x10000000,
                                     data=write_data)
            resp = send_recv(sock, frame)
            wc = resp["working_counter"]
            if wc == 0x0001:
                results.append(("Write process data (0.0 reset)", True,
                                f"wc=0x{wc:04X}"))
            else:
                results.append(("Write process data (0.0 reset)", False,
                                f"expected wc=0x0001, got wc=0x{wc:04X}"))
        except Exception as exc:
            results.append(("Write process data (0.0 reset)", False, str(exc)))

        # ---- Test 8: Read back process data (verify 0.0) ----
        idx_counter += 1
        try:
            frame = build_ecat_frame(ECAT_CMD_LRD, idx_counter, 0x10000000,
                                     data=b"\x00\x00\x00\x00")
            resp = send_recv(sock, frame)
            wc = resp["working_counter"]
            data = resp["data"]
            if wc == 0x0001 and len(data) >= 4:
                value = struct.unpack("<f", data[:4])[0]
                if abs(value) < 0.01:
                    results.append(("Read back process data (verify 0.0)", True,
                                    f"value={value:.2f}, wc=0x{wc:04X}"))
                else:
                    results.append(("Read back process data (verify 0.0)", False,
                                    f"expected 0.0, got {value:.2f}, wc=0x{wc:04X}"))
            else:
                results.append(("Read back process data (verify 0.0)", False,
                                f"wc=0x{wc:04X}, data_len={len(data)}, "
                                f"data={data.hex()}"))
        except Exception as exc:
            results.append(("Read back process data (verify 0.0)", False, str(exc)))

    finally:
        sock.close()

    return results


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main() -> None:
    print("=" * 64)
    print("ProtoForge EtherCAT Diagnostic Test")
    print("=" * 64)

    # Start server
    print(f"\nStarting EtherCAT server on {HOST}:{PORT} ...")
    server = None
    try:
        server = await start_server()
    except Exception as exc:
        print(f"[FATAL] Failed to start server: {exc}")
        sys.exit(1)

    # Run tests in a thread so the blocking socket I/O does not stall the
    # asyncio event loop that the EtherCAT server is running on.
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
