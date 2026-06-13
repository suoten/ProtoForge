"""
ProtoForge MQTT Diagnostic Test Script

Tests the MQTT server (amqtt broker) using raw MQTT protocol frames.
Validates Connect, Subscribe, Publish, and Receive operations.

Usage:
    python scripts/diag_mqtt.py
"""

import sys
import os
import socket
import struct
import asyncio
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from protoforge.protocols.mqtt.server import MqttBroker
from protoforge.models.device import DeviceConfig, PointConfig

HOST = "127.0.0.1"
PORT = 1883
SOCKET_TIMEOUT = 5


# ---------------------------------------------------------------------------
# MQTT protocol helpers (minimal implementation for testing)
# ---------------------------------------------------------------------------

def _encode_utf8(s: str) -> bytes:
    """Encode a string as MQTT UTF-8 encoded string (length prefix + bytes)."""
    encoded = s.encode("utf-8")
    return struct.pack(">H", len(encoded)) + encoded


def _encode_remaining_length(length: int) -> bytes:
    """Encode MQTT remaining length field."""
    result = bytearray()
    while True:
        byte = length % 128
        length = length // 128
        if length > 0:
            byte |= 0x80
        result.append(byte)
        if length == 0:
            break
    return bytes(result)


def build_connect(client_id: str = "diag_test", keepalive: int = 60) -> bytes:
    """Build an MQTT CONNECT packet."""
    # Variable header
    var_header = _encode_utf8("MQTT")  # Protocol name
    var_header += struct.pack("B", 4)   # Protocol level (MQTT 3.1.1)
    var_header += struct.pack("B", 0x02)  # Connect flags: Clean Session
    var_header += struct.pack(">H", keepalive)

    # Payload
    payload = _encode_utf8(client_id)

    # Fixed header
    remaining = var_header + payload
    fixed_header = struct.pack("B", 0x10) + _encode_remaining_length(len(remaining))
    return fixed_header + remaining


def build_subscribe(packet_id: int, topic: str, qos: int = 0) -> bytes:
    """Build an MQTT SUBSCRIBE packet."""
    var_header = struct.pack(">H", packet_id)
    payload = _encode_utf8(topic) + struct.pack("B", qos)
    remaining = var_header + payload
    fixed_header = struct.pack("B", 0x82) + _encode_remaining_length(len(remaining))
    return fixed_header + remaining


def build_publish(topic: str, payload: str, qos: int = 0, retain: bool = False,
                  packet_id: int = 0) -> bytes:
    """Build an MQTT PUBLISH packet."""
    topic_encoded = _encode_utf8(topic)
    remaining = topic_encoded

    if qos > 0:
        remaining += struct.pack(">H", packet_id)

    remaining += payload.encode("utf-8")

    first_byte = 0x30 | (qos << 1) | (0x01 if retain else 0x00)
    fixed_header = struct.pack("B", first_byte) + _encode_remaining_length(len(remaining))
    return fixed_header + remaining


def build_pingreq() -> bytes:
    """Build an MQTT PINGREQ packet."""
    return bytes([0xC0, 0x00])


def build_disconnect() -> bytes:
    """Build an MQTT DISCONNECT packet."""
    return bytes([0xE0, 0x00])


def parse_connack(data: bytes) -> tuple[int, int]:
    """Parse CONNACK response. Returns (session_present, return_code)."""
    if len(data) < 4:
        return -1, -1
    # Fixed header: 0x20, remaining_length
    # Variable header: acknowledge_flags, return_code
    return data[2] & 0x01, data[3]


def parse_suback(data: bytes) -> tuple[int, int]:
    """Parse SUBACK response. Returns (packet_id, granted_qos)."""
    if len(data) < 5:
        return -1, -1
    packet_id = struct.unpack(">H", data[2:4])[0]
    granted_qos = data[4]
    return packet_id, granted_qos


def recv_mqtt_packet(sock: socket.socket) -> bytes:
    """Receive a complete MQTT packet from the socket."""
    # Read first byte (packet type + flags)
    first_byte = sock.recv(1)
    if not first_byte:
        return b""

    # Decode remaining length
    remaining_length = 0
    multiplier = 1
    while True:
        byte = sock.recv(1)
        if not byte:
            return b""
        byte_val = byte[0]
        remaining_length += (byte_val & 0x7F) * multiplier
        multiplier *= 128
        if not (byte_val & 0x80):
            break

    # Read remaining data
    data = first_byte
    data += bytes([byte_val])  # last byte of remaining length
    # We need to reconstruct the full remaining length bytes for parsing
    # Re-read: let's just read the payload
    payload = b""
    while len(payload) < remaining_length:
        chunk = sock.recv(remaining_length - len(payload))
        if not chunk:
            break
        payload += chunk

    return first_byte + data[1:] + payload


# ---------------------------------------------------------------------------
# Server setup
# ---------------------------------------------------------------------------

