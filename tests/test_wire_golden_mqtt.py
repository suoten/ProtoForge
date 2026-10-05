"""MQTT broker wire-level golden tests (MQTT 3.1.1 raw packets).

The broker itself is amqtt; ProtoForge owns the configuration, the
topic derivation (`{prefix}/{device_id}/{point}`) and the JSON payload
shape — these goldens gate that contract on the wire:
  CONNECT -> CONNACK(0)
  SUBSCRIBE -> SUBACK(0)
  publish loop -> PUBLISH with topic/payload per contract
  PINGREQ -> PINGRESP
"""

import asyncio
import json
import struct

import pytest

from protoforge.models.device import DeviceConfig, PointConfig
from tests.wire_golden_harness import free_tcp_port

HOST = "127.0.0.1"

try:
    import amqtt  # noqa: F401
    AMQTT_OK = True
except ImportError:
    AMQTT_OK = False


def mqtt_encode_remaining_len(n: int) -> bytes:
    out = bytearray()
    while True:
        byte = n % 128
        n //= 128
        if n > 0:
            byte |= 0x80
        out.append(byte)
        if n == 0:
            return bytes(out)


def mqtt_string(s: str) -> bytes:
    raw = s.encode("utf-8")
    return struct.pack(">H", len(raw)) + raw


def connect_packet(client_id: str) -> bytes:
    payload = mqtt_string(client_id)
    var_header = mqtt_string("MQTT") + bytes([0x04, 0x02]) + struct.pack(">H", 60)
    body = var_header + payload
    return bytes([0x10]) + mqtt_encode_remaining_len(len(body)) + body


def subscribe_packet(pid: int, topic: str) -> bytes:
    body = struct.pack(">H", pid) + mqtt_string(topic) + bytes([0x00])
    return bytes([0x82]) + mqtt_encode_remaining_len(len(body)) + body


async def read_packet(reader, timeout: float = 5.0) -> tuple[int, bytes]:
    first = await asyncio.wait_for(reader.readexactly(1), timeout=timeout)
    multiplier, value = 1, 0
    while True:
        byte = (await asyncio.wait_for(reader.readexactly(1), timeout=timeout))[0]
        value += (byte & 0x7F) * multiplier
        multiplier *= 128
        if not byte & 0x80:
            break
    body = await asyncio.wait_for(reader.readexactly(value), timeout=timeout)
    return first[0], body


async def start_broker():
    from protoforge.protocols.mqtt.server import MqttBroker
    server = MqttBroker()
    port = free_tcp_port()
    await server.start({"host": HOST, "port": port, "publish_interval": 1})
    await asyncio.sleep(0.2)
    await server.create_device(DeviceConfig(
        id="dev1",
        name="MQTT Golden",
        protocol="mqtt",
        points=[PointConfig(name="temp", address="temp", data_type="float32")],
    ))
    await server.write_point("dev1", "temp", 23.5)
    return server, port


async def teardown(server, writer=None):
    if writer is not None:
        writer.close()
        try:
            await asyncio.wait_for(writer.wait_closed(), timeout=3)
        except (asyncio.TimeoutError, ConnectionError):
            pass
    await asyncio.wait_for(server.stop(), timeout=10)


@pytest.mark.skipif(not AMQTT_OK, reason="amqtt not installed")
@pytest.mark.asyncio
async def test_connect_ping_publish_contract():
    """CONNECT/CONNACK + PING/PINGRESP + subscription receives the point topic."""
    server, port = await start_broker()
    writer = None
    try:
        reader, writer = await asyncio.open_connection(HOST, port)
        writer.write(connect_packet("golden-client"))
        await writer.drain()
        ptype, body = await read_packet(reader)
        assert (ptype, body) == (0x20, b"\x00\x00"), f"CONNACK mismatch: {ptype:#x} {body.hex(' ')}"

        writer.write(subscribe_packet(1, "protoforge/dev1/#"))
        await writer.drain()
        ptype, body = await read_packet(reader)
        assert ptype == 0x90, f"expected SUBACK, got {ptype:#x}"
        assert body == b"\x00\x01\x00", f"SUBACK mismatch: {body.hex(' ')}"

        # publish loop (interval=1s) -> PUBLISH on the contract topic
        got = None
        for _ in range(15):
            try:
                ptype, body = await read_packet(reader, timeout=2)
            except asyncio.TimeoutError:
                continue
            if ptype & 0xF0 == 0x30:  # PUBLISH (QoS0)
                topic_len = struct.unpack(">H", body[:2])[0]
                topic = body[2:2 + topic_len].decode()
                payload = json.loads(body[2 + topic_len:].decode())
                got = (topic, payload)
                break
        assert got is not None, "no PUBLISH received"
        topic, payload = got
        assert topic == "protoforge/dev1/temp", f"topic contract broken: {topic}"
        assert payload["device_id"] == "dev1" and payload["point"] == "temp"
        assert payload["value"] == pytest.approx(23.5) and "timestamp" in payload and "unit" in payload

        writer.write(b"\xc0\x00")  # PINGREQ
        await writer.drain()
        ptype, body = await read_packet(reader)
        assert (ptype, body) == (0xD0, b""), "PINGRESP mismatch"
    finally:
        await teardown(server, writer)
