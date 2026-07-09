"""Diagnostic test script for ProtoForge MC Protocol (Mitsubishi SLMP 3E) server.

Starts the MC server locally and tests raw SLMP 3E binary frame operations:
  - Batch Read Word  (0x0401/0x0000)
  - Batch Write Word (0x1401/0x0000)
  - Batch Read back & verify
  - Self-diagnosis    (0x0001/0x0000)

Usage:  python scripts/diag_mc.py
"""

import asyncio
import socket
import struct
import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from protoforge.protocols.mc.server import McServer
from protoforge.models.device import DeviceConfig, PointConfig

HOST = "127.0.0.1"
PORT = 5000
SOCKET_TIMEOUT = 5

DEVICE_CODE_D = 0x44


def build_slmp3e_header(data_length, command, subcommand):
    """Build the fixed SLMP 3E binary header (bytes 0..14).

    Layout:
      0-1  Subheader       0x0054 (LE)
      2    Network No      0x00
      3    PC No           0xFF
      4-5  Target Module   0x03FF (LE)
      6    Target Station  0x00
      7-8  Data Length     (LE) - length of everything after this field
      9-10 CPU Monitor     0x0010 (LE)
      11-12 Command        (LE)
      13-14 Subcommand     (LE)
    """
    return struct.pack("<H", 0x0054) + \
           bytes([0x00, 0xFF]) + \
           struct.pack("<H", 0x03FF) + \
           bytes([0x00]) + \
           struct.pack("<H", data_length) + \
           struct.pack("<H", 0x0010) + \
           struct.pack("<H", command) + \
           struct.pack("<H", subcommand)


def build_batch_read_request(start_addr, device_code, word_count):
    """Batch Read Word (command 0x0401, subcommand 0x0000).

    Request data after header: StartAddr(2 LE) + DeviceCode(1) + WordCount(2 LE)
    """
    payload = struct.pack("<H", start_addr) + bytes([device_code]) + struct.pack("<H", word_count)
    data_length = 2 + len(payload)  # timer(2) + payload
    return build_slmp3e_header(data_length, 0x0401, 0x0000) + payload


def build_batch_write_request(start_addr, device_code, word_count, values):
    """Batch Write Word (command 0x1401, subcommand 0x0000).

    Request data after header:
      StartAddr(2 LE) + DeviceCode(1) + WordCount(2 LE) + Data(word_count*2 bytes)
    """
    data = b"".join(struct.pack("<H", v) for v in values)
    payload = struct.pack("<H", start_addr) + bytes([device_code]) + struct.pack("<H", word_count) + data
    data_length = 2 + len(payload)
    return build_slmp3e_header(data_length, 0x1401, 0x0000) + payload


def build_self_test_request():
    """Self-diagnosis (command 0x0001, subcommand 0x0000). No extra data."""
    data_length = 2  # only CPU monitor timer
    return build_slmp3e_header(data_length, 0x0001, 0x0000)


