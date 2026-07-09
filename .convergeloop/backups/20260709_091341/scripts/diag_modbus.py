"""
ProtoForge Modbus TCP Diagnostic Test Script

Tests the Modbus TCP server using raw TCP sockets (no pymodbus dependency
on the client side). Validates FC01/03/04/05/06/16 operations against
the ProtoForge native Modbus frame handler.

Usage:
    python scripts/diag_modbus.py
"""

import sys
import os
import socket
import struct
import asyncio

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from protoforge.protocols.modbus.server import ModbusTcpServer
from protoforge.models.device import DeviceConfig, PointConfig

HOST = "127.0.0.1"
PORT = 5020
UNIT_ID = 1
SOCKET_TIMEOUT = 5

# ---------------------------------------------------------------------------
# Global transaction ID counter
# ---------------------------------------------------------------------------
_tx_counter = 0


def _next_tx_id() -> int:
    global _tx_counter
    _tx_counter += 1
    return _tx_counter


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


def _send_recv(sock: socket.socket, unit_id: int, pdu: bytes) -> bytes:
    """Build MBAP header, send request, read and return full response."""
    tx_id = _next_tx_id()
    # MBAP: TransactionID(2) + ProtocolID(2) + Length(2) + UnitID(1)
    # Length = 1 (UnitID) + len(pdu)
    mbap = struct.pack(">HHHB", tx_id, 0x0000, len(pdu) + 1, unit_id)
    sock.sendall(mbap + pdu)

    # Read MBAP header (7 bytes)
    header = _recv_exact(sock, 7)
    resp_tx_id = struct.unpack(">H", header[0:2])[0]
    resp_proto_id = struct.unpack(">H", header[2:4])[0]
    resp_length = struct.unpack(">H", header[4:6])[0]
    resp_unit_id = header[6]

    # Read remaining payload (Length field includes UnitID byte already read)
    payload_len = resp_length - 1
    payload = _recv_exact(sock, payload_len) if payload_len > 0 else b""
    return header + payload


def _check_exception(resp: bytes, fc_name: str) -> None:
    """Raise if the response is a Modbus exception."""
    fc = resp[7]
    if fc & 0x80:
        exc_code = resp[8] if len(resp) > 8 else -1
        raise RuntimeError(f"{fc_name} exception: code 0x{exc_code:02X}")


# ---------------------------------------------------------------------------
# Modbus function code helpers
# ---------------------------------------------------------------------------

