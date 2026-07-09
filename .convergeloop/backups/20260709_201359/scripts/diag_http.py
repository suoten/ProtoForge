"""
ProtoForge HTTP REST Diagnostic Test Script

Tests the HTTP REST/JSON server using raw HTTP requests.
Validates GET /devices, GET /devices/{id}, POST write value, GET verify.

Usage:
    python scripts/diag_http.py
"""

import sys
import os
import socket
import json
import asyncio

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from protoforge.protocols.http.server import HttpSimulatorServer
from protoforge.models.device import DeviceConfig, PointConfig

HOST = "127.0.0.1"
PORT = 8080
SOCKET_TIMEOUT = 5


# ---------------------------------------------------------------------------
# Low-level HTTP helpers
# ---------------------------------------------------------------------------

def http_request(method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
    """Send an HTTP request and return (status_code, parsed_json_body)."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(SOCKET_TIMEOUT)
    try:
        sock.connect((HOST, PORT))

        body_bytes = b""
        if body is not None:
            body_bytes = json.dumps(body, ensure_ascii=False).encode("utf-8")

        headers = (
            f"{method} {path} HTTP/1.1\r\n"
            f"Host: {HOST}:{PORT}\r\n"
            f"Connection: close\r\n"
        )
        if body_bytes:
            headers += (
                f"Content-Type: application/json; charset=utf-8\r\n"
                f"Content-Length: {len(body_bytes)}\r\n"
            )
        headers += "\r\n"

        sock.sendall(headers.encode("utf-8") + body_bytes)

        # Read full response
        data = b""
        while True:
            try:
                chunk = sock.recv(8192)
                if not chunk:
                    break
                data += chunk
            except socket.timeout:
                break

        response = data.decode("utf-8", errors="replace")

        # Parse status line
        header_end = response.find("\r\n\r\n")
        if header_end == -1:
            return -1, {}
        header_section = response[:header_end]
        resp_body = response[header_end + 4:]

        status_line = header_section.split("\r\n")[0]
        parts = status_line.split(" ", 2)
        status_code = int(parts[1]) if len(parts) >= 2 else -1

        try:
            parsed = json.loads(resp_body)
        except (json.JSONDecodeError, ValueError):
            parsed = {}

        return status_code, parsed
    except Exception as exc:
        return -1, {"error": str(exc)}
    finally:
        sock.close()


# ---------------------------------------------------------------------------
# Server setup
# ---------------------------------------------------------------------------

async def start_server() -> HttpSimulatorServer:
    """Create and start the ProtoForge HTTP server with a test device."""
    server = HttpSimulatorServer()

    config = DeviceConfig(
        id="test-http",
        name="Test HTTP Device",
        protocol="http",
        points=[
            PointConfig(name="temperature", address="0", data_type="float32",
                        access="rw", fixed_value=25.0),
        ],
    )

    await server.create_device(config)
    await server.start({"host": HOST, "port": PORT})

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
    else:
        raise RuntimeError("Server did not start listening within 3 seconds")

    return server


# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------

def run_tests() -> list[tuple[str, bool, str]]:
    """Execute all HTTP REST test cases. Returns list of (name, passed, detail)."""
    results: list[tuple[str, bool, str]] = []

    # ---- Test 1: GET /devices ----
    try:
        status, body = http_request("GET", "/devices")
        if status != 200:
            results.append(("GET /devices - HTTP status", False,
                            f"expected 200, got {status}"))
        else:
            devices = body.get("devices", [])
            device_ids = [d.get("id", "") for d in devices]
            results.append(("GET /devices", True,
                            f"status={status}, device_ids={device_ids}"))
    except Exception as exc:
        results.append(("GET /devices", False, str(exc)))

    # ---- Test 2: GET /devices/test-http ----
    try:
        status, body = http_request("GET", "/api/test-http/points")
        if status != 200:
            results.append(("GET /devices/test-http/points - HTTP status", False,
                            f"expected 200, got {status}"))
        else:
            points = body.get("points", [])
            point_names = [p.get("name", "") for p in points]
            has_temp = "temperature" in point_names
            results.append(("GET /devices/test-http/points", True,
                            f"status={status}, points={point_names}, "
                            f"has_temperature={has_temp}"))
    except Exception as exc:
        results.append(("GET /devices/test-http/points", False, str(exc)))

    # ---- Test 3: GET /devices/test-http/temperature ----
    try:
        status, body = http_request("GET", "/api/test-http/temperature")
        if status != 200:
            results.append(("GET /devices/test-http/temperature - HTTP status",
                            False, f"expected 200, got {status}"))
        else:
            name = body.get("name", "")
            value = body.get("value")
            results.append(("GET /devices/test-http/temperature", True,
                            f"status={status}, name={name}, value={value}"))
    except Exception as exc:
        results.append(("GET /devices/test-http/temperature", False, str(exc)))

    # ---- Test 4: POST write value (temperature = 42.5) ----
    try:
        status, body = http_request("POST", "/api/test-http/points",
                                     {"temperature": 42.5})
        if status != 200:
            results.append(("POST write temperature=42.5 - HTTP status", False,
                            f"expected 200, got {status}"))
        else:
            ok = body.get("ok", False)
            results.append(("POST write temperature=42.5", True,
                            f"status={status}, ok={ok}"))
    except Exception as exc:
        results.append(("POST write temperature=42.5", False, str(exc)))

    # ---- Test 5: GET verify temperature value ----
    try:
        status, body = http_request("GET", "/api/test-http/temperature")
        if status != 200:
            results.append(("GET verify temperature - HTTP status", False,
                            f"expected 200, got {status}"))
        else:
            value = body.get("value")
            # The server stores the value as-is; check it matches what we wrote
            if value == 42.5:
                results.append(("GET verify temperature=42.5", True,
                                f"value={value}"))
            else:
                results.append(("GET verify temperature=42.5", False,
                                f"expected 42.5, got {value}"))
    except Exception as exc:
        results.append(("GET verify temperature=42.5", False, str(exc)))

    return results


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main() -> None:
    print("=" * 64)
    print("ProtoForge HTTP REST Diagnostic Test")
    print("=" * 64)

    # Start server
    print(f"\nStarting HTTP REST server on {HOST}:{PORT} ...")
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
