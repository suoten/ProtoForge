"""
ProtoForge BACnet/IP Diagnostic Test Script

Tests the BACnet server using raw UDP sockets. Validates Who-Is/I-Am,
ReadProperty, WriteProperty, and read-back-verify operations against
the ProtoForge BACnet frame handler.

Usage:
    python scripts/diag_bacnet.py
"""

import sys
import os
import socket
import struct
import asyncio

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from protoforge.protocols.bacnet.server import BACnetServer
from protoforge.models.device import DeviceConfig, PointConfig

HOST = "127.0.0.1"
PORT = 47808
SOCKET_TIMEOUT = 5

# BACnet object type IDs
OBJ_ANALOG_INPUT = 0
OBJ_ANALOG_OUTPUT = 1
OBJ_ANALOG_VALUE = 2
OBJ_BINARY_INPUT = 3
OBJ_DEVICE = 8

# BACnet property IDs
PROP_PRESENT_VALUE = 85
PROP_OBJECT_NAME = 77
PROP_DESCRIPTION = 28

# BACnet service choices
SVC_READ_PROPERTY = 0x0C
SVC_WRITE_PROPERTY = 0x0F
SVC_WHO_IS = 0x08
SVC_I_AM = 0x00

# BVLC function codes
BVLC_ORIGINAL_UNICAST = 0x0A
BVLC_ORIGINAL_BROADCAST = 0x0B


# ---------------------------------------------------------------------------
# Frame building helpers
# ---------------------------------------------------------------------------

def _build_bvlc(bvlc_func: int, apdu: bytes) -> bytes:
    """Build a complete BACnet/IP frame: BVLC + NPDU + APDU.

    BVLC header (4 bytes):
      0x81  - BVLC Type
      func  - BVLC Function (0x0A unicast, 0x0B broadcast)
      len   - Total frame length (uint16 BE), including BVLC header

    NPDU (2 bytes):
      0x01  - NPDU Version
      0x00  - Control: no routing, no hop count
    """
    total_len = 4 + 2 + len(apdu)  # BVLC(4) + NPDU(2) + APDU
    bvlc = struct.pack(">BBH", 0x81, bvlc_func, total_len)
    npdu = bytes([0x01, 0x00])
    return bvlc + npdu + apdu


def _encode_object_id(obj_type: int, obj_inst: int) -> bytes:
    """Encode a BACnet Object Identifier as 4 bytes (big-endian).

    Format: (object_type << 22) | instance
    """
    return struct.pack(">I", (obj_type << 22) | obj_inst)


def build_who_is(low: int = 0, high: int = 255) -> bytes:
    """Build a BACnet Who-Is request (Unconfirmed Request, broadcast).

    APDU: 0x10 (Unconfirmed Request) + 0x08 (Who-Is)
          + low_limit (Tag 0x21 + 1 byte) + high_limit (Tag 0x21 + 1 byte)
    """
    apdu = bytes([
        0x10,          # PDU type: Unconfirmed Request
        SVC_WHO_IS,    # Service Choice: Who-Is
        0x21,          # Application tag: Unsigned8
        low & 0xFF,
        0x21,          # Application tag: Unsigned8
        high & 0xFF,
    ])
    return _build_bvlc(BVLC_ORIGINAL_BROADCAST, apdu)


def build_read_property(invoke_id: int, obj_type: int, obj_inst: int,
                        prop_id: int) -> bytes:
    """Build a BACnet ReadProperty request (Confirmed Request, unicast).

    APDU (non-segmented confirmed request):
      0x00       - PDU type: Confirmed Request (no segmentation)
      invoke_id  - Invoke ID
      0x0C       - Service Choice: ReadProperty
      obj_id     - Object Identifier (4 bytes, raw encoding)
      prop_id    - Property Identifier (1 byte)
    """
    apdu = bytes([0x00, invoke_id & 0xFF, SVC_READ_PROPERTY])
    apdu += _encode_object_id(obj_type, obj_inst)
    apdu += bytes([prop_id & 0xFF])
    return _build_bvlc(BVLC_ORIGINAL_UNICAST, apdu)


