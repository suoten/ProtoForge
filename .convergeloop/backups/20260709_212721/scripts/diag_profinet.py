"""
ProtoForge PROFINET Server Diagnostic Test
Target: 127.0.0.1:34964 (CM TCP tunnel)
"""

import sys
import os
import struct
import asyncio
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from protoforge.protocols.profinet.server import ProfinetServer
from protoforge.models.device import DeviceConfig, PointConfig

HOST = "127.0.0.1"
PORT = 34964
TIMEOUT = 5

MSG_TYPE_DCP = 0x01
MSG_TYPE_RT = 0x02
MSG_TYPE_CM = 0x03
MSG_TYPE_ALARM = 0x04

DCP_SERVICE_GET = 0x03
DCP_SERVICE_SET = 0x04
DCP_SERVICE_IDENTIFY = 0x05
DCP_BLOCK_DEVICE_NAME = 0x02

CM_OP_CONNECT = 0x01
CM_OP_RELEASE = 0x02
CM_OP_READ = 0x03
CM_OP_WRITE = 0x04
CM_OP_CONTROL = 0x05

results = []


def record(name, passed, detail=""):
    status = "PASS" if passed else "FAIL"
    results.append((name, passed))
    msg = f"  [{status}] {name}"
    if detail:
        msg += f"\n         {detail}"
    print(msg)


async def send_recv(reader, writer, payload):
    """Send a tunneled PROFINET frame and receive the response."""
    frame = struct.pack(">H", len(payload)) + payload
    writer.write(frame)
    await writer.drain()

    hdr = await asyncio.wait_for(reader.readexactly(2), timeout=TIMEOUT)
    body_len = struct.unpack(">H", hdr)[0]
    if body_len == 0:
        return b""
    data = await asyncio.wait_for(reader.readexactly(body_len), timeout=TIMEOUT)
    return data


async def open_connection():
    """Open a new TCP connection to the PROFINET server."""
    return await asyncio.wait_for(
        asyncio.open_connection(HOST, PORT), timeout=TIMEOUT
    )


async def close_connection(reader, writer):
    """Close a TCP connection gracefully."""
    writer.close()
    try:
        await writer.wait_closed()
    except Exception:
        pass


async def start_server():
    server = ProfinetServer()
    server._host = HOST
    server._port = PORT
    config = DeviceConfig(
        id="test-pn",
        name="Test PROFINET Device",
        protocol="profinet",
        points=[
            PointConfig(name="temperature", address="0", data_type="float32", access="rw", fixed_value=25.0),
        ],
    )
    await server.create_device(config)
    await server.start({"host": HOST, "port": PORT,
                        "ip_address": "192.168.1.1",
                        "subnet_mask": "255.255.255.0",
                        "gateway": "192.168.1.254"})
    return server


