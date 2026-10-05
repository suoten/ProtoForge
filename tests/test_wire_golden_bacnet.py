"""BACnet (UDP) wire-level golden tests per ASHRAE 135.

  BVLL: 0x81 + type + length(2 BE); 0x0B Original-Broadcast, 0x0A Unicast
  NPDU: 0x01 0x00
  Who-Is (unconfirmed 0x08) -> I-Am (0x00) with object id / max APDU /
  segmentation / vendor ID context tags
  ReadProperty (confirmed 0x0C) -> ComplexACK [0x30, inv, 0x0C, ...]
  WriteProperty (0x0F) -> SimpleACK [0x20, inv, 0x0F]
"""

import asyncio
import struct

import pytest

from protoforge.models.device import DeviceConfig, PointConfig
from protoforge.protocols.bacnet.server import BACnetServer
from tests.wire_golden_harness import free_udp_port

HOST = "127.0.0.1"


def obj_id(obj_type: int, instance: int) -> bytes:
    return struct.pack(">I", ((obj_type & 0x3FF) << 22) | (instance & 0x3FFFFF))


async def start_server():
    server = BACnetServer()
    port = free_udp_port()
    await server.start({"host": HOST, "port": port, "device_id_base": 100})
    await asyncio.sleep(0.1)
    await server.create_device(DeviceConfig(
        id="dev-bac",
        name="BACnet Golden",
        protocol="bacnet",
        points=[
            PointConfig(name="setpoint", address="setpoint", data_type="float32", access="rw"),
            PointConfig(name="switch", address="switch", data_type="bool", access="rw"),
        ],
        protocol_config={"device_id": 101},
    ))
    await server.write_point("dev-bac", "setpoint", 23.5)
    return server, port


async def teardown(server):
    await asyncio.wait_for(server.stop(), timeout=10)


class _UdpReceiver(asyncio.DatagramProtocol):
    def __init__(self, future: asyncio.Future):
        self.future = future

    def datagram_received(self, data: bytes, addr) -> None:
        if not self.future.done():
            self.future.set_result(data)


async def udp_exchange(port, payload: bytes) -> bytes:
    loop = asyncio.get_running_loop()
    response = loop.create_future()
    transport, _protocol = await loop.create_datagram_endpoint(
        lambda: _UdpReceiver(response), remote_addr=(HOST, port))
    transport.sendto(payload)
    try:
        return await asyncio.wait_for(response, timeout=5)
    finally:
        transport.close()


@pytest.mark.asyncio
async def test_who_is_i_am_exact():
    """Who-Is -> I-Am: BVLC 0x0A, device object 101, max APDU 1024, vendor 999."""
    server, port = await start_server()
    try:
        who_is = b"\x81\x0b\x00\x08" + b"\x01\x00" + b"\x10\x08"
        resp = await udp_exchange(port, who_is)
        expected_apdu = (b"\x10\x00"
                         + b"\xc4" + obj_id(8, 101)
                         + b"\x8a\x04\x00"     # max APDU 1024 (2-byte form)
                         + b"\x91\x03"         # segmentation: no-segmentation
                         + b"\x9a\x03\xe7")    # vendor 999 (2-byte form)
        expected = b"\x81\x0a" + struct.pack(">H", 4 + 2 + len(expected_apdu)) \
            + b"\x01\x00" + expected_apdu
        assert resp == expected, f"I-Am mismatch:\n got {resp.hex(' ')}\n exp {expected.hex(' ')}"
    finally:
        await teardown(server)


@pytest.mark.asyncio
async def test_read_property_present_value_exact():
    """ReadProperty analogOutput,1 present-value (0x55) -> ComplexACK with float 23.5."""
    server, port = await start_server()
    try:
        invoke_id = 0x2A
        apdu = bytes([0x00, 0x05, invoke_id, 0x0C]) + b"\x0c" + obj_id(1, 1) + b"\x19\x55"
        request = b"\x81\x0a" + struct.pack(">H", 4 + 2 + len(apdu)) + b"\x01\x00" + apdu
        resp = await udp_exchange(port, request)
        expected_apdu = (bytes([0x30, invoke_id, 0x0C])
                         + b"\x0c" + obj_id(1, 1)
                         + b"\x19\x55"
                         + b"\x2e"          # value-list opening tag
                         + b"\x44" + struct.pack(">f", 23.5)
                         + b"\x2f")         # closing tag
        expected = b"\x81\x0a" + struct.pack(">H", 4 + 2 + len(expected_apdu)) \
            + b"\x01\x00" + expected_apdu
        assert resp == expected, f"ReadProperty ACK mismatch:\n got {resp.hex(' ')}\n exp {expected.hex(' ')}"
    finally:
        await teardown(server)


@pytest.mark.asyncio
async def test_write_property_and_readback():
    """WriteProperty analogOutput,2 = 21.0 -> SimpleACK; readback returns 21.0."""
    server, port = await start_server()
    try:
        invoke_id = 0x33
        apdu = (bytes([0x00, 0x05, invoke_id, 0x0F]) + b"\x0c" + obj_id(1, 1) + b"\x19\x55"
                + b"\x2e" + b"\x44" + struct.pack(">f", 21.0) + b"\x2f")
        request = b"\x81\x0a" + struct.pack(">H", 4 + 2 + len(apdu)) + b"\x01\x00" + apdu
        resp = await udp_exchange(port, request)
        expected = b"\x81\x0a\x00\x09" + b"\x01\x00" + bytes([0x20, invoke_id, 0x0F])
        assert resp == expected, f"WriteProperty ACK mismatch:\n got {resp.hex(' ')}\n exp {expected.hex(' ')}"

        invoke_id2 = 0x34
        apdu2 = bytes([0x00, 0x05, invoke_id2, 0x0C]) + b"\x0c" + obj_id(1, 1) + b"\x19\x55"
        request2 = b"\x81\x0a" + struct.pack(">H", 4 + 2 + len(apdu2)) + b"\x01\x00" + apdu2
        resp2 = await udp_exchange(port, request2)
        assert struct.pack(">f", 21.0) in resp2, \
            f"readback value mismatch: {resp2.hex(' ')}"
    finally:
        await teardown(server)


@pytest.mark.asyncio
async def test_read_property_unknown_object_reject():
    """ReadProperty on a nonexistent object instance -> Error APDU
    (error-class 1 = object, error-code 31 = unknown-object)."""
    server, port = await start_server()
    try:
        invoke_id = 0x11
        apdu = bytes([0x00, 0x05, invoke_id, 0x0C]) + b"\x0c" + obj_id(1, 999) + b"\x19\x55"
        request = b"\x81\x0a" + struct.pack(">H", 4 + 2 + len(apdu)) + b"\x01\x00" + apdu
        resp = await udp_exchange(port, request)
        expected = b"\x81\x0a\x00\x0d" + b"\x01\x00" + bytes([0x50, invoke_id, 0x0C]) \
            + b"\x91\x01\x91\x1f"
        assert resp == expected, f"Reject mismatch:\n got {resp.hex(' ')}\n exp {expected.hex(' ')}"
    finally:
        await teardown(server)
