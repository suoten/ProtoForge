"""
ProtoForge MTConnect Diagnostic Test Script

Tests the MTConnect server using raw HTTP GET requests and XML response parsing.
Validates /probe, /current, and /sample endpoints.

Usage:
    python scripts/diag_mtconnect.py
"""

import sys
import os
import socket
import asyncio
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from protoforge.protocols.mtconnect.server import MtConnectServer
from protoforge.models.device import DeviceConfig, PointConfig

HOST = "127.0.0.1"
PORT = 7878
SOCKET_TIMEOUT = 5


# ---------------------------------------------------------------------------
# Low-level HTTP helpers
# ---------------------------------------------------------------------------

def http_get(path: str) -> tuple[int, str]:
    """Send an HTTP GET request and return (status_code, body)."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(SOCKET_TIMEOUT)
    try:
        sock.connect((HOST, PORT))
        request = f"GET {path} HTTP/1.1\r\nHost: {HOST}:{PORT}\r\nConnection: close\r\n\r\n"
        sock.sendall(request.encode("utf-8"))

        # Read full response
        data = b""
        while True:
            try:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                data += chunk
            except socket.timeout:
                break

        response = data.decode("utf-8", errors="replace")

        # Parse status line
        header_end = response.find("\r\n\r\n")
        if header_end == -1:
            return -1, ""
        header_section = response[:header_end]
        body = response[header_end + 4:]

        status_line = header_section.split("\r\n")[0]
        parts = status_line.split(" ", 2)
        status_code = int(parts[1]) if len(parts) >= 2 else -1
        return status_code, body
    except Exception as exc:
        return -1, str(exc)
    finally:
        sock.close()


# ---------------------------------------------------------------------------
# Server setup
# ---------------------------------------------------------------------------

async def start_server() -> MtConnectServer:
    """Create and start the ProtoForge MTConnect server with a test device."""
    server = MtConnectServer()

    config = DeviceConfig(
        id="test-mtconnect",
        name="Test MTConnect Device",
        protocol="mtconnect",
        points=[
            PointConfig(name="x_pos", address="0", data_type="float64",
                        access="rw", fixed_value=100.0),
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
    """Execute all MTConnect test cases. Returns list of (name, passed, detail)."""
    results: list[tuple[str, bool, str]] = []

    # ---- Test 1: GET /probe ----
    try:
        status, body = http_get("/probe")
        if status != 200:
            results.append(("GET /probe - HTTP status", False, f"expected 200, got {status}"))
        else:
            try:
                root = ET.fromstring(body)
                ns = {"mt": "urn:mtconnect.org:MTConnectDevices:1.3"}
                devices = root.findall(".//mt:Device", ns)
                if len(devices) > 0:
                    device_names = [d.get("name", "") for d in devices]
                    results.append(("GET /probe", True,
                                    f"status={status}, devices={device_names}"))
                else:
                    results.append(("GET /probe", False,
                                    f"status={status} but no Device elements found"))
            except ET.ParseError as e:
                results.append(("GET /probe", False, f"XML parse error: {e}"))
    except Exception as exc:
        results.append(("GET /probe", False, str(exc)))

    # ---- Test 2: GET /current ----
    try:
        status, body = http_get("/current")
        if status != 200:
            results.append(("GET /current - HTTP status", False, f"expected 200, got {status}"))
        else:
            try:
                root = ET.fromstring(body)
                ns = {"mt": "urn:mtconnect.org:MTConnectStreams:1.3"}
                streams = root.findall(".//mt:DeviceStream", ns)
                if len(streams) > 0:
                    # Check for Sample elements with x_pos
                    samples = root.findall(".//mt:Sample", ns)
                    x_pos_found = any(
                        s.get("dataItemId") == "x_pos" or s.get("name") == "x_pos"
                        for s in samples
                    )
                    results.append(("GET /current", True,
                                    f"status={status}, streams={len(streams)}, "
                                    f"x_pos_found={x_pos_found}"))
                else:
                    results.append(("GET /current", False,
                                    f"status={status} but no DeviceStream elements"))
            except ET.ParseError as e:
                results.append(("GET /current", False, f"XML parse error: {e}"))
    except Exception as exc:
        results.append(("GET /current", False, str(exc)))

    # ---- Test 3: GET /sample ----
    try:
        status, body = http_get("/sample")
        if status != 200:
            results.append(("GET /sample - HTTP status", False, f"expected 200, got {status}"))
        else:
            try:
                root = ET.fromstring(body)
                ns = {"mt": "urn:mtconnect.org:MTConnectStreams:1.3"}
                header = root.find("mt:Header", ns)
                first_seq = header.get("firstSequence", "") if header is not None else ""
                last_seq = header.get("lastSequence", "") if header is not None else ""
                next_seq = header.get("nextSequence", "") if header is not None else ""
                results.append(("GET /sample", True,
                                f"status={status}, firstSeq={first_seq}, "
                                f"lastSeq={last_seq}, nextSeq={next_seq}"))
            except ET.ParseError as e:
                results.append(("GET /sample", False, f"XML parse error: {e}"))
    except Exception as exc:
        results.append(("GET /sample", False, str(exc)))

    # ---- Test 4: Verify /current contains x_pos value ----
    try:
        status, body = http_get("/current")
        if status != 200:
            results.append(("GET /current - x_pos value check", False,
                            f"HTTP {status}"))
        else:
            root = ET.fromstring(body)
            ns = {"mt": "urn:mtconnect.org:MTConnectStreams:1.3"}
            samples = root.findall(".//mt:Sample", ns)
            x_pos_value = None
            for s in samples:
                if s.get("dataItemId") == "x_pos" or s.get("name") == "x_pos":
                    x_pos_value = s.text
                    break
            if x_pos_value is not None:
                results.append(("GET /current - x_pos value", True,
                                f"x_pos={x_pos_value}"))
            else:
                results.append(("GET /current - x_pos value", False,
                                "x_pos Sample element not found in response"))
    except Exception as exc:
        results.append(("GET /current - x_pos value", False, str(exc)))

    # ---- Test 5: GET /probe contains DataItem for x_pos ----
    try:
        status, body = http_get("/probe")
        if status != 200:
            results.append(("GET /probe - DataItem check", False,
                            f"HTTP {status}"))
        else:
            root = ET.fromstring(body)
            ns = {"mt": "urn:mtconnect.org:MTConnectDevices:1.3"}
            data_items = root.findall(".//mt:DataItem", ns)
            x_pos_item = None
            for di in data_items:
                if di.get("name") == "x_pos":
                    x_pos_item = di
                    break
            if x_pos_item is not None:
                di_type = x_pos_item.get("type", "")
                di_category = x_pos_item.get("category", "")
                results.append(("GET /probe - DataItem x_pos", True,
                                f"type={di_type}, category={di_category}"))
            else:
                results.append(("GET /probe - DataItem x_pos", False,
                                "DataItem with name=x_pos not found"))
    except Exception as exc:
        results.append(("GET /probe - DataItem x_pos", False, str(exc)))

    return results


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main() -> None:
    print("=" * 64)
    print("ProtoForge MTConnect Diagnostic Test")
    print("=" * 64)

    # Start server
    print(f"\nStarting MTConnect server on {HOST}:{PORT} ...")
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
