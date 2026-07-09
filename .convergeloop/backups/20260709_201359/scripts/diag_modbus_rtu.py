"""
ProtoForge Modbus RTU (TCP Bridge) Diagnostic Test Script

Tests the Modbus RTU server running in TCP bridge mode using raw TCP sockets
with MBAP header + PDU frame format. Validates FC03 Read Holding Registers,
FC06 Write Single Register, and Read back verify operations.

Usage:
    python scripts/diag_modbus_rtu.py
"""

import sys
import os
import socket
import struct
import asyncio

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from protoforge.protocols.modbus.rtu_server import ModbusRtuServer
from protoforge.models.device import DeviceConfig, PointConfig

HOST = "127.0.0.1"
PORT = 5021
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


# ---------------------------------------------------------------------------
# Server setup
# ---------------------------------------------------------------------------

async def start_server() -> ModbusRtuServer:
    """Create and start the ProtoForge Modbus RTU server with a test device.

    The RTU server falls back to TCP bridge mode when the serial port
    doesn't exist (which is the case on most test machines).
    """
    server = ModbusRtuServer()

    config = DeviceConfig(
        id="test-modbus-rtu",
        name="Test Modbus RTU Device",
        protocol="modbus_rtu",
        points=[
            PointConfig(name="temperature", address="0", data_type="float32",
                        access="rw", fixed_value=25.0),
        ],
    )

    # Register the device (sets up behavior, slave_map, device_configs).
    await server.create_device(config)

    # Manually populate the data store since create_device() skips
    # _apply_device_to_context when the server is not yet RUNNING.
    server._apply_device_to_context(config)

    # Start the server - it will fall back to TCP bridge mode since
    # COM1/serial port likely doesn't exist on the test machine.
    await server.start({
        "host": HOST,
        "port": "COM1",  # Will trigger TCP bridge fallback
        "tcp_bridge_port": PORT,
    })

    # Wait for the server to start accepting connections.
    for attempt in range(20):
        await asyncio.sleep(0.15)
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        probe.settimeout(0.5)
        try:
            probe.connect((HOST, PORT))
            probe.close()
            break
        except (ConnectionRefusedError, OSError):
            probe.close()
            # Also try nearby ports since _find_available_port might shift
            for offset in range(1, 5):
                try:
                    p = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    p.settimeout(0.3)
                    p.connect((HOST, PORT + offset))
                    p.close()
                    # Found the actual port - update PORT for tests
                    break
                except (ConnectionRefusedError, OSError):
                    pass
    else:
        raise RuntimeError("Server did not start listening within 3 seconds")

    return server


# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------

def run_tests() -> list[tuple[str, bool, str]]:
    """Execute all Modbus RTU test cases. Returns list of (name, passed, detail)."""
    results: list[tuple[str, bool, str]] = []

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(SOCKET_TIMEOUT)

    # Try to connect - the server might be on a different port if PORT was taken
    connected = False
    actual_port = PORT
    for port in [PORT, PORT + 1, PORT + 2, PORT + 3]:
        try:
            sock.connect((HOST, port))
            actual_port = port
            connected = True
            break
        except ConnectionError:
            continue

    if not connected:
        results.append(("CONNECT", False, f"Cannot connect to {HOST}:{PORT}"))
        return results

    try:
        # ---- Test 1: FC03 Read Holding Registers (2 regs from addr 0) ----
        # temperature=25.0 as float32 BE => 0x41C80000 => regs [0x41C8, 0x0000]
        try:
            regs = fc03_read(sock, UNIT_ID, 0, 2)
            detail = f"regs={[f'0x{r:04X}' for r in regs]}"
            if len(regs) == 2:
                # Verify the float32 value
                raw = struct.pack(">HH", regs[0], regs[1])
                value = struct.unpack(">f", raw)[0]
                if abs(value - 25.0) < 0.01:
                    results.append(("FC03 Read Holding Registers (temperature)", True,
                                    f"value={value}, {detail}"))
                else:
                    results.append(("FC03 Read Holding Registers (temperature)", False,
                                    f"expected ~25.0, got {value}, {detail}"))
            else:
                results.append(("FC03 Read Holding Registers (temperature)", False,
                                f"expected 2 registers, got {len(regs)}: {detail}"))
        except Exception as exc:
            results.append(("FC03 Read Holding Registers (temperature)", False, str(exc)))

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

        # ---- Test 4: FC06 Write Single Register (5678 to addr 1) ----
        try:
            echo_addr, echo_val = fc06_write(sock, UNIT_ID, 1, 5678)
            if echo_addr == 1 and echo_val == 5678:
                results.append(("FC06 Write Single Register (addr=1, val=5678)",
                                True, f"echo addr={echo_addr} val={echo_val}"))
            else:
                results.append(("FC06 Write Single Register (addr=1, val=5678)",
                                False, f"echo addr={echo_addr} val={echo_val}"))
        except Exception as exc:
            results.append(("FC06 Write Single Register (addr=1, val=5678)",
                            False, str(exc)))

        # ---- Test 5: FC03 Read back both registers ----
        try:
            regs = fc03_read(sock, UNIT_ID, 0, 2)
            if regs == [1234, 5678]:
                results.append(("FC03 Read back both registers", True,
                                f"regs={[f'0x{r:04X}' for r in regs]}"))
            else:
                results.append(("FC03 Read back both registers", False,
                                f"expected [1234, 5678], got {regs}"))
        except Exception as exc:
            results.append(("FC03 Read back both registers", False, str(exc)))

    finally:
        sock.close()

    return results


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main() -> None:
    print("=" * 64)
    print("ProtoForge Modbus RTU (TCP Bridge) Diagnostic Test")
    print("=" * 64)

    # Start server
    print(f"\nStarting Modbus RTU server (TCP bridge) on {HOST}:{PORT} ...")
    server = None
    try:
        server = await start_server()
    except Exception as exc:
        print(f"[FATAL] Failed to start server: {exc}")
        sys.exit(1)

    # Run tests in a thread so the blocking socket I/O does not stall the
    # asyncio event loop that the server is running on.
    print("\nRunning tests ...\n")
    results = await asyncio.to_thread(run_tests)

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