def build_write_property_float(invoke_id: int, obj_type: int, obj_inst: int,
                               prop_id: int, value: float) -> bytes:
    """Build a BACnet WriteProperty request for a REAL (float32) value.

    APDU (non-segmented confirmed request):
      0x00       - PDU type: Confirmed Request
      invoke_id  - Invoke ID
      0x0F       - Service Choice: WriteProperty
      obj_id     - Object Identifier (4 bytes)
      prop_id    - Property Identifier (1 byte)
      0x44       - Application tag: REAL (float32)
      value      - 4 bytes big-endian IEEE 754 float
    """
    apdu = bytes([0x00, invoke_id & 0xFF, SVC_WRITE_PROPERTY])
    apdu += _encode_object_id(obj_type, obj_inst)
    apdu += bytes([prop_id & 0xFF])
    apdu += bytes([0x44])  # REAL application tag
    apdu += struct.pack(">f", value)
    return _build_bvlc(BVLC_ORIGINAL_UNICAST, apdu)


# ---------------------------------------------------------------------------
# Response parsing helpers
# ---------------------------------------------------------------------------

def _parse_bvlc(data: bytes) -> dict | None:
    """Parse BVLC header and return {type, func, length} or None."""
    if len(data) < 4 or data[0] != 0x81:
        return None
    length = struct.unpack(">H", data[2:4])[0]
    return {"type": data[0], "func": data[1], "length": length}


def parse_i_am(data: bytes) -> dict | None:
    """Parse an I-Am response.

    Expected structure after BVLC+NPDU (6 bytes):
      0x10       - Unconfirmed Request PDU type
      0x00       - Service Choice: I-Am
      0xC4       - Context tag 0, length 4 (Object Identifier)
      obj_id     - 4 bytes
      0x89/0x8A  - Context tag 1 (Max APDU Length)
      max_apdu   - 1 or 2 bytes
      0x91       - Context tag 2, length 1 (Segmentation Supported)
      seg        - 1 byte
      0x99/0x9A  - Context tag 3 (Vendor ID)
      vendor_id  - 1 or 2 bytes
    """
    bvlc = _parse_bvlc(data)
    if not bvlc or bvlc["func"] != BVLC_ORIGINAL_UNICAST:
        return None
    if len(data) < 8:
        return None

    offset = 6  # skip BVLC(4) + NPDU(2)
    if data[offset] != 0x10 or data[offset + 1] != SVC_I_AM:
        return None
    offset += 2

    result = {}
    while offset < len(data):
        tag = data[offset]
        if tag == 0xC4:  # Context tag 0, length 4: Object Identifier
            offset += 1
            if offset + 4 > len(data):
                break
            obj_id = struct.unpack(">I", data[offset:offset + 4])[0]
            result["obj_type"] = (obj_id >> 22) & 0x3FF
            result["obj_inst"] = obj_id & 0x3FFFFF
            offset += 4
        elif tag == 0x89:  # Context tag 1, length 1: Max APDU
            offset += 1
            result["max_apdu"] = data[offset]
            offset += 1
        elif tag == 0x8A:  # Context tag 1, length 2: Max APDU
            offset += 1
            result["max_apdu"] = struct.unpack(">H", data[offset:offset + 2])[0]
            offset += 2
        elif tag == 0x91:  # Context tag 2, length 1: Segmentation
            offset += 1
            result["segmentation"] = data[offset]
            offset += 1
        elif tag == 0x99:  # Context tag 3, length 1: Vendor ID
            offset += 1
            result["vendor_id"] = data[offset]
            offset += 1
        elif tag == 0x9A:  # Context tag 3, length 2: Vendor ID
            offset += 1
            result["vendor_id"] = struct.unpack(">H", data[offset:offset + 2])[0]
            offset += 2
        else:
            offset += 1  # skip unknown tag

    return result if result else None