def fc03_read(sock: socket.socket, unit_id: int, start: int, count: int) -> list[int]:
    """FC03 Read Holding Registers."""
    pdu = struct.pack(">BHH", 0x03, start, count)
    resp = _send_recv(sock, unit_id, pdu)
    _check_exception(resp, "FC03")
    byte_count = resp[8]
    regs = []
    for i in range(byte_count // 2):
        regs.append(struct.unpack(">H", resp[9 + i * 2: 11 + i * 2])[0])
    return regs


def fc06_write(sock: socket.socket, unit_id: int, addr: int, value: int) -> tuple[int, int]:
    """FC06 Write Single Register. Returns (echo_addr, echo_value)."""
    pdu = struct.pack(">BHH", 0x06, addr, value)
    resp = _send_recv(sock, unit_id, pdu)
    _check_exception(resp, "FC06")
    echo_addr = struct.unpack(">H", resp[8:10])[0]
    echo_val = struct.unpack(">H", resp[10:12])[0]
    return echo_addr, echo_val


def fc16_write(sock: socket.socket, unit_id: int, start: int,
               values: list[int]) -> tuple[int, int]:
    """FC16 Write Multiple Registers. Returns (echo_start, echo_count)."""
    count = len(values)
    byte_count = count * 2
    pdu = struct.pack(">BHHB", 0x10, start, count, byte_count)
    for v in values:
        pdu += struct.pack(">H", v)
    resp = _send_recv(sock, unit_id, pdu)
    _check_exception(resp, "FC16")
    echo_start = struct.unpack(">H", resp[8:10])[0]
    echo_count = struct.unpack(">H", resp[10:12])[0]
    return echo_start, echo_count


def fc01_read(sock: socket.socket, unit_id: int, start: int, count: int) -> list[bool]:
    """FC01 Read Coils."""
    pdu = struct.pack(">BHH", 0x01, start, count)
    resp = _send_recv(sock, unit_id, pdu)
    _check_exception(resp, "FC01")
    byte_count = resp[8]
    coils: list[bool] = []
    for i in range(count):
        byte_idx = i // 8
        bit_idx = i % 8
        coils.append(bool(resp[9 + byte_idx] & (1 << bit_idx)))
    return coils


def fc05_write(sock: socket.socket, unit_id: int, addr: int,
               on: bool) -> tuple[int, int]:
    """FC05 Write Single Coil. Returns (echo_addr, echo_value)."""
    value = 0xFF00 if on else 0x0000
    pdu = struct.pack(">BHH", 0x05, addr, value)
    resp = _send_recv(sock, unit_id, pdu)
    _check_exception(resp, "FC05")
    echo_addr = struct.unpack(">H", resp[8:10])[0]
    echo_val = struct.unpack(">H", resp[10:12])[0]
    return echo_addr, echo_val


def fc04_read(sock: socket.socket, unit_id: int, start: int, count: int) -> list[int]:
    """FC04 Read Input Registers."""
    pdu = struct.pack(">BHH", 0x04, start, count)
    resp = _send_recv(sock, unit_id, pdu)
    _check_exception(resp, "FC04")
    byte_count = resp[8]
    regs = []
    for i in range(byte_count // 2):
        regs.append(struct.unpack(">H", resp[9 + i * 2: 11 + i * 2])[0])
    return regs


# ---------------------------------------------------------------------------
# Server setup
# ---------------------------------------------------------------------------

async def start_server() -> ModbusTcpServer:
    """Create and start the ProtoForge Modbus TCP server with a test device.

    Uses the native frame handler directly so that raw-socket tests exercise
    the ProtoForge Modbus frame processing code path, not the pymodbus
    library.  This also avoids the pymodbus SimData / OldAPI initialisation
    ordering issue where create_device() before start() leaves the data
    store empty.
    """
    server = ModbusTcpServer()

    config = DeviceConfig(
        id="test-modbus",
        name="Test Modbus Device",
        protocol="modbus_tcp",
        points=[
            PointConfig(name="temperature", address="0", data_type="float32",
                        access="rw", fixed_value=25.0),
            PointConfig(name="pressure", address="2", data_type="int32",
                        access="rw", fixed_value=100),
            PointConfig(name="status", address="4", data_type="uint16",
                        access="rw", fixed_value=1),
            PointConfig(name="coil0", address="0", data_type="bool",
                        access="rw", fixed_value=False),
        ],
    )

    # Register the device (sets up behavior, slave_map, device_configs).
    await server.create_device(config)

    # Manually populate the data store since create_device() skips
    # _apply_device_to_context when the server is not yet RUNNING.
    server._apply_device_to_context(config)

    # Force native frame server mode (bypasses pymodbus dependency).
    server._host = HOST
    server._port = PORT
    server._server_running = True
    server._status = type(server._status).RUNNING
    server._server_task = asyncio.create_task(server._serve_datastore_only())

    # Wait for the server to start accepting connections.
    for attempt in range(20):
        await asyncio.sleep(0.15)
        if server._server_task.done():
            exc = server._server_task.exception()
            raise RuntimeError(f"Server task exited prematurely: {exc}")
        # Probe the port to see if it's open.
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
    """Execute all Modbus TCP test cases. Returns list of (name, passed, detail)."""
    results: list[tuple[str, bool, str]] = []

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(SOCKET_TIMEOUT)
    try:
        sock.connect((HOST, PORT))
    except ConnectionError as exc:
        results.append(("CONNECT", False, str(exc)))
        return results

    try:
        # ---- Test 1: FC03 Read Holding Registers (10 regs from addr 0) ----
        try:
            regs = fc03_read(sock, UNIT_ID, 0, 10)
            # temperature=25.0 as float32 BE => 0x41C80000 => regs [0x41C8, 0x0000]
            # pressure=100 as int32 BE => 0x00000064 => regs [0x0000, 0x0064]
            # status=1 as uint16 => 0x0001
            detail = f"regs={[f'0x{r:04X}' for r in regs]}"
            if len(regs) == 10:
                results.append(("FC03 Read 10 Holding Registers", True, detail))
            else:
                results.append(("FC03 Read 10 Holding Registers", False,
                                f"expected 10 registers, got {len(regs)}: {detail}"))
        except Exception as exc:
            results.append(("FC03 Read 10 Holding Registers", False, str(exc)))

        # ---- Test 2: FC06 Write Single Register (1234 to addr 0) ----
        try:
            echo_addr, echo_val = fc06_write(sock, UNIT_ID, 0, 1234)
            if echo_addr == 0 and echo_val == 1234:
                results.append(("FC06 Write Single Register (addr=0, val=1234)",
                                True, f"echo addr={echo_addr} val={echo_val}"))
            else:
                results.append(("FC06 Write Single Register (addr=0, val=1234)",
                                False, f"echo addr={echo_addr} val={echo_val}"))
        except Exception as exc:
            results.append(("FC06 Write Single Register (addr=0, val=1234)",
                            False, str(exc)))

        # ---- Test 3: FC03 Read back and verify ----
        try:
            regs = fc03_read(sock, UNIT_ID, 0, 1)
            if regs and regs[0] == 1234:
                results.append(("FC03 Read back after FC06", True,
                                f"reg[0]=0x{regs[0]:04X} ({regs[0]})"))
            else:
                results.append(("FC03 Read back after FC06", False,
                                f"expected 1234, got {regs}"))
        except Exception as exc:
            results.append(("FC03 Read back after FC06", False, str(exc)))

        # ---- Test 4: FC16 Write Multiple Registers ([100,200,300] to addr 1) ----
        try:
            echo_start, echo_count = fc16_write(sock, UNIT_ID, 1, [100, 200, 300])
            if echo_start == 1 and echo_count == 3:
                results.append(("FC16 Write Multiple Registers (addr=1, [100,200,300])",
                                True, f"echo start={echo_start} count={echo_count}"))
            else:
                results.append(("FC16 Write Multiple Registers (addr=1, [100,200,300])",
                                False, f"echo start={echo_start} count={echo_count}"))
        except Exception as exc:
            results.append(("FC16 Write Multiple Registers (addr=1, [100,200,300])",
                            False, str(exc)))

        # ---- Test 5: FC03 Read back and verify FC16 ----
        try:
            regs = fc03_read(sock, UNIT_ID, 1, 3)
            if regs == [100, 200, 300]:
                results.append(("FC03 Read back after FC16", True,
                                f"regs={regs}"))
            else:
                results.append(("FC03 Read back after FC16", False,
                                f"expected [100,200,300], got {regs}"))
        except Exception as exc:
            results.append(("FC03 Read back after FC16", False, str(exc)))

        # ---- Test 6: FC01 Read Coils (8 coils from addr 0) ----
        try:
            coils = fc01_read(sock, UNIT_ID, 0, 8)
            detail = f"coils={coils}"
            if len(coils) == 8:
                results.append(("FC01 Read 8 Coils", True, detail))
            else:
                results.append(("FC01 Read 8 Coils", False,
                                f"expected 8 coils, got {len(coils)}: {detail}"))
        except Exception as exc:
            results.append(("FC01 Read 8 Coils", False, str(exc)))

        # ---- Test 7: FC05 Write Single Coil (ON to coil 0) ----
        try:
            echo_addr, echo_val = fc05_write(sock, UNIT_ID, 0, True)
            if echo_addr == 0 and echo_val == 0xFF00:
                results.append(("FC05 Write Single Coil (addr=0, ON)",
                                True, f"echo addr={echo_addr} val=0x{echo_val:04X}"))
            else:
                results.append(("FC05 Write Single Coil (addr=0, ON)",
                                False, f"echo addr={echo_addr} val=0x{echo_val:04X}"))
        except Exception as exc:
            results.append(("FC05 Write Single Coil (addr=0, ON)", False, str(exc)))

        # ---- Test 8: FC01 Read back coils and verify ----
        try:
            coils = fc01_read(sock, UNIT_ID, 0, 8)
            if coils and coils[0] is True:
                results.append(("FC01 Read back after FC05", True,
                                f"coil[0]={coils[0]}"))
            else:
                results.append(("FC01 Read back after FC05", False,
                                f"expected coil[0]=True, got {coils}"))
        except Exception as exc:
            results.append(("FC01 Read back after FC05", False, str(exc)))

        # ---- Test 9: FC04 Read Input Registers (4 regs from addr 0) ----
        try:
            regs = fc04_read(sock, UNIT_ID, 0, 4)
            detail = f"regs={[f'0x{r:04X}' for r in regs]}"
            if len(regs) == 4:
                results.append(("FC04 Read 4 Input Registers", True, detail))
            else:
                results.append(("FC04 Read 4 Input Registers", False,
                                f"expected 4 registers, got {len(regs)}: {detail}"))
        except Exception as exc:
            results.append(("FC04 Read 4 Input Registers", False, str(exc)))

    finally:
        sock.close()

    return results


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main() -> None:
    print("=" * 64)
    print("ProtoForge Modbus TCP Diagnostic Test")
    print("=" * 64)

    # Start server
    print(f"\nStarting Modbus TCP server on {HOST}:{PORT} ...")
    server = None
    try:
        server = await start_server()
    except Exception as exc:
        print(f"[FATAL] Failed to start server: {exc}")
        sys.exit(1)

    # Run tests in a thread so the blocking socket I/O does not stall the
    # asyncio event loop that the Modbus server is running on.
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