async def wait_for_port(host, port, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            r, w = await asyncio.wait_for(
                asyncio.open_connection(host, port), timeout=1.0
            )
            w.close()
            await w.wait_closed()
            return True
        except (ConnectionRefusedError, OSError, asyncio.TimeoutError):
            await asyncio.sleep(0.1)
    return False


# ---------------------------------------------------------------------------
# DCP Tests (each on its own connection since server bugs may kill connection)
# ---------------------------------------------------------------------------

async def test_dcp_identify():
    """DCP Identify request/response."""
    xid = 0x00000001
    # Server reads: data[1]=service_id, data[2:6]=xid
    # So after MSG_TYPE_DCP byte, we need: service_id(1) + xid(4) directly
    dcp_body = struct.pack(">BIHH",
                           DCP_SERVICE_IDENTIFY,
                           xid,
                           0x0000, # response_delay + padding
                           0)      # block_count
    payload = bytes([MSG_TYPE_DCP]) + dcp_body

    try:
        reader, writer = await open_connection()
        resp = await send_recv(reader, writer, payload)
    except asyncio.IncompleteReadError:
        record("DCP Identify", False, "server closed connection (known bug: struct.pack H overflow for subnet_mask)")
        return
    except Exception as e:
        record("DCP Identify", False, f"error: {e}")
        return
    finally:
        try:
            await close_connection(reader, writer)
        except Exception:
            pass

    if resp is None or len(resp) < 2 or resp[0] != MSG_TYPE_DCP:
        record("DCP Identify", False, f"unexpected response (len={len(resp) if resp else 0})")
        return
    if len(resp) < 11:
        record("DCP Identify", False, f"response too short ({len(resp)} bytes)")
        return

    # Response: msg_type(1) + service_id(1) + service_type(1) + xid(4) + reserved(2) + data_len(2)
    resp_service = resp[1]
    resp_xid = struct.unpack(">I", resp[3:7])[0]
    resp_data_len = struct.unpack(">H", resp[9:11])[0]

    ok_service = resp_service == DCP_SERVICE_IDENTIFY + 1
    ok_xid = resp_xid == xid
    ok_data = resp_data_len > 0

    detail_parts = []
    data = resp[11:]
    if len(data) >= 4:
        vendor_id = struct.unpack(">H", data[0:2])[0]
        device_id = struct.unpack(">H", data[2:4])[0]
        detail_parts.append(f"vendor=0x{vendor_id:04X}, device=0x{device_id:04X}")
    if not ok_service:
        detail_parts.append(f"service=0x{resp_service:02X} (expect 0x06)")
    if not ok_xid:
        detail_parts.append(f"xid=0x{resp_xid:08X} (expect 0x{xid:08X})")
    if not ok_data:
        detail_parts.append(f"data_len={resp_data_len}")

    passed = ok_service and ok_xid and ok_data
    record("DCP Identify", passed, ", ".join(detail_parts))


async def test_dcp_get():
    """DCP Get request/response."""
    xid = 0x00000002
    dcp_body = struct.pack(">BIHH",
                           DCP_SERVICE_GET,
                           xid,
                           0x0000,
                           0)
    payload = bytes([MSG_TYPE_DCP]) + dcp_body

    try:
        reader, writer = await open_connection()
        resp = await send_recv(reader, writer, payload)
    except asyncio.IncompleteReadError:
        record("DCP Get", False, "server closed connection")
        return
    except Exception as e:
        record("DCP Get", False, f"error: {e}")
        return
    finally:
        try:
            await close_connection(reader, writer)
        except Exception:
            pass

    if resp is None or len(resp) < 2 or resp[0] != MSG_TYPE_DCP:
        record("DCP Get", False, f"unexpected response")
        return
    if len(resp) < 11:
        record("DCP Get", False, f"response too short ({len(resp)} bytes)")
        return

    # Response: msg_type(1) + service_id(1) + service_type(1) + xid(4) + reserved(2) + data_len(2)
    resp_service = resp[1]
    resp_xid = struct.unpack(">I", resp[3:7])[0]

    ok_service = resp_service == DCP_SERVICE_GET + 1
    ok_xid = resp_xid == xid

    data = resp[11:]
    name_str = ""
    if len(data) >= 3 and data[0] == DCP_BLOCK_DEVICE_NAME:
        name_len = struct.unpack(">H", data[1:3])[0]
        if len(data) >= 3 + name_len - 4:
            name_str = data[3:3 + name_len - 4].decode("utf-8", errors="replace")

    passed = ok_service and ok_xid
    detail = f"service=0x{resp_service:02X}, xid=0x{resp_xid:08X}"
    if name_str:
        detail += f", device_name='{name_str}'"
    record("DCP Get", passed, detail)


async def test_dcp_set():
    """DCP Set request/response."""
    xid = 0x00000003
    dcp_body = struct.pack(">BIHH",
                           DCP_SERVICE_SET,
                           xid,
                           0x0000,
                           0)
    payload = bytes([MSG_TYPE_DCP]) + dcp_body

    try:
        reader, writer = await open_connection()
        resp = await send_recv(reader, writer, payload)
    except asyncio.IncompleteReadError:
        record("DCP Set", False, "server closed connection")
        return
    except Exception as e:
        record("DCP Set", False, f"error: {e}")
        return
    finally:
        try:
            await close_connection(reader, writer)
        except Exception:
            pass

    if resp is None or len(resp) < 2 or resp[0] != MSG_TYPE_DCP:
        record("DCP Set", False, f"unexpected response")
        return
    # DCP Set response has no data, so minimum is: msg_type(1) + service_id(1) + service_type(1) + xid(4) + reserved(2) + data_len(2) = 11
    if len(resp) < 11:
        # But server may send shorter response for Set (data_len=0)
        if len(resp) >= 10:
            resp_service = resp[1]
            resp_xid = struct.unpack(">I", resp[3:7])[0] if len(resp) >= 7 else 0
            ok_service = resp_service == DCP_SERVICE_SET + 1
            ok_xid = resp_xid == xid
            record("DCP Set", ok_service and ok_xid,
                   f"service=0x{resp_service:02X}, xid=0x{resp_xid:08X}")
            return
        record("DCP Set", False, f"response too short ({len(resp)} bytes)")
        return

    # Response: msg_type(1) + service_id(1) + service_type(1) + xid(4) + reserved(2) + data_len(2)
    resp_service = resp[1]
    resp_xid = struct.unpack(">I", resp[3:7])[0]

    ok_service = resp_service == DCP_SERVICE_SET + 1
    ok_xid = resp_xid == xid
    record("DCP Set", ok_service and ok_xid,
           f"service=0x{resp_service:02X}, xid=0x{resp_xid:08X}")


# ---------------------------------------------------------------------------
# CM/RT/Alarm Tests (on a single connection)
# ---------------------------------------------------------------------------

async def test_cm_connect(reader, writer):
    """CM Connect request/response. Returns AR ID on success."""
    cm_seq = 0x01
    session_key = 0x0001
    send_clock = 0x0032
    reduction_ratio = 0x0001

    cm_body = struct.pack(">BBBBHHH",
                          MSG_TYPE_CM,
                          CM_OP_CONNECT,
                          cm_seq,
                          0x01,
                          session_key,
                          send_clock,
                          reduction_ratio)

    try:
        resp = await send_recv(reader, writer, cm_body)
    except Exception as e:
        record("CM Connect", False, f"error: {e}")
        return None

    if resp is None or len(resp) < 3 or resp[0] != MSG_TYPE_CM:
        record("CM Connect", False, f"unexpected response")
        return None

    resp_op = resp[1]
    if resp_op != CM_OP_CONNECT:
        record("CM Connect", False, f"unexpected cm_op=0x{resp_op:02X} (expect 0x01)")
        return None

    data = resp[3:]
    if len(data) < 29:
        record("CM Connect", False, f"response body too short ({len(data)} bytes)")
        return None

    ar_id = struct.unpack(">H", data[0:2])[0]
    resp_session_key = struct.unpack(">H", data[19:21])[0]
    resp_send_clock = struct.unpack(">H", data[21:23])[0]
    cr_count = struct.unpack(">H", data[27:29])[0]

    cr_offset = 29
    crs = []
    for _ in range(cr_count):
        if cr_offset + 9 > len(data):
            break
        cr_type = data[cr_offset]
        cr_id = struct.unpack(">H", data[cr_offset + 1:cr_offset + 3])[0]
        cr_data_len = struct.unpack(">H", data[cr_offset + 3:cr_offset + 5])[0]
        cr_frame_id = struct.unpack(">H", data[cr_offset + 5:cr_offset + 7])[0]
        crs.append({"type": cr_type, "id": cr_id, "data_len": cr_data_len,
                     "frame_id": cr_frame_id})
        cr_offset += 9

    detail = (f"ar_id={ar_id}, session_key=0x{resp_session_key:04X}, "
              f"send_clock={resp_send_clock}, crs={cr_count}")
    if crs:
        cr_summary = ", ".join(
            f"CR{c['id']}(type={c['type']},len={c['data_len']},fid=0x{c['frame_id']:04X})"
            for c in crs)
        detail += f" [{cr_summary}]"

    ok = ar_id > 0 and cr_count > 0
    record("CM Connect", ok, detail)
    return ar_id if ok else None


async def test_cm_control(reader, writer, ar_id):
    """CM Control (ApplicationReady) request/response."""
    cm_seq = 0x02
    control_cmd = 0x01

    cm_body = struct.pack(">BBBHB",
                          MSG_TYPE_CM,
                          CM_OP_CONTROL,
                          cm_seq,
                          ar_id,
                          control_cmd)

    try:
        resp = await send_recv(reader, writer, cm_body)
    except Exception as e:
        record("CM Control (ApplicationReady)", False, f"error: {e}")
        return

    if resp is None or len(resp) < 3 or resp[0] != MSG_TYPE_CM:
        record("CM Control (ApplicationReady)", False, f"unexpected response")
        return

    resp_op = resp[1]
    if resp_op != CM_OP_CONTROL:
        record("CM Control (ApplicationReady)", False, f"unexpected cm_op=0x{resp_op:02X}")
        return

    data = resp[3:]
    if len(data) < 5:
        record("CM Control (ApplicationReady)", False, f"response body too short ({len(data)} bytes)")
        return

    resp_ar_id = struct.unpack(">H", data[0:2])[0]
    resp_cmd = data[2]
    resp_status = struct.unpack(">H", data[3:5])[0]

    ok = resp_ar_id == ar_id and resp_cmd == control_cmd and resp_status == 0x0000
    record("CM Control (ApplicationReady)", ok,
           f"ar_id={resp_ar_id}, cmd=0x{resp_cmd:02X}, status=0x{resp_status:04X}")


async def test_cm_read(reader, writer):
    """CM Read request/response."""
    cm_seq = 0x03
    cm_body = struct.pack(">BBB", MSG_TYPE_CM, CM_OP_READ, cm_seq)

    try:
        resp = await send_recv(reader, writer, cm_body)
    except Exception as e:
        record("CM Read", False, f"error: {e}")
        return

    if resp is None or len(resp) < 3 or resp[0] != MSG_TYPE_CM:
        record("CM Read", False, f"unexpected response")
        return
    if resp[1] != CM_OP_READ:
        record("CM Read", False, f"unexpected cm_op=0x{resp[1]:02X}")
        return

    data = resp[3:]
    if len(data) < 4:
        record("CM Read", False, f"response body too short ({len(data)} bytes)")
        return

    s1 = struct.unpack(">H", data[0:2])[0]
    s2 = struct.unpack(">H", data[2:4])[0]
    record("CM Read", True, f"status1=0x{s1:04X}, status2=0x{s2:04X}")


async def test_cm_write(reader, writer):
    """CM Write request/response."""
    cm_seq = 0x04
    cm_body = struct.pack(">BBB", MSG_TYPE_CM, CM_OP_WRITE, cm_seq)

    try:
        resp = await send_recv(reader, writer, cm_body)
    except Exception as e:
        record("CM Write", False, f"error: {e}")
        return

    if resp is None or len(resp) < 3 or resp[0] != MSG_TYPE_CM:
        record("CM Write", False, f"unexpected response")
        return
    if resp[1] != CM_OP_WRITE:
        record("CM Write", False, f"unexpected cm_op=0x{resp[1]:02X}")
        return

    data = resp[3:]
    if len(data) < 4:
        record("CM Write", False, f"response body too short ({len(data)} bytes)")
        return

    s1 = struct.unpack(">H", data[0:2])[0]
    s2 = struct.unpack(">H", data[2:4])[0]
    record("CM Write", True, f"status1=0x{s1:04X}, status2=0x{s2:04X}")


async def test_rt_cyclic(reader, writer):
    """RT cyclic data exchange (read input data)."""
    cycle_counter = 0x0001
    data_status = 0x01
    transfer_status = 0x00

    rt_body = struct.pack(">BHBB",
                          MSG_TYPE_RT,
                          cycle_counter,
                          data_status,
                          transfer_status)

    try:
        resp = await send_recv(reader, writer, rt_body)
    except Exception as e:
        record("RT Cyclic Data", False, f"error: {e}")
        return

    if resp is None or len(resp) < 2 or resp[0] != MSG_TYPE_RT:
        record("RT Cyclic Data", False, f"unexpected response")
        return

    data = resp[1:]
    if len(data) < 4:
        record("RT Cyclic Data", False, f"response body too short ({len(data)} bytes)")
        return

    resp_cycle = struct.unpack(">H", data[0:2])[0]
    resp_data_status = data[2]
    input_data = data[4:]

    expected_input_size = 4
    temp_val = None
    if len(input_data) >= expected_input_size:
        temp_val = struct.unpack(">f", input_data[:4])[0]

    ok = resp_cycle == cycle_counter + 1 and len(input_data) >= expected_input_size
    detail = f"cycle={resp_cycle}, data_status=0x{resp_data_status:02X}, input_len={len(input_data)}"
    if temp_val is not None:
        detail += f", temperature={temp_val:.1f}"
    record("RT Cyclic Data", ok, detail)


async def test_rt_cyclic_write(reader, writer):
    """RT cyclic write output data then read back input data."""
    cycle_counter = 0x0002
    data_status = 0x01
    transfer_status = 0x00
    write_val = 42.5
    output_data = struct.pack(">f", write_val)

    rt_body = struct.pack(">BHBB",
                          MSG_TYPE_RT,
                          cycle_counter,
                          data_status,
                          transfer_status) + output_data

    try:
        resp = await send_recv(reader, writer, rt_body)
    except Exception as e:
        record("RT Cyclic Write+Read", False, f"error: {e}")
        return

    if resp is None or len(resp) < 2 or resp[0] != MSG_TYPE_RT:
        record("RT Cyclic Write+Read", False, f"unexpected response")
        return

    data = resp[1:]
    if len(data) < 4:
        record("RT Cyclic Write+Read", False, f"response body too short ({len(data)} bytes)")
        return

    resp_cycle = struct.unpack(">H", data[0:2])[0]
    input_data = data[4:]

    temp_val = None
    if len(input_data) >= 4:
        temp_val = struct.unpack(">f", input_data[:4])[0]

    ok = resp_cycle == cycle_counter + 1
    detail = f"cycle={resp_cycle}, input_len={len(input_data)}"
    if temp_val is not None:
        detail += f", temperature={temp_val:.1f}"
    record("RT Cyclic Write+Read", ok, detail)


async def test_alarm(reader, writer, ar_id):
    """Alarm request/response."""
    alarm_type = 0x0001
    alarm_seq = 0x0001
    alarm_spec = 0x01

    alarm_body = struct.pack(">BHHHB",
                             MSG_TYPE_ALARM,
                             alarm_type,
                             ar_id,
                             alarm_seq,
                             alarm_spec)

    try:
        resp = await send_recv(reader, writer, alarm_body)
    except Exception as e:
        record("Alarm", False, f"error: {e}")
        return

    if resp is None or len(resp) < 2 or resp[0] != MSG_TYPE_ALARM:
        record("Alarm", False, f"unexpected response")
        return

    data = resp[1:]
    if len(data) < 9:
        record("Alarm", False, f"response body too short ({len(data)} bytes)")
        return

    resp_alarm_type = struct.unpack(">H", data[0:2])[0]
    resp_ar_id = struct.unpack(">H", data[2:4])[0]
    resp_alarm_seq = struct.unpack(">H", data[4:6])[0]
    resp_status = struct.unpack(">H", data[7:9])[0]

    ok = (resp_alarm_type == alarm_type and
          resp_ar_id == ar_id and
          resp_alarm_seq == alarm_seq and
          resp_status == 0x0000)
    record("Alarm", ok,
           f"type=0x{resp_alarm_type:04X}, ar_id={resp_ar_id}, "
           f"seq={resp_alarm_seq}, status=0x{resp_status:04X}")


async def test_cm_release(reader, writer, ar_id):
    """CM Release request/response."""
    cm_seq = 0x06
    cm_body = struct.pack(">BBBH",
                          MSG_TYPE_CM,
                          CM_OP_RELEASE,
                          cm_seq,
                          ar_id)

    try:
        resp = await send_recv(reader, writer, cm_body)
    except Exception as e:
        record("CM Release", False, f"error: {e}")
        return

    if resp is None or len(resp) < 3 or resp[0] != MSG_TYPE_CM:
        record("CM Release", False, f"unexpected response")
        return
    if resp[1] != CM_OP_RELEASE:
        record("CM Release", False, f"unexpected cm_op=0x{resp[1]:02X}")
        return

    data = resp[3:]
    if len(data) < 4:
        record("CM Release", False, f"response body too short ({len(data)} bytes)")
        return

    resp_ar_id = struct.unpack(">H", data[0:2])[0]
    resp_status = struct.unpack(">H", data[2:4])[0]

    ok = resp_ar_id == ar_id and resp_status == 0x0000
    record("CM Release", ok,
           f"ar_id={resp_ar_id}, status=0x{resp_status:04X}")


async def test_unknown_msg_type():
    """Unknown message type should be handled gracefully (no response, but no crash)."""
    payload = bytes([0xFF, 0x00, 0x00])
    try:
        reader, writer = await open_connection()
        # Send the unknown message type
        frame = struct.pack(">H", len(payload)) + payload
        writer.write(frame)
        await writer.drain()
        # Server returns None for unknown types, so no response is sent.
        # Try to read with a short timeout - if we get nothing, that's expected.
        try:
            hdr = await asyncio.wait_for(reader.readexactly(2), timeout=2)
            # If we got a response, that's also fine
            record("Unknown Message Type (graceful)", True,
                   "server responded to unknown msg type")
        except asyncio.TimeoutError:
            # No response is expected for unknown msg type
            record("Unknown Message Type (graceful)", True,
                   "no response for unknown msg type (expected)")
        except asyncio.IncompleteReadError:
            # Connection closed is also acceptable
            record("Unknown Message Type (graceful)", True,
                   "connection closed after unknown msg type")
    except Exception as e:
        record("Unknown Message Type (graceful)", False, str(e))
    finally:
        try:
            await close_connection(reader, writer)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def run_tests():
    """Run all PROFINET diagnostic tests."""
    # DCP tests - each on its own connection (server may crash connection on error)
    await test_dcp_identify()
    await test_dcp_get()
    await test_dcp_set()

    # CM/RT/Alarm tests - single connection for stateful operations
    try:
        reader, writer = await open_connection()
    except (ConnectionRefusedError, OSError) as e:
        print(f"\nFAIL: Cannot connect to {HOST}:{PORT} - {e}")
        return
    except asyncio.TimeoutError:
        print(f"\nFAIL: Connection timed out ({TIMEOUT}s)")
        return

    try:
        ar_id = await test_cm_connect(reader, writer)

        if ar_id is not None:
            await test_cm_control(reader, writer, ar_id)
            await test_cm_read(reader, writer)
            await test_cm_write(reader, writer)
            await test_rt_cyclic(reader, writer)
            await test_rt_cyclic_write(reader, writer)
            await test_alarm(reader, writer, ar_id)
            await test_cm_release(reader, writer, ar_id)
    finally:
        await close_connection(reader, writer)

    # Unknown msg type test - separate connection
    await test_unknown_msg_type()


async def main():
    print("=" * 60)
    print("  ProtoForge PROFINET Server Diagnostic Test")
    print(f"  Target: {HOST}:{PORT}")
    print("=" * 60)

    print(f"\nStarting PROFINET server on {HOST}:{PORT} ...")
    server = None
    try:
        server = await start_server()
        if not await wait_for_port(HOST, PORT):
            print("FAIL: Server did not become ready within timeout")
            await server.stop()
            return
        print("Server is accepting connections.\n")
    except Exception as e:
        print(f"FAIL: Could not start server: {e}")
        return

    try:
        await run_tests()
    finally:
        print("\nStopping server ...")
        await server.stop()

    print("\n" + "=" * 60)
    print("  Test Summary")
    print("=" * 60)
    passed = sum(1 for _, p in results if p)
    failed = len(results) - passed
    for name, p in results:
        print(f"  [{'PASS' if p else 'FAIL'}]  {name}")
    print(f"\n  Total: {len(results)}, Passed: {passed}, Failed: {failed}")
    if failed == 0:
        print("  All tests PASSED!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