def parse_read_property_response(data: bytes, expected_invoke_id: int) -> dict | None:
    """Parse a ReadProperty Complex ACK response.

    Expected structure after BVLC+NPDU (6 bytes):
      invoke_id  - 1 byte
      0x0C       - Service ACK choice: ReadProperty
      obj_id     - 4 bytes (echoed back)
      prop_id    - 1 byte (echoed back)
      value_tag  - 1 byte (application tag)
      value_data - variable length
    """
    bvlc = _parse_bvlc(data)
    if not bvlc or bvlc["func"] != BVLC_ORIGINAL_UNICAST:
        return None
    if len(data) < 8:
        return None

    offset = 6  # skip BVLC(4) + NPDU(2)
    invoke_id = data[offset]
    if invoke_id != expected_invoke_id:
        return None
    offset += 1

    svc = data[offset]
    offset += 1

    # Error response
    if svc == 0x50:
        err_svc = data[offset] if offset < len(data) else 0
        offset += 1
        err_class = data[offset + 1] if offset + 1 < len(data) else 0
        err_code = data[offset + 3] if offset + 3 < len(data) else 0
        return {"error": True, "service": err_svc,
                "error_class": err_class, "error_code": err_code}

    # Complex ACK for ReadProperty
    if svc != SVC_READ_PROPERTY:
        return None

    # Skip echoed object identifier (4 bytes) and property identifier (1 byte)
    if offset + 5 > len(data):
        return None
    resp_obj_id = struct.unpack(">I", data[offset:offset + 4])[0]
    resp_obj_type = (resp_obj_id >> 22) & 0x3FF
    resp_obj_inst = resp_obj_id & 0x3FFFFF
    offset += 4
    resp_prop_id = data[offset]
    offset += 1

    # Parse value based on application tag
    if offset >= len(data):
        return None

    tag = data[offset]
    offset += 1
    value = None
    value_type = "unknown"

    if tag == 0x44:  # REAL (float32)
        if offset + 4 <= len(data):
            value = struct.unpack(">f", data[offset:offset + 4])[0]
            value_type = "float"
            offset += 4
    elif tag == 0x55:  # DOUBLE (float64)
        if offset + 8 <= len(data):
            value = struct.unpack(">d", data[offset:offset + 8])[0]
            value_type = "double"
            offset += 8
    elif tag == 0x75:  # Character String
        if offset + 2 <= len(data):
            str_len = struct.unpack(">H", data[offset:offset + 2])[0]
            offset += 2
            if offset + str_len <= len(data):
                value = data[offset:offset + str_len].decode("utf-8", errors="replace")
                value_type = "string"
    elif tag == 0x21:  # Unsigned8
        if offset < len(data):
            value = data[offset]
            value_type = "uint8"
            offset += 1
    elif tag == 0x22:  # Unsigned16
        if offset + 2 <= len(data):
            value = struct.unpack(">H", data[offset:offset + 2])[0]
            value_type = "uint16"
            offset += 2
    elif tag == 0x24:  # Unsigned32
        if offset + 4 <= len(data):
            value = struct.unpack(">I", data[offset:offset + 4])[0]
            value_type = "uint32"
            offset += 4
    elif tag == 0x19:  # Boolean
        if offset < len(data):
            value = bool(data[offset])
            value_type = "bool"
            offset += 1
    elif tag == 0x34:  # Signed32
        if offset + 4 <= len(data):
            value = struct.unpack(">i", data[offset:offset + 4])[0]
            value_type = "int32"
            offset += 4

    return {
        "obj_type": resp_obj_type,
        "obj_inst": resp_obj_inst,
        "prop_id": resp_prop_id,
        "value": value,
        "value_type": value_type,
    }


def parse_write_property_response(data: bytes, expected_invoke_id: int) -> dict | None:
    """Parse a WriteProperty Simple ACK response.

    Expected structure after BVLC+NPDU (6 bytes):
      invoke_id  - 1 byte
      0x0F       - Service ACK choice: WriteProperty
    """
    bvlc = _parse_bvlc(data)
    if not bvlc or bvlc["func"] != BVLC_ORIGINAL_UNICAST:
        return None
    if len(data) < 8:
        return None

    offset = 6  # skip BVLC(4) + NPDU(2)
    invoke_id = data[offset]
    if invoke_id != expected_invoke_id:
        return None
    offset += 1

    svc = data[offset]
    offset += 1

    # Error response
    if svc == 0x50:
        err_svc = data[offset] if offset < len(data) else 0
        offset += 1
        err_class = data[offset + 1] if offset + 1 < len(data) else 0
        err_code = data[offset + 3] if offset + 3 < len(data) else 0
        return {"success": False, "error": True,
                "service": err_svc, "error_class": err_class, "error_code": err_code}

    # Simple ACK for WriteProperty
    if svc == SVC_WRITE_PROPERTY:
        return {"success": True}

    return None


