"""
ProtoForge GB28181 SIP Diagnostic Test Script

Tests the GB28181 SIP server using raw UDP SIP messages.
Validates REGISTER, 401 challenge response, and authenticated REGISTER flow.

Usage:
    python scripts/diag_gb28181.py
"""

import sys
import os
import socket
import re
import asyncio
import hashlib
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from protoforge.protocols.gb28181.server import GB28181Server
from protoforge.models.device import DeviceConfig, PointConfig

HOST = "127.0.0.1"
PORT = 5060
SOCKET_TIMEOUT = 5

# GB28181 test parameters
SERVER_ID = "34020000002000000001"
DEVICE_ID = "34020000001320000001"
DEVICE_NAME = "Test-GB28181-Camera"
REALM = "gb28181"
USERNAME = DEVICE_ID
PASSWORD = "test123"


# ---------------------------------------------------------------------------
# SIP message helpers
# ---------------------------------------------------------------------------

def build_register(server_id: str, device_id: str, host: str, port: int,
                   call_id: str = "", expires: int = 3600) -> str:
    """Build a SIP REGISTER message (without auth)."""
    if not call_id:
        call_id = uuid.uuid4().hex[:16]
    branch = f"z9hG4bK{uuid.uuid4().hex[:12]}"
    tag = uuid.uuid4().hex[:8]

    return (
        f"REGISTER sip:{server_id} SIP/2.0\r\n"
        f"Via: SIP/2.0/UDP {host}:{port};branch={branch};rport\r\n"
        f"From: <sip:{device_id}@{host}>;tag={tag}\r\n"
        f"To: <sip:{device_id}@{host}>\r\n"
        f"Call-ID: {call_id}@{host}\r\n"
        f"CSeq: 1 REGISTER\r\n"
        f"Contact: <sip:{device_id}@{host}:{port}>\r\n"
        f"Max-Forwards: 70\r\n"
        f"User-Agent: ProtoForge-Diag/1.0\r\n"
        f"Expires: {expires}\r\n"
        f"Content-Length: 0\r\n\r\n"
    )


def build_register_with_auth(server_id: str, device_id: str, host: str, port: int,
                              call_id: str, nonce: str, realm: str,
                              username: str, password: str) -> str:
    """Build a SIP REGISTER message with Digest authentication."""
    branch = f"z9hG4bK{uuid.uuid4().hex[:12]}"
    tag = uuid.uuid4().hex[:8]

    # Digest auth calculation
    ha1 = hashlib.md5(f"{username}:{realm}:{password}".encode()).hexdigest()
    ha2 = hashlib.md5(f"REGISTER:sip:{server_id}".encode()).hexdigest()
    response = hashlib.md5(f"{ha1}:{nonce}:{ha2}".encode()).hexdigest()

    return (
        f"REGISTER sip:{server_id} SIP/2.0\r\n"
        f"Via: SIP/2.0/UDP {host}:{port};branch={branch};rport\r\n"
        f"From: <sip:{device_id}@{host}>;tag={tag}\r\n"
        f"To: <sip:{device_id}@{host}>\r\n"
        f"Call-ID: {call_id}@{host}\r\n"
        f"CSeq: 2 REGISTER\r\n"
        f"Contact: <sip:{device_id}@{host}:{port}>\r\n"
        f"Authorization: Digest username=\"{username}\", realm=\"{realm}\", "
        f"nonce=\"{nonce}\", uri=\"sip:{server_id}\", response=\"{response}\"\r\n"
        f"Max-Forwards: 70\r\n"
        f"User-Agent: ProtoForge-Diag/1.0\r\n"
        f"Expires: 3600\r\n"
        f"Content-Length: 0\r\n\r\n"
    )


def parse_sip_response(data: bytes) -> tuple[int, str, dict]:
    """Parse a SIP response. Returns (status_code, status_text, headers_dict)."""
    try:
        message = data.decode("utf-8", errors="replace")
    except Exception:
        return -1, "", {}

    lines = message.split("\r\n")
    if not lines:
        return -1, "", {}

    # Parse status line: SIP/2.0 <code> <text>
    parts = lines[0].split(" ", 2)
    if len(parts) < 2 or parts[0] != "SIP/2.0":
        return -1, "", {}

    status_code = int(parts[1])
    status_text = parts[2] if len(parts) >= 3 else ""

    headers = {}
    for line in lines[1:]:
        if ":" in line:
            key, val = line.split(":", 1)
            headers[key.strip().lower()] = val.strip()

    return status_code, status_text, headers


# ---------------------------------------------------------------------------
# Server setup
# ---------------------------------------------------------------------------