async def start_server() -> MqttBroker:
    """Create and start the ProtoForge MQTT broker with a test device."""
    server = MqttBroker()

    config = DeviceConfig(
        id="test-mqtt",
        name="Test MQTT Device",
        protocol="mqtt",
        points=[
            PointConfig(name="temperature", address="0", data_type="float32",
                        access="rw", fixed_value=25.0),
        ],
    )

    await server.create_device(config)
    await server.start({"host": HOST, "port": PORT, "publish_interval": 2})

    # Wait for the server to start accepting connections.
    for attempt in range(30):
        await asyncio.sleep(0.2)
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        probe.settimeout(0.5)
        try:
            probe.connect((HOST, PORT))
            probe.close()
            break
        except (ConnectionRefusedError, OSError):
            probe.close()
    else:
        raise RuntimeError("Server did not start listening within 6 seconds")

    return server


# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------

def run_tests() -> list[tuple[str, bool, str]]:
    """Execute all MQTT test cases. Returns list of (name, passed, detail)."""
    results: list[tuple[str, bool, str]] = []

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(SOCKET_TIMEOUT)

    # ---- Test 1: Connect ----
    try:
        sock.connect((HOST, PORT))
        sock.sendall(build_connect("diag_mqtt_client"))
        data = sock.recv(1024)
        session_present, return_code = parse_connack(data)
        if return_code == 0:
            results.append(("MQTT Connect", True,
                            f"session_present={session_present}, "
                            f"return_code={return_code}"))
        else:
            results.append(("MQTT Connect", False,
                            f"return_code={return_code} (expected 0)"))
    except Exception as exc:
        results.append(("MQTT Connect", False, str(exc)))
        return results

    # ---- Test 2: Subscribe ----
    try:
        topic = "protoforge/test-mqtt/temperature"
        sock.sendall(build_subscribe(1, topic, qos=0))
        data = sock.recv(1024)
        packet_id, granted_qos = parse_suback(data)
        if packet_id == 1 and granted_qos <= 2:
            results.append(("MQTT Subscribe", True,
                            f"topic={topic}, packet_id={packet_id}, "
                            f"granted_qos={granted_qos}"))
        else:
            results.append(("MQTT Subscribe", False,
                            f"packet_id={packet_id}, granted_qos={granted_qos}"))
    except Exception as exc:
        results.append(("MQTT Subscribe", False, str(exc)))

    # ---- Test 3: Publish ----
    try:
        pub_topic = "protoforge/test-mqtt/temperature"
        pub_payload = json.dumps({
            "device_id": "test-mqtt",
            "point": "temperature",
            "value": 99.9,
            "timestamp": 0,
            "unit": "",
        })
        sock.sendall(build_publish(pub_topic, pub_payload, qos=0))
        # No ACK expected for QoS 0, just check no error
        results.append(("MQTT Publish", True,
                        f"topic={pub_topic}, payload_len={len(pub_payload)}"))
    except Exception as exc:
        results.append(("MQTT Publish", False, str(exc)))

    # ---- Test 4: Receive (wait for broker to publish) ----
    try:
        # The broker publishes device values periodically (publish_interval=2s).
        # We wait for an incoming PUBLISH packet.
        sock.settimeout(6)
        received = False
        topic_received = ""
        try:
            for _ in range(10):
                data = sock.recv(4096)
                if not data:
                    break
                # Check if any byte is a PUBLISH packet (0x30-0x3F)
                for i in range(len(data)):
                    if 0x30 <= data[i] <= 0x3F:
                        received = True
                        # Try to extract topic from the PUBLISH
                        try:
                            # Skip fixed header (1 byte + remaining length)
                            j = i + 1
                            while j < len(data) and data[j] & 0x80:
                                j += 1
                            j += 1  # past remaining length
                            if j + 2 <= len(data):
                                topic_len = struct.unpack(">H", data[j:j+2])[0]
                                if j + 2 + topic_len <= len(data):
                                    topic_received = data[j+2:j+2+topic_len].decode("utf-8", errors="replace")
                        except (struct.error, IndexError):
                            pass
                        break
                if received:
                    break
        except socket.timeout:
            pass

        if received:
            results.append(("MQTT Receive", True,
                            f"topic={topic_received or '(parsed from stream)'}"))
        else:
            results.append(("MQTT Receive", False,
                            "No PUBLISH packet received within timeout"))
    except Exception as exc:
        results.append(("MQTT Receive", False, str(exc)))

    # ---- Test 5: Disconnect ----
    try:
        sock.sendall(build_disconnect())
        results.append(("MQTT Disconnect", True, "DISCONNECT sent"))
    except Exception as exc:
        results.append(("MQTT Disconnect", False, str(exc)))
    finally:
        sock.close()

    return results


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main() -> None:
    print("=" * 64)
    print("ProtoForge MQTT Diagnostic Test")
    print("=" * 64)

    # Start server
    print(f"\nStarting MQTT broker on {HOST}:{PORT} ...")
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