# ---------------------------------------------------------------------------
# Server setup
# ---------------------------------------------------------------------------

async def start_server() -> BACnetServer:
    """Create and start the ProtoForge BACnet server with a test device."""
    server = BACnetServer()

    config = DeviceConfig(
        id="test-bacnet",
        name="Test BACnet Device",
        protocol="bacnet",
        points=[
            PointConfig(
                name="temperature",
                address="AI0",
                data_type="float32",
                access="rw",
                fixed_value=25.0,
            ),
            PointConfig(
                name="pressure",
                address="AI1",
                data_type="float32",
                access="rw",
                fixed_value=100.0,
            ),
        ],
    )

    await server.create_device(config)
    await server.start({"host": HOST, "port": PORT})

    # Brief wait for the UDP socket to be ready
    await asyncio.sleep(0.3)
    return server


# ---------------------------------------------------------------------------
# Test runner (blocking socket I/O)
# ---------------------------------------------------------------------------

def run_tests() -> list[tuple[str, bool, str]]:
    """Execute all BACnet/IP test cases. Returns list of (name, passed, detail)."""
    results: list[tuple[str, bool, str]] = []

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(SOCKET_TIMEOUT)
    # Allow broadcast for Who-Is
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

    invoke_id = 0

    def next_invoke_id() -> int:
        nonlocal invoke_id
        invoke_id += 1
        return invoke_id

    try:
        # ---- Test 1: Who-Is / I-Am ----
        try:
            req = build_who_is(low=0, high=255)
            sock.sendto(req, (HOST, PORT))
            data, addr = sock.recvfrom(2048)
            iam = parse_i_am(data)
            if iam and iam.get("obj_type") == OBJ_DEVICE:
                detail = (f"device_type={iam['obj_type']}, "
                          f"instance={iam['obj_inst']}, "
                          f"vendor_id={iam.get('vendor_id', 'N/A')}, "
                          f"max_apdu={iam.get('max_apdu', 'N/A')}")
                results.append(("Who-Is / I-Am", True, detail))
            else:
                results.append(("Who-Is / I-Am", False,
                                f"unexpected response: {iam}"))
        except socket.timeout:
            results.append(("Who-Is / I-Am", False, "timeout (5s)"))
        except Exception as exc:
            results.append(("Who-Is / I-Am", False, str(exc)))

        # ---- Test 2: Read Property - presentValue (analogInput,1) ----
        # Note: Server creates objects with 1-based instances.
        # access="rw" maps to analogOutput internally, but the server
        # matches by instance number regardless of object type.
        try:
            iid = next_invoke_id()
            req = build_read_property(iid, OBJ_ANALOG_INPUT, 1,
                                      PROP_PRESENT_VALUE)
            sock.sendto(req, (HOST, PORT))
            data, addr = sock.recvfrom(2048)
            resp = parse_read_property_response(data, iid)
            if resp and not resp.get("error"):
                val = resp.get("value")
                vtype = resp.get("value_type")
                # Initial value is 25.0 (temperature point)
                if vtype == "float" and val is not None and abs(val - 25.0) < 0.01:
                    results.append((
                        "ReadProperty analogInput,1 presentValue",
                        True,
                        f"value={val} ({vtype})",
                    ))
                else:
                    results.append((
                        "ReadProperty analogInput,1 presentValue",
                        False,
                        f"expected ~25.0, got value={val} type={vtype}",
                    ))
            else:
                results.append((
                    "ReadProperty analogInput,1 presentValue",
                    False,
                    f"error response: {resp}",
                ))
        except socket.timeout:
            results.append(("ReadProperty analogInput,1 presentValue",
                            False, "timeout (5s)"))
        except Exception as exc:
            results.append(("ReadProperty analogInput,1 presentValue",
                            False, str(exc)))

        # ---- Test 3: Read Property - objectName (analogInput,1) ----
        try:
            iid = next_invoke_id()
            req = build_read_property(iid, OBJ_ANALOG_INPUT, 1,
                                      PROP_OBJECT_NAME)
            sock.sendto(req, (HOST, PORT))
            data, addr = sock.recvfrom(2048)
            resp = parse_read_property_response(data, iid)
            if resp and not resp.get("error"):
                val = resp.get("value")
                vtype = resp.get("value_type")
                if vtype == "string" and val == "temperature":
                    results.append((
                        "ReadProperty analogInput,1 objectName",
                        True,
                        f"value='{val}' ({vtype})",
                    ))
                else:
                    results.append((
                        "ReadProperty analogInput,1 objectName",
                        False,
                        f"expected 'temperature', got value={val!r} type={vtype}",
                    ))
            else:
                results.append((
                    "ReadProperty analogInput,1 objectName",
                    False,
                    f"error response: {resp}",
                ))
        except socket.timeout:
            results.append(("ReadProperty analogInput,1 objectName",
                            False, "timeout (5s)"))
        except Exception as exc:
            results.append(("ReadProperty analogInput,1 objectName",
                            False, str(exc)))

        # ---- Test 4: Write Property - presentValue = 42.5 (analogInput,1) ----
        try:
            iid = next_invoke_id()
            req = build_write_property_float(iid, OBJ_ANALOG_INPUT, 1,
                                             PROP_PRESENT_VALUE, 42.5)
            sock.sendto(req, (HOST, PORT))
            data, addr = sock.recvfrom(2048)
            resp = parse_write_property_response(data, iid)
            if resp and resp.get("success"):
                results.append((
                    "WriteProperty analogInput,1 presentValue=42.5",
                    True,
                    "Simple ACK received",
                ))
            else:
                results.append((
                    "WriteProperty analogInput,1 presentValue=42.5",
                    False,
                    f"unexpected response: {resp}",
                ))
        except socket.timeout:
            results.append(("WriteProperty analogInput,1 presentValue=42.5",
                            False, "timeout (5s)"))
        except Exception as exc:
            results.append(("WriteProperty analogInput,1 presentValue=42.5",
                            False, str(exc)))

        # ---- Test 5: Read back and verify written value ----
        try:
            iid = next_invoke_id()
            req = build_read_property(iid, OBJ_ANALOG_INPUT, 1,
                                      PROP_PRESENT_VALUE)
            sock.sendto(req, (HOST, PORT))
            data, addr = sock.recvfrom(2048)
            resp = parse_read_property_response(data, iid)
            if resp and not resp.get("error"):
                val = resp.get("value")
                vtype = resp.get("value_type")
                if vtype == "float" and val is not None and abs(val - 42.5) < 0.01:
                    results.append((
                        "ReadProperty verify (expect 42.5)",
                        True,
                        f"value={val} ({vtype})",
                    ))
                else:
                    results.append((
                        "ReadProperty verify (expect 42.5)",
                        False,
                        f"expected ~42.5, got value={val} type={vtype}",
                    ))
            else:
                results.append((
                    "ReadProperty verify (expect 42.5)",
                    False,
                    f"error response: {resp}",
                ))
        except socket.timeout:
            results.append(("ReadProperty verify (expect 42.5)",
                            False, "timeout (5s)"))
        except Exception as exc:
            results.append(("ReadProperty verify (expect 42.5)",
                            False, str(exc)))

    finally:
        sock.close()

    return results


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main() -> None:
    print("=" * 64)
    print("ProtoForge BACnet/IP Diagnostic Test")
    print("=" * 64)

    # Start server
    print(f"\nStarting BACnet server on {HOST}:{PORT} ...")
    server = None
    try:
        server = await start_server()
    except Exception as exc:
        print(f"[FATAL] Failed to start server: {exc}")
        sys.exit(1)

    # Run tests in a thread so the blocking socket I/O does not stall the
    # asyncio event loop that the BACnet server is running on.
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
