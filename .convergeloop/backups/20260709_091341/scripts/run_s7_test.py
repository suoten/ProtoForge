"""启动 S7 服务器并自动运行协议栈验证。"""
import asyncio
import socket
import struct
import sys
import time
import threading


def build_cotp_cr(rack=0, slot=1):
    calling_tsap = struct.pack(">H", 0x0100)
    called_tsap = struct.pack(">H", 0x0100 | (rack << 5) | slot)
    cotp_params = bytes([0xC1, len(calling_tsap)]) + calling_tsap + \
                  bytes([0xC2, len(called_tsap)]) + called_tsap + \
                  bytes([0xC0, 0x01, 0x07])
    cotp_header = bytes([len(cotp_params) + 6, 0xE0, 0x00, 0x01, 0x00, 0x01, 0x00])
    payload = cotp_header + cotp_params
    tpkt = bytes([0x03, 0x00, (4 + len(payload)) >> 8 & 0xFF, (4 + len(payload)) & 0xFF]) + payload
    return tpkt


def build_s7_setup(pdu_ref=1, pdu_size=480):
    return bytes([
        0x03, 0x00, 0x00, 0x19,
        0x02, 0xF0, 0x80,
        0x32, 0x01,
        0x00, 0x00,
        0x00, pdu_ref,
        0x00, 0x08,
        0x00, 0x00,
        0xF0, 0x00,
        0x00, 0x08,
        0x00, 0x08,
        (pdu_size >> 8) & 0xFF, pdu_size & 0xFF,
    ])


def build_s7_read(db_number=1, offset=0, size=4, pdu_ref=2):
    full_addr = offset << 3
    param = bytes([
        0x12, 0x0A,       # Spec type, Length of following (10 bytes)
        0x10, 0x02,       # Syntax ID (S7 any), Transport size (byte)
        (size >> 8) & 0xFF, size & 0xFF,  # Number of elements
        (db_number >> 8) & 0xFF, db_number & 0xFF,  # DB Number (before Area!)
        0x84,             # Area = DB (after DB Number!)
        (full_addr >> 16) & 0xFF, (full_addr >> 8) & 0xFF, full_addr & 0xFF,  # Address
    ])
    s7_header = bytes([0x32, 0x01, 0x00, 0x00, 0x00, pdu_ref])
    s7_header += struct.pack(">H", len(param) + 2)
    s7_header += struct.pack(">H", 0)
    s7_header += bytes([0x04, 0x00, 0x01])
    s7_header += param
    payload = bytes([0x02, 0xF0, 0x80]) + s7_header
    tpkt_len = 4 + len(payload)
    return bytes([0x03, 0x00, (tpkt_len >> 8) & 0xFF, tpkt_len & 0xFF]) + payload


def recv_tpkt(sock, timeout=5.0):
    sock.settimeout(timeout)
    header = sock.recv(4)
    if len(header) < 4:
        raise ConnectionError(f"Incomplete TPKT header: {len(header)} bytes")
    if header[0] != 0x03:
        raise ConnectionError(f"Invalid TPKT version: 0x{header[0]:02X}")
    tpkt_len = struct.unpack(">H", header[2:4])[0]
    remaining = tpkt_len - 4
    data = header
    while len(data) < tpkt_len:
        chunk = sock.recv(tpkt_len - len(data))
        if not chunk:
            break
        data += chunk
    return data