def send_recv(frame, timeout=SOCKET_TIMEOUT):
    """Send a SLMP frame and return the raw response."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect((HOST, PORT))
        sock.sendall(frame)
        # Read header (9 bytes: subheader(2)+net(1)+pc(1)+io(2)+station(1)+datalen(2))
        header = b""
        while len(header) < 9:
            chunk = sock.recv(9 - len(header))
            if not chunk:
                raise ConnectionError("Connection closed while reading header")
            header += chunk
        data_len = struct.unpack("<H", header[7:9])[0]
        remaining = b""
        while len(remaining) < data_len:
            chunk = sock.recv(data_len - len(remaining))
            if not chunk:
                raise ConnectionError("Connection closed while reading data")
            remaining += chunk
        return header + remaining
    finally:
        sock.close()


def parse_completion_code(resp):
    """Extract the 2-byte completion code from a SLMP 3E binary response."""
    if len(resp) < 11:
        return 0xFFFF
    return struct.unpack("<H", resp[9:11])[0]


async def start_server():
    """Create and start the MC server with a test device."""
    server = McServer()
    await server.start({"host": HOST, "port": PORT})
    config = DeviceConfig(
        id="test-mc",
        name="Test MC Device",
        protocol="mc",
        points=[
            PointConfig(name="temperature", address="D0", data_type="float32",
                        access="rw", fixed_value=25.0),
            PointConfig(name="pressure", address="D2", data_type="int16",
                        access="rw", fixed_value=100),
        ],
    )
    await server.create_device(config)
    return server


def test_batch_read():
    """Test 1: Batch Read Word - read D0-D9 (10 words)."""
    print("\n[Test 1] Batch Read Word (0x0401) - D0..D9")
    try:
        req = build_batch_read_request(start_addr=0, device_code=DEVICE_CODE_D, word_count=10)
        resp = send_recv(req)
        cc = parse_completion_code(resp)
        if cc != 0x0000:
            print(f"  Completion code: 0x{cc:04X}")
            print(f"  FAIL - expected 0x0000")
            return False
        data = resp[11:]
        words = [struct.unpack("<H", data[i:i+2])[0] for i in range(0, len(data), 2)]
        print(f"  Read {len(words)} words: {words}")
        print(f"  PASS")
        return True
    except Exception as e:
        print(f"  FAIL - {e}")
        return False


def test_batch_write():
    """Test 2: Batch Write Word - write D0=1234, D1=5678."""
    print("\n[Test 2] Batch Write Word (0x1401) - D0=1234, D1=5678")
    try:
        req = build_batch_write_request(
            start_addr=0, device_code=DEVICE_CODE_D,
            word_count=2, values=[1234, 5678],
        )
        resp = send_recv(req)
        cc = parse_completion_code(resp)
        if cc != 0x0000:
            print(f"  Completion code: 0x{cc:04X}")
            print(f"  FAIL - expected 0x0000")
            return False
        print(f"  Write completion code: 0x{cc:04X}")
        print(f"  PASS")
        return True
    except Exception as e:
        print(f"  FAIL - {e}")
        return False


def test_batch_read_verify():
    """Test 3: Batch Read back and verify D0=1234, D1=5678."""
    print("\n[Test 3] Batch Read back & verify - D0==1234, D1==5678")
    try:
        req = build_batch_read_request(start_addr=0, device_code=DEVICE_CODE_D, word_count=2)
        resp = send_recv(req)
        cc = parse_completion_code(resp)
        if cc != 0x0000:
            print(f"  Completion code: 0x{cc:04X}")
            print(f"  FAIL - expected 0x0000")
            return False
        data = resp[11:]
        d0 = struct.unpack("<H", data[0:2])[0]
        d1 = struct.unpack("<H", data[2:4])[0]
        print(f"  D0={d0}, D1={d1}")
        ok = True
        if d0 != 1234:
            print(f"  D0 mismatch: expected 1234, got {d0}")
            ok = False
        if d1 != 5678:
            print(f"  D1 mismatch: expected 5678, got {d1}")
            ok = False
        if ok:
            print(f"  PASS")
        else:
            print(f"  FAIL")
        return ok
    except Exception as e:
        print(f"  FAIL - {e}")
        return False


def test_self_diagnosis():
    """Test 4: Self-diagnosis (command 0x0001)."""
    print("\n[Test 4] Self-diagnosis (0x0001)")
    try:
        req = build_self_test_request()
        resp = send_recv(req)
        cc = parse_completion_code(resp)
        if cc != 0x0000:
            print(f"  Completion code: 0x{cc:04X}")
            print(f"  FAIL - expected 0x0000")
            return False
        print(f"  Self-diagnosis completion code: 0x{cc:04X}")
        print(f"  PASS")
        return True
    except Exception as e:
        print(f"  FAIL - {e}")
        return False


async def main():
    print("=" * 60)
    print("  ProtoForge MC Protocol (SLMP 3E) Diagnostic Test")
    print(f"  Target: {HOST}:{PORT}")
    print("=" * 60)

    print("\n[Setup] Starting MC server ...")
    try:
        server = await start_server()
    except Exception as e:
        print(f"  FAIL - could not start server: {e}")
        return

    await asyncio.sleep(0.3)

    results = []
    results.append(("Batch Read Word", test_batch_read()))
    results.append(("Batch Write Word", test_batch_write()))
    results.append(("Batch Read & Verify", test_batch_read_verify()))
    results.append(("Self-diagnosis", test_self_diagnosis()))

    print("\n[Teardown] Stopping MC server ...")
    await server.stop()

    print("\n" + "=" * 60)
    print("  Summary")
    print("=" * 60)
    passed = 0
    for name, ok in results:
        status = "PASS" if ok else "FAIL"
        print(f"  {status}  {name}")
        if ok:
            passed += 1
    print(f"\n  {passed}/{len(results)} tests passed")
    if passed == len(results):
        print("  All tests passed!")
    else:
        print("  Some tests failed.")


if __name__ == "__main__":
    asyncio.run(main())
