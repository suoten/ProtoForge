"""
ProtoForge Mettler-Toledo MT-SICS Diagnostic Test Script

Tests the Toledo server using raw TCP sockets. Validates S, SI, T, Z
commands against the ProtoForge MT-SICS protocol handler.

Usage:
    python scripts/diag_toledo.py
"""

import sys
import os
import socket
import asyncio
import re

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from protoforge.protocols.toledo.server import ToledoServer
from protoforge.models.device import DeviceConfig, PointConfig

HOST = "127.0.0.1"
PORT = 1701
SOCKET_TIMEOUT = 5

# ---------------------------------------------------------------------------
# Result tracking
# ---------------------------------------------------------------------------
results: list[tuple[str, bool, str]] = []


def record(name: str, passed: bool, detail: str = "") -> None:
    tag = "PASS" if passed else "FAIL"
    results.append((name, passed, detail))
    print(f"  [{tag}] {name}" + (f"  -- {detail}" if detail else ""))


# ---------------------------------------------------------------------------
# TCP helpers (blocking — must be called via asyncio.to_thread)
# ---------------------------------------------------------------------------

def _send_recv(cmd: str) -> str:
    """Send an MT-SICS command and return the raw ASCII response."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(SOCKET_TIMEOUT)
        sock.connect((HOST, PORT))
        sock.sendall((cmd + "\r\n").encode("ascii"))
        data = sock.recv(1024)
    return data.decode("ascii", errors="replace")


async def send_recv(cmd: str) -> str:
    """Async wrapper: runs the blocking socket call in a thread."""
    return await asyncio.to_thread(_send_recv, cmd)


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------

# Weight response format: sign(1) + value(8.3f) + unit(2-3) + stable_flag(1) + zero_flag(1) + \r\n
# Example: " 0000.000kg Z\r\n" or "-0012.500kg  \r\n"
WEIGHT_RE = re.compile(
    r"^([ ]|[-])"
    r"(\d{4}\.\d{3})"
    r"(kg|g |lb|oz|t )"
    r"([ SUD])"
    r"([ Z])"
    r"\r\n$"
)


def parse_weight_response(raw: str) -> dict | None:
    """Parse a weight response string into components. Returns None on failure."""
    m = WEIGHT_RE.match(raw)
    if not m:
        return None
    sign, value_str, unit, stable, zero = m.groups()
    value = float(value_str)
    if sign == "-":
        value = -value
    return {
        "sign": sign,
        "value": value,
        "unit": unit.strip(),
        "stable": stable.strip(),
        "zero": zero.strip(),
        "raw": raw,
    }


# ---------------------------------------------------------------------------
# Server lifecycle
# ---------------------------------------------------------------------------

async def start_server() -> ToledoServer:
    server = ToledoServer()
    server._host = HOST
    server._port = PORT
    config = DeviceConfig(
        id="test-toledo",
        name="Test Toledo Device",
        protocol="toledo",
        points=[
            PointConfig(name="weight", address="0", data_type="float32", access="rw"),
        ],
    )
    await server.create_device(config)
    await server.start({"host": HOST, "port": PORT})
    await asyncio.sleep(0.3)
    return server


# ---------------------------------------------------------------------------
# Test cases (all async so they yield to the event loop during socket I/O)
# ---------------------------------------------------------------------------

async def test_s_command_zero_weight() -> None:
    """S command on a freshly-created device should return zero weight."""
    raw = await send_recv("S")
    parsed = parse_weight_response(raw)
    if parsed is None:
        record("S command (zero weight) - response format", False,
               f"response does not match weight pattern: {raw!r}")
        return
    record("S command (zero weight) - response format", True,
           f"raw={raw!r}")
    record("S command (zero weight) - value is 0", parsed["value"] == 0.0,
           f"value={parsed['value']}")
    record("S command (zero weight) - unit is kg", parsed["unit"] == "kg",
           f"unit={parsed['unit']!r}")


async def test_si_command() -> None:
    """SI command (immediate stable weight) should return same format as S."""
    raw = await send_recv("SI")
    parsed = parse_weight_response(raw)
    if parsed is None:
        record("SI command - response format", False,
               f"response does not match weight pattern: {raw!r}")
        return
    record("SI command - response format", True, f"raw={raw!r}")
    record("SI command - value is 0", parsed["value"] == 0.0,
           f"value={parsed['value']}")


async def test_tare_command() -> None:
    """T command should set tare equal to current weight and return net=0."""
    raw = await send_recv("T")
    parsed = parse_weight_response(raw)
    if parsed is None:
        record("T command (tare at zero) - response format", False,
               f"response does not match weight pattern: {raw!r}")
        return
    record("T command (tare at zero) - response format", True, f"raw={raw!r}")
    record("T command (tare at zero) - net weight is 0", parsed["value"] == 0.0,
           f"value={parsed['value']}")


async def test_zero_command() -> None:
    """Z command should reset weight and tare to 0, return zero flag Z."""
    raw = await send_recv("Z")
    parsed = parse_weight_response(raw)
    if parsed is None:
        record("Z command - response format", False,
               f"response does not match weight pattern: {raw!r}")
        return
    record("Z command - response format", True, f"raw={raw!r}")
    record("Z command - value is 0", parsed["value"] == 0.0,
           f"value={parsed['value']}")
    record("Z command - zero flag is Z", parsed["zero"] == "Z",
           f"zero_flag={parsed['zero']!r}")


async def test_s_command_with_weight() -> None:
    """After writing a weight via the server, S should reflect the value."""
    server = _server_ref
    await server.write_point("test-toledo", "weight", 12.5)

    raw = await send_recv("S")
    parsed = parse_weight_response(raw)
    if parsed is None:
        record("S command (weight=12.5) - response format", False,
               f"response does not match weight pattern: {raw!r}")
        return
    record("S command (weight=12.5) - response format", True, f"raw={raw!r}")
    record("S command (weight=12.5) - value is 12.5", parsed["value"] == 12.5,
           f"value={parsed['value']}")


async def test_tare_with_weight() -> None:
    """Tare when weight is non-zero should set tare=weight, net=0."""
    raw = await send_recv("T")
    parsed = parse_weight_response(raw)
    if parsed is None:
        record("T command (tare at 12.5) - response format", False,
               f"response does not match weight pattern: {raw!r}")
        return
    record("T command (tare at 12.5) - response format", True, f"raw={raw!r}")
    record("T command (tare at 12.5) - net weight is 0", parsed["value"] == 0.0,
           f"value={parsed['value']}")


async def test_zero_resets_tare() -> None:
    """Z command should reset both weight and tare to 0."""
    server = _server_ref
    await server.write_point("test-toledo", "weight", 25.0)
    await send_recv("T")
    raw = await send_recv("Z")
    parsed = parse_weight_response(raw)
    if parsed is None:
        record("Z resets tare - response format", False,
               f"response does not match weight pattern: {raw!r}")
        return
    record("Z resets tare - value is 0", parsed["value"] == 0.0,
           f"value={parsed['value']}")
    record("Z resets tare - zero flag is Z", parsed["zero"] == "Z",
           f"zero_flag={parsed['zero']!r}")

    raw2 = await send_recv("S")
    parsed2 = parse_weight_response(raw2)
    if parsed2:
        record("Z resets tare - S confirms zero", parsed2["value"] == 0.0,
               f"value={parsed2['value']}")
    else:
        record("Z resets tare - S confirms zero", False,
               f"bad response: {raw2!r}")


async def test_lowercase_commands() -> None:
    """Lowercase s, t, z should work the same as uppercase."""
    server = _server_ref
    await send_recv("Z")
    await server.write_point("test-toledo", "weight", 3.0)

    raw = await send_recv("s")
    parsed = parse_weight_response(raw)
    if parsed is None:
        record("Lowercase 's' command - response format", False,
               f"response does not match weight pattern: {raw!r}")
        return
    record("Lowercase 's' command - response format", True, f"raw={raw!r}")
    record("Lowercase 's' command - value is 3.0", parsed["value"] == 3.0,
           f"value={parsed['value']}")

    raw_t = await send_recv("t")
    parsed_t = parse_weight_response(raw_t)
    if parsed_t:
        record("Lowercase 't' command - net is 0", parsed_t["value"] == 0.0,
               f"value={parsed_t['value']}")
    else:
        record("Lowercase 't' command - net is 0", False,
               f"bad response: {raw_t!r}")

    raw_z = await send_recv("z")
    parsed_z = parse_weight_response(raw_z)
    if parsed_z:
        record("Lowercase 'z' command - value is 0", parsed_z["value"] == 0.0,
               f"value={parsed_z['value']}")
    else:
        record("Lowercase 'z' command - value is 0", False,
               f"bad response: {raw_z!r}")


# ---------------------------------------------------------------------------
# Global server reference
# ---------------------------------------------------------------------------
_server_ref: ToledoServer = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main() -> None:
    global _server_ref

    print("=" * 60)
    print("ProtoForge Mettler-Toledo MT-SICS Diagnostic Test")
    print("=" * 60)

    print("\n[Setup] Starting Toledo server on %s:%d ..." % (HOST, PORT))
    try:
        _server_ref = await start_server()
    except Exception as e:
        print(f"\n[FATAL] Could not start server: {e}")
        sys.exit(1)
    print("[Setup] Server started.\n")

    print("[Test 1] S command - read stable weight (zero)")
    await test_s_command_zero_weight()

    print("\n[Test 2] SI command - read immediate stable weight")
    await test_si_command()

    print("\n[Test 3] T command - tare at zero weight")
    await test_tare_command()

    print("\n[Test 4] Z command - zero the scale")
    await test_zero_command()

    print("\n[Test 5] S command - read weight after write_point(12.5)")
    await test_s_command_with_weight()

    print("\n[Test 6] T command - tare at non-zero weight")
    await test_tare_with_weight()

    print("\n[Test 7] Z command - resets both weight and tare")
    await test_zero_resets_tare()

    print("\n[Test 8] Lowercase commands (s, t, z)")
    await test_lowercase_commands()

    print("\n[Teardown] Stopping server ...")
    await _server_ref.stop()
    print("[Teardown] Server stopped.\n")

    total = len(results)
    passed = sum(1 for _, ok, _ in results if ok)
    failed = total - passed
    print("=" * 60)
    print(f"Results: {passed}/{total} passed, {failed} failed")
    print("=" * 60)
    if failed:
        print("\nFailed tests:")
        for name, ok, detail in results:
            if not ok:
                print(f"  - {name}: {detail}")
        sys.exit(1)
    else:
        print("\nAll tests passed!")
        sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())