def run_tests(host, port):
    errors = []
    print("=" * 60)
    print(f"  S7 协议栈验证: {host}:{port}")
    print("=" * 60)

    # Test 1: COTP CR
    print("\n[Test 1] COTP CR 连接请求")
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5.0)
        sock.connect((host, port))
        cr = build_cotp_cr(0, 1)
        print(f"  发送 COTP CR ({len(cr)} bytes): {cr.hex()}")
        sock.sendall(cr)
        resp = recv_tpkt(sock, 5.0)
        print(f"  收到响应 ({len(resp)} bytes): {resp.hex()}")
        if len(resp) < 6:
            errors.append("COTP CC: 响应太短")
        elif resp[5] != 0xD0:
            errors.append(f"COTP CC: PDU Type 错误 0x{resp[5]:02X} (期望 0xD0)")
        else:
            print(f"  COTP CC 验证通过! PDU Type=0xD0")
        sock.close()
    except socket.timeout:
        errors.append("COTP CR: 超时无响应 - P0 Bug未修复!")
        print(f"  FAIL: 超时无响应")
    except Exception as e:
        errors.append(f"COTP CR: {e}")
        print(f"  FAIL: {e}")

    # Test 2: S7 Setup Communication
    print("\n[Test 2] S7 Setup Communication")
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5.0)
        sock.connect((host, port))
        sock.sendall(build_cotp_cr(0, 1))
        recv_tpkt(sock)
        pdu_ref = 1
        sock.sendall(build_s7_setup(pdu_ref=pdu_ref))
        resp = recv_tpkt(sock, 5.0)
        print(f"  收到响应 ({len(resp)} bytes): {resp.hex()}")
        if len(resp) >= 19:
            # Reserved
            if resp[9] != 0x00 or resp[10] != 0x00:
                errors.append(f"S7 Setup: Reserved 非零: 0x{resp[9]:02X}{resp[10]:02X}")
            else:
                print(f"  Reserved: 0x0000 OK")
            # PDU Reference
            resp_ref = struct.unpack(">H", resp[11:13])[0]
            if resp_ref != pdu_ref:
                errors.append(f"S7 Setup: PDU Ref 不匹配: {resp_ref} != {pdu_ref}")
            else:
                print(f"  PDU Reference: {resp_ref} OK")
            # Error Class/Code
            if resp[17] != 0 or resp[18] != 0:
                errors.append(f"S7 Setup: Error Class={resp[17]}, Code={resp[18]}")
            else:
                print(f"  Error Class/Code: 0/0 OK")
            # PDU Size
            if len(resp) >= 27:
                neg_pdu = struct.unpack(">H", resp[25:27])[0]
                print(f"  协商 PDU Size: {neg_pdu}")
        sock.close()
    except socket.timeout:
        errors.append("S7 Setup: 超时无响应")
        print(f"  FAIL: 超时无响应")
    except Exception as e:
        errors.append(f"S7 Setup: {e}")
        print(f"  FAIL: {e}")

    # Test 3: S7 Read
    print("\n[Test 3] S7 Read DB1.DBD0")
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5.0)
        sock.connect((host, port))
        sock.sendall(build_cotp_cr(0, 1))
        recv_tpkt(sock)
        sock.sendall(build_s7_setup(pdu_ref=1))
        recv_tpkt(sock)
        pdu_ref = 2
        sock.sendall(build_s7_read(1, 0, 4, pdu_ref))
        resp = recv_tpkt(sock, 5.0)
        print(f"  收到响应 ({len(resp)} bytes): {resp.hex()}")
        if len(resp) >= 19:
            if resp[9] != 0x00 or resp[10] != 0x00:
                errors.append(f"S7 Read: Reserved 非零")
            else:
                print(f"  Reserved: 0x0000 OK")
            resp_ref = struct.unpack(">H", resp[11:13])[0]
            if resp_ref != pdu_ref:
                errors.append(f"S7 Read: PDU Ref 不匹配: {resp_ref} != {pdu_ref}")
            else:
                print(f"  PDU Reference: {resp_ref} OK")
            if resp[17] != 0 or resp[18] != 0:
                errors.append(f"S7 Read: Error Class={resp[17]}, Code={resp[18]}")
            else:
                print(f"  Error Class/Code: 0/0 OK")
        sock.close()
    except socket.timeout:
        errors.append("S7 Read: 超时无响应")
        print(f"  FAIL: 超时无响应")
    except Exception as e:
        errors.append(f"S7 Read: {e}")
        print(f"  FAIL: {e}")

    # Test 4: SZL Read
    print("\n[Test 4] SZL Read (Module Identification)")
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5.0)
        sock.connect((host, port))
        sock.sendall(build_cotp_cr(0, 1))
        recv_tpkt(sock)
        sock.sendall(build_s7_setup(pdu_ref=1))
        recv_tpkt(sock)
        # SZL Read: area=0x00, SZL ID=0x0011
        szl_req = bytes([
            0x03, 0x00, 0x00, 0x1F,  # TPKT length=31
            0x02, 0xF0, 0x80,        # COTP DT
            0x32, 0x01, 0x00, 0x00,  # S7 Job
            0x00, 0x03,              # PDU Reference = 3
            0x00, 0x0E,              # Parameter Length = 14
            0x00, 0x00,              # Data Length = 0
            0x04, 0x00, 0x01,        # Function=Read Var, Reserved, Item Count=1
            0x12, 0x0A, 0x10, 0x04,  # Item: Spec type, Len, Syntax ID, Transport
            0x00, 0x08,              # Number of elements = 8
            0x00, 0x00,              # DB Number = 0 (SZL uses area 0x00)
            0x00,                    # Area = 0x00 (SZL)
            0x11, 0x00, 0x00,        # SZL ID(2) + SZL Index(1) in address field
        ])
        sock.sendall(szl_req)
        resp = recv_tpkt(sock, 5.0)
        print(f"  收到响应 ({len(resp)} bytes): {resp.hex()}")
        if len(resp) >= 19:
            if resp[8] != 0x03:
                errors.append(f"SZL: Msg Type 错误 0x{resp[8]:02X}")
            else:
                print(f"  Msg Type: 0x03 (Ack Data) OK")
            if resp[9] != 0x00 or resp[10] != 0x00:
                errors.append(f"SZL: Reserved 非零")
            else:
                print(f"  Reserved: 0x0000 OK")
            resp_ref = struct.unpack(">H", resp[11:13])[0]
            if resp_ref != 3:
                errors.append(f"SZL: PDU Ref 不匹配: {resp_ref} != 3")
            else:
                print(f"  PDU Reference: {resp_ref} OK")
            if resp[17] != 0 or resp[18] != 0:
                errors.append(f"SZL: Error Class={resp[17]}, Code={resp[18]}")
            else:
                print(f"  Error Class/Code: 0/0 OK")
        sock.close()
    except socket.timeout:
        errors.append("SZL: 超时无响应")
        print(f"  FAIL: 超时无响应")
    except Exception as e:
        errors.append(f"SZL: {e}")
        print(f"  FAIL: {e}")

    print("\n" + "=" * 60)
    if errors:
        print(f"  验证失败! {len(errors)} 个错误:")
        for i, err in enumerate(errors, 1):
            print(f"    {i}. {err}")
    else:
        print(f"  全部验证通过!")
    print("=" * 60)
    return len(errors) == 0


def main():
    host = "127.0.0.1"
    port = 1102

    # 在后台线程启动 S7 服务器
    from protoforge.protocols.s7.server import S7Server
    from protoforge.models.device import DeviceConfig, PointConfig

    server = S7Server()
    loop = asyncio.new_event_loop()

    async def start_server():
        await server.start({"host": host, "port": port, "rack": 0, "slot": 1})
        device = DeviceConfig(
            id="test-device-001",
            name="Test S7-1200",
            protocol="s7",
            points=[
                PointConfig(name="temperature", address="DB1.DBD0", data_type="float32", access="rw", generator_type="sine"),
            ],
            protocol_config={"rack": 0, "slot": 1},
        )
        await server.create_device(device)
        print(f"S7 Server started on {host}:{port}")

    loop.run_until_complete(start_server())

    # 在线程中运行事件循环
    def run_loop():
        loop.run_forever()

    t = threading.Thread(target=run_loop, daemon=True)
    t.start()

    # 等待服务器就绪
    time.sleep(0.5)

    # 运行测试
    success = run_tests(host, port)

    # 停止服务器
    loop.call_soon_threadsafe(loop.stop)
    t.join(timeout=2)

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