async def start_server() -> GB28181Server:
    """Create and start the ProtoForge GB28181 server with a test device."""
    server = GB28181Server()

    await server.start({"host": HOST, "port": PORT, "server_id": SERVER_ID})

    config = DeviceConfig(
        id="test-gb28181",
        name=DEVICE_NAME,
        protocol="gb28181",
        points=[
            PointConfig(name="video1", address="0", data_type="string",
                        access="rw", fixed_value="stream1"),
        ],
    )

    # Create device with protocol config for GB28181
    # Note: We don't set sip_server_addr because the device doesn't need to
    # register outward; we're testing the server's ability to handle incoming
    # SIP messages.
    await server.create_device(config)

    # Wait for the server to start
    await asyncio.sleep(0.5)

    return server


# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------

def run_tests() -> list[tuple[str, bool, str]]:
    """Execute all GB28181 test cases. Returns list of (name, passed, detail)."""
    results: list[tuple[str, bool, str]] = []

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(SOCKET_TIMEOUT)
    server_addr = (HOST, PORT)

    # ---- Test 1: Send REGISTER (no auth) and receive 401 challenge ----
    call_id = uuid.uuid4().hex[:16]
    try:
        register_msg = build_register(SERVER_ID, DEVICE_ID, HOST, PORT, call_id)
        sock.sendto(register_msg.encode("utf-8"), server_addr)

        data, addr = sock.recvfrom(4096)
        status_code, status_text, headers = parse_sip_response(data)

        if status_code == 401:
            # Extract nonce and realm from WWW-Authenticate or Authorization header
            auth_header = headers.get("www-authenticate", "") or headers.get("authorization", "")
            nonce_match = re.search(r'nonce="([^"]+)"', auth_header)
            realm_match = re.search(r'realm="([^"]+)"', auth_header)
            nonce = nonce_match.group(1) if nonce_match else ""
            realm = realm_match.group(1) if realm_match else REALM

            results.append(("REGISTER -> 401 Challenge", True,
                            f"status={status_code}, nonce={nonce[:16]}..., "
                            f"realm={realm}"))

            # ---- Test 2: Send REGISTER with auth ----
            if nonce:
                try:
                    auth_register = build_register_with_auth(
                        SERVER_ID, DEVICE_ID, HOST, PORT,
                        call_id, nonce, realm, USERNAME, PASSWORD
                    )
                    sock.sendto(auth_register.encode("utf-8"), server_addr)

                    data2, addr2 = sock.recvfrom(4096)
                    status_code2, status_text2, headers2 = parse_sip_response(data2)

                    if status_code2 == 200:
                        results.append(("REGISTER with Auth -> 200 OK", True,
                                        f"status={status_code2}"))
                    else:
                        results.append(("REGISTER with Auth -> 200 OK", False,
                                        f"expected 200, got {status_code2} "
                                        f"({status_text2})"))
                except socket.timeout:
                    results.append(("REGISTER with Auth -> 200 OK", False,
                                    "Timeout waiting for 200 OK"))
                except Exception as exc:
                    results.append(("REGISTER with Auth -> 200 OK", False, str(exc)))
            else:
                results.append(("REGISTER with Auth -> 200 OK", False,
                                "No nonce extracted from 401"))
        else:
            results.append(("REGISTER -> 401 Challenge", False,
                            f"expected 401, got {status_code} ({status_text})"))
    except socket.timeout:
        results.append(("REGISTER -> 401 Challenge", False,
                        "Timeout waiting for 401 response"))
    except Exception as exc:
        results.append(("REGISTER -> 401 Challenge", False, str(exc)))

    # ---- Test 3: Send MESSAGE (Catalog query) ----
    try:
        sn = str(int(asyncio.get_event_loop().time() * 1000) % 100000)
        xml_body = (
            f'<?xml version="1.0"?>\r\n'
            f'<Query>\r\n'
            f'<CmdType>Catalog</CmdType>\r\n'
            f'<SN>{sn}</SN>\r\n'
            f'<DeviceID>{DEVICE_ID}</DeviceID>\r\n'
            f'</Query>'
        )
        branch = f"z9hG4bK{uuid.uuid4().hex[:12]}"
        tag = uuid.uuid4().hex[:8]
        msg_call_id = uuid.uuid4().hex[:16]
        local_host = HOST
        local_port = PORT + 1  # Use a different port for this message

        sip_message = (
            f"MESSAGE sip:{SERVER_ID}@{local_host} SIP/2.0\r\n"
            f"Via: SIP/2.0/UDP {local_host}:{local_port};rport;branch={branch}\r\n"
            f"From: <sip:{DEVICE_ID}@{local_host}>;tag={tag}\r\n"
            f"To: <sip:{SERVER_ID}@{local_host}>\r\n"
            f"Call-ID: {msg_call_id}@{local_host}\r\n"
            f"CSeq: 1 MESSAGE\r\n"
            f"Content-Type: Application/MANSCDP+xml\r\n"
            f"Content-Length: {len(xml_body.encode('utf-8'))}\r\n\r\n"
            f"{xml_body}"
        )
        sock.sendto(sip_message.encode("utf-8"), server_addr)

        data3, addr3 = sock.recvfrom(4096)
        status_code3, status_text3, headers3 = parse_sip_response(data3)

        if status_code3 == 200:
            # Check if the response body contains Catalog
            body_start = data3.find(b"\r\n\r\n")
            body = data3[body_start + 4:].decode("utf-8", errors="replace") if body_start != -1 else ""
            has_catalog = "Catalog" in body
            results.append(("MESSAGE Catalog -> 200 OK", True,
                            f"status={status_code3}, has_catalog={has_catalog}"))
        else:
            results.append(("MESSAGE Catalog -> 200 OK", False,
                            f"expected 200, got {status_code3} ({status_text3})"))
    except socket.timeout:
        results.append(("MESSAGE Catalog -> 200 OK", False,
                        "Timeout waiting for Catalog response"))
    except Exception as exc:
        results.append(("MESSAGE Catalog -> 200 OK", False, str(exc)))

    # ---- Test 4: Send MESSAGE (Keepalive) ----
    try:
        sn2 = str(int(asyncio.get_event_loop().time() * 1000) % 100000 + 1)
        keepalive_body = (
            f'<?xml version="1.0"?>\r\n'
            f'<Notify>\r\n'
            f'<CmdType>Keepalive</CmdType>\r\n'
            f'<SN>{sn2}</SN>\r\n'
            f'<DeviceID>{DEVICE_ID}</DeviceID>\r\n'
            f'<Status>OK</Status>\r\n'
            f'</Notify>'
        )
        branch2 = f"z9hG4bK{uuid.uuid4().hex[:12]}"
        tag2 = uuid.uuid4().hex[:8]
        msg_call_id2 = uuid.uuid4().hex[:16]

        keepalive_msg = (
            f"MESSAGE sip:{SERVER_ID}@{HOST} SIP/2.0\r\n"
            f"Via: SIP/2.0/UDP {HOST}:{PORT + 2};rport;branch={branch2}\r\n"
            f"From: <sip:{DEVICE_ID}@{HOST}>;tag={tag2}\r\n"
            f"To: <sip:{SERVER_ID}@{HOST}>\r\n"
            f"Call-ID: {msg_call_id2}@{HOST}\r\n"
            f"CSeq: 2 MESSAGE\r\n"
            f"Content-Type: Application/MANSCDP+xml\r\n"
            f"Content-Length: {len(keepalive_body.encode('utf-8'))}\r\n\r\n"
            f"{keepalive_body}"
        )
        sock.sendto(keepalive_msg.encode("utf-8"), server_addr)

        data4, addr4 = sock.recvfrom(4096)
        status_code4, status_text4, _ = parse_sip_response(data4)

        if status_code4 == 200:
            results.append(("MESSAGE Keepalive -> 200 OK", True,
                            f"status={status_code4}"))
        else:
            results.append(("MESSAGE Keepalive -> 200 OK", False,
                            f"expected 200, got {status_code4} ({status_text4})"))
    except socket.timeout:
        results.append(("MESSAGE Keepalive -> 200 OK", False,
                        "Timeout waiting for Keepalive response"))
    except Exception as exc:
        results.append(("MESSAGE Keepalive -> 200 OK", False, str(exc)))

    # ---- Test 5: Verify server is still running ----
    try:
        # Send a simple REGISTER again to confirm server is responsive
        call_id5 = uuid.uuid4().hex[:16]
        register_msg5 = build_register(SERVER_ID, DEVICE_ID, HOST, PORT, call_id5)
        sock.sendto(register_msg5.encode("utf-8"), server_addr)

        data5, addr5 = sock.recvfrom(4096)
        status_code5, _, _ = parse_sip_response(data5)

        if status_code5 > 0:
            results.append(("Server responsiveness check", True,
                            f"status={status_code5}"))
        else:
            results.append(("Server responsiveness check", False,
                            "No valid SIP response received"))
    except socket.timeout:
        results.append(("Server responsiveness check", False,
                        "Timeout - server may have stopped"))
    except Exception as exc:
        results.append(("Server responsiveness check", False, str(exc)))
    finally:
        sock.close()

    return results


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main() -> None:
    print("=" * 64)
    print("ProtoForge GB28181 SIP Diagnostic Test")
    print("=" * 64)

    # Start server
    print(f"\nStarting GB28181 SIP server on {HOST}:{PORT} ...")
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
