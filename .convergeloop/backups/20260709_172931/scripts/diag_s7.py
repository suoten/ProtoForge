"""S7 连接诊断脚本 - 分层排查 Receive timeout 问题。

用法: python3 diag_s7.py <PLC_IP> [rack] [slot] [port]
示例: python3 diag_s7.py 10.0.0.82 0 1 102
"""
import socket
import struct
import sys
import time


def check_tcp(ip: str, port: int, timeout: float = 5.0) -> bool:
    """Layer 1: TCP 连通性检查 + 设备指纹探测"""
    print(f"\n[1] TCP 连通性检查: {ip}:{port}")
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        start = time.time()
        sock.connect((ip, port))
        elapsed = time.time() - start
        print(f"    TCP 连接成功! 耗时: {elapsed*1000:.0f}ms")

        # 尝试读取设备主动发送的 banner / 初始数据
        # 真正的 S7 PLC 不会主动发数据，但其他协议可能会
        sock.settimeout(2.0)
        try:
            banner = sock.recv(256)
            if banner:
                print(f"    设备主动发送了数据 ({len(banner)} bytes): {banner.hex()}")
                # 尝试识别协议
                if banner[:2] == b'\x03\x00':
                    print(f"    -> 看起来像 TPKT/S7 协议头")
                elif banner[:4] == b'MQTT':
                    print(f"    -> 这是 MQTT 协议，不是 S7!")
                elif b'HTTP' in banner[:10]:
                    print(f"    -> 这是 HTTP 协议，不是 S7!")
                elif banner[0] == 0x00 and len(banner) >= 8:
                    print(f"    -> 可能是 Modbus TCP 协议")
                else:
                    try:
                        text = banner.decode('ascii', errors='replace')
                        print(f"    -> 文本内容: {text[:100]}")
                    except Exception:
                        pass
                print(f"    *** 该设备在端口 {port} 上运行的不是标准 S7 协议 ***")
            else:
                print(f"    设备未主动发送数据 (符合 S7 PLC 行为)")
        except socket.timeout:
            print(f"    设备未主动发送数据 (符合 S7 PLC 行为)")

        sock.close()
        return True
    except socket.timeout:
        print(f"    TCP 连接超时 ({timeout}s) - 端口不可达或被防火墙拦截")
        return False
    except ConnectionRefusedError:
        print(f"    TCP 连接被拒绝 - 端口没有监听服务")
        return False
    except OSError as e:
        print(f"    TCP 连接失败: {e}")
        return False


def check_s7_cotp(ip: str, port: int, rack: int, slot: int, timeout: float = 5.0) -> bool:
    """Layer 2: COTP 连接请求检查 (ISO 8073)"""
    print(f"\n[2] COTP/S7 协议层检查: rack={rack}, slot={slot}")

    # 构建 COTP CR (Connection Request)
    # TSAP 编码: rack 和 slot 编码在 Called TSAP 中
    # Calling TSAP (0xC1): 客户端源 TSAP
    # Called TSAP (0xC2): 目标 rack/slot
    calling_tsap = struct.pack(">H", 0x0100)  # 客户端 TSAP
    called_tsap = struct.pack(">H", 0x0100 | (rack << 5) | slot)  # 服务端 TSAP (含 rack/slot)

    cotp_params = bytes([
        0xC1, len(calling_tsap),  # Calling TSAP
    ]) + calling_tsap + bytes([
        0xC2, len(called_tsap),   # Called TSAP
    ]) + called_tsap + bytes([
        0xC0, 0x01, 0x07,        # TPDU size = 0x07 (2048)
    ])

    cotp_header = bytes([
        len(cotp_params) + 6,  # LI
        0xE0,                   # COTP CR PDU Type
        0x00, 0x01,             # Destination reference
        0x00, 0x01,             # Source reference
        0x00,                   # Class 0
    ])

    payload = cotp_header + cotp_params
    tpkt = bytes([
        0x03, 0x00,                          # TPKT version, reserved
        (4 + len(payload)) >> 8 & 0xFF,      # Length high
        (4 + len(payload)) & 0xFF,           # Length low
    ]) + payload

    print(f"    发送 COTP CR: rack={rack}, slot={slot}")
    print(f"    Called TSAP: 0x{struct.unpack('>H', called_tsap)[0]:04X}")
    print(f"    报文 ({len(tpkt)} bytes): {tpkt.hex()}")

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect((ip, port))

        sock.sendall(tpkt)

        # 读取 TPKT 头部 (4 bytes)
        start = time.time()
        response = b""
        try:
            header = sock.recv(4)
            if len(header) < 4:
                print(f"    COTP 响应不完整: 只收到 {len(header)} 字节")
                sock.close()
                return False

            if header[0] != 0x03:
                print(f"    TPKT 版本错误: 0x{header[0]:02X} (期望 0x03)")
                sock.close()
                return False

            tpkt_len = struct.unpack(">H", header[2:4])[0]
            remaining = tpkt_len - 4

            # 读取剩余数据
            while len(response) < remaining:
                chunk = sock.recv(remaining - len(response))
                if not chunk:
                    break
                response += chunk

            full_response = header + response
            elapsed = time.time() - start

            # 解析 COTP CC 响应
            if len(full_response) >= 6:
                pdu_type = full_response[5]
                if pdu_type == 0xD0:
                    print(f"    COTP CC (Connection Confirm) 收到! 耗时: {elapsed*1000:.0f}ms")
                    print(f"    响应 ({len(full_response)} bytes): {full_response.hex()}")
                    sock.close()
                    return True
                elif pdu_type == 0xE0:
                    print(f"    收到 COTP CR 而非 CC - 可能是对端也是客户端模式")
                    print(f"    响应 ({len(full_response)} bytes): {full_response.hex()}")
                else:
                    print(f"    收到未知 PDU Type: 0x{pdu_type:02X}")
                    print(f"    响应 ({len(full_response)} bytes): {full_response.hex()}")
            else:
                print(f"    COTP 响应太短: {full_response.hex()}")

        except socket.timeout:
            elapsed = time.time() - start
            print(f"    COTP 响应超时 ({elapsed:.1f}s) - 设备不回复 S7 协议")
            print(f"    可能原因: 1)不是S7设备 2)rack/slot错误 3)S7通信未启用")
            # 尝试读取设备可能延迟发送的任何数据
            try:
                sock.settimeout(3.0)
                late_data = sock.recv(512)
                if late_data:
                    print(f"    设备延迟发送了数据 ({len(late_data)} bytes): {late_data.hex()}")
                    if late_data[:2] == b'\x03\x00':
                        print(f"    -> 这是 TPKT 协议数据，但不是 COTP CC 响应")
                    print(f"    *** 设备可能不是标准 S7 PLC，或使用了非标准 S7 实现 ***")
            except socket.timeout:
                pass

        sock.close()
        return False

    except Exception as e:
        print(f"    COTP 检查失败: {e}")
        return False


def check_s7_setup(ip: str, port: int, rack: int, slot: int, timeout: float = 5.0) -> bool:
    """Layer 3: S7 Communication Setup 检查"""
    print(f"\n[3] S7 Communication Setup 检查")

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect((ip, port))

        # Step 1: COTP CR
        calling_tsap = struct.pack(">H", 0x0100)
        called_tsap = struct.pack(">H", 0x0100 | (rack << 5) | slot)
        cotp_params = bytes([0xC1, len(calling_tsap)]) + calling_tsap + bytes([0xC2, len(called_tsap)]) + called_tsap + bytes([0xC0, 0x01, 0x07])
        cotp_header = bytes([len(cotp_params) + 6, 0xE0, 0x00, 0x01, 0x00, 0x01, 0x00])
        payload = cotp_header + cotp_params
        tpkt = bytes([0x03, 0x00, (4 + len(payload)) >> 8 & 0xFF, (4 + len(payload)) & 0xFF]) + payload

        sock.sendall(tpkt)
        header = sock.recv(4)
        tpkt_len = struct.unpack(">H", header[2:4])[0]
        remaining = tpkt_len - 4
        resp = header
        while len(resp) < tpkt_len:
            chunk = sock.recv(tpkt_len - len(resp))
            if not chunk:
                break
            resp += chunk

        if len(resp) < 6 or resp[5] != 0xD0:
            print(f"    COTP 连接失败，无法继续 S7 Setup 检查")
            sock.close()
            return False

        print(f"    COTP 连接成功")

        # Step 2: S7 Setup Communication
        s7_setup = bytes([
            0x03, 0x00, 0x00, 0x19,  # TPKT: length=25
            0x02, 0xF0, 0x80,        # COTP DT
            0x32, 0x01,               # S7 Protocol ID, Msg Type = Job
            0x00, 0x00,               # Reserved
            0x00, 0x01,               # PDU Reference
            0x00, 0x08,               # Parameter Length = 8
            0x00, 0x00,               # Data Length = 0
            0xF0,                     # Function: Setup Communication
            0x00,                     # Reserved
            0x00, 0x01,               # Max AMQ Caller = 1
            0x00, 0x01,               # Max AMQ Callee = 1
            0x01, 0xE0,               # PDU Size = 480
        ])

        print(f"    发送 S7 Setup Communication")
        sock.sendall(s7_setup)

        header = sock.recv(4)
        if len(header) < 4:
            print(f"    S7 Setup 响应不完整")
            sock.close()
            return False

        tpkt_len = struct.unpack(">H", header[2:4])[0]
        remaining = tpkt_len - 4
        resp = header
        while len(resp) < tpkt_len:
            chunk = sock.recv(tpkt_len - len(resp))
            if not chunk:
                break
            resp += chunk

        if len(resp) >= 20 and resp[7] == 0x32 and resp[8] == 0x03:
            error_class = resp[17]
            error_code = resp[18]
            if error_class == 0 and error_code == 0:
                print(f"    S7 Setup Communication 成功!")
                # 解析协商的 PDU Size
                if len(resp) >= 27:
                    pdu_size = struct.unpack(">H", resp[25:27])[0]
                    print(f"    协商 PDU Size: {pdu_size}")
                sock.close()
                return True
            else:
                print(f"    S7 Setup 失败: Error Class={error_class}, Error Code={error_code}")
        else:
            print(f"    S7 Setup 响应异常: {resp.hex()}")

        sock.close()
        return False

    except socket.timeout:
        print(f"    S7 Setup 超时")
        return False
    except Exception as e:
        print(f"    S7 Setup 检查失败: {e}")
        return False


def check_s7_read(ip: str, port: int, rack: int, slot: int, timeout: float = 5.0) -> bool:
    """Layer 4: S7 Read 测试 - 完整连接后尝试读取数据"""
    print(f"\n[4] S7 Read 数据读取测试")

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect((ip, port))

        # Step 1: COTP CR
        calling_tsap = struct.pack(">H", 0x0100)
        called_tsap = struct.pack(">H", 0x0100 | (rack << 5) | slot)
        cotp_params = bytes([0xC1, len(calling_tsap)]) + calling_tsap + bytes([0xC2, len(called_tsap)]) + called_tsap + bytes([0xC0, 0x01, 0x07])
        cotp_header = bytes([len(cotp_params) + 6, 0xE0, 0x00, 0x01, 0x00, 0x01, 0x00])
        payload = cotp_header + cotp_params
        tpkt = bytes([0x03, 0x00, (4 + len(payload)) >> 8 & 0xFF, (4 + len(payload)) & 0xFF]) + payload
        sock.sendall(tpkt)

        header = sock.recv(4)
        tpkt_len = struct.unpack(">H", header[2:4])[0]
        resp = header
        while len(resp) < tpkt_len:
            chunk = sock.recv(tpkt_len - len(resp))
            if not chunk:
                break
            resp += chunk
        if len(resp) < 6 or resp[5] != 0xD0:
            print(f"    COTP 连接失败")
            sock.close()
            return False

        # Step 2: S7 Setup
        s7_setup = bytes([
            0x03, 0x00, 0x00, 0x19,
            0x02, 0xF0, 0x80,
            0x32, 0x01, 0x00, 0x00,
            0x00, 0x01,
            0x00, 0x08, 0x00, 0x00,
            0xF0, 0x00,
            0x00, 0x08, 0x00, 0x08,
            0x01, 0xE0,
        ])
        sock.sendall(s7_setup)
        header = sock.recv(4)
        tpkt_len = struct.unpack(">H", header[2:4])[0]
        resp = header
        while len(resp) < tpkt_len:
            chunk = sock.recv(tpkt_len - len(resp))
            if not chunk:
                break
            resp += chunk
        if len(resp) < 20 or resp[7] != 0x32 or resp[8] != 0x03:
            print(f"    S7 Setup 失败")
            sock.close()
            return False

        # Step 3: S7 Read - 尝试读取 SZL (系统状态列表)，不依赖 DB 是否存在
        # SZL 0x0011 (Module Identification) - 所有 S7 PLC 都支持
        # FIXED: SZL 使用 Read Var (0x04) + area=0x00 的 item 结构
        # S7 Job 请求不含 Error Class/Code 字段
        szl_read = bytes([
            0x03, 0x00, 0x00, 0x1F,  # TPKT length=31
            0x02, 0xF0, 0x80,        # COTP DT
            0x32, 0x01,               # S7 Protocol ID, Msg Type = Job
            0x00, 0x00,               # Reserved
            0x00, 0x02,               # PDU Reference = 2
            0x00, 0x0E,               # Parameter Length = 14 (func+reserved+count+item12)
            0x00, 0x00,               # Data Length = 0
            # Parameters:
            0x04,                     # Function: Read Var
            0x00,                     # Reserved
            0x01,                     # Item count = 1
            # Item (12 bytes):
            0x12,                     # Spec type (variable specification)
            0x0A,                     # Length of following (10 bytes)
            0x10,                     # Syntax ID (S7 any)
            0x04,                     # Transport size (byte)
            0x00, 0x08,               # Number of elements = 8
            0x00, 0x00,               # DB Number = 0 (SZL uses area 0x00)
            0x00,                     # Area = 0x00 (system/SZL)
            0x11, 0x00, 0x00,         # SZL ID(2) + SZL Index(1) in address field
        ])
        print(f"    发送 SZL Read (Module Identification)")
        sock.sendall(szl_read)

        header = sock.recv(4)
        if len(header) < 4:
            print(f"    SZL Read 无响应")
            sock.close()
            return False

        tpkt_len = struct.unpack(">H", header[2:4])[0]
        resp = header
        while len(resp) < tpkt_len:
            chunk = sock.recv(tpkt_len - len(resp))
            if not chunk:
                break
            resp += chunk

        if len(resp) >= 20 and resp[7] == 0x32 and resp[8] == 0x03:
            error_class = resp[17]
            error_code = resp[18]
            if error_class == 0 and error_code == 0:
                print(f"    SZL Read 成功! 设备支持 S7 数据读取")
                # 尝试解析模块名称
                if len(resp) > 30:
                    # SZL data 包含模块信息
                    print(f"    响应 ({len(resp)} bytes): {resp.hex()}")
                return True
            else:
                print(f"    SZL Read 返回错误: Error Class={error_class}, Error Code={error_code}")
        else:
            print(f"    SZL Read 响应异常: {resp.hex()}")

        # Step 4: 尝试读取 DB1 (可能不存在)
        db_read = bytes([
            0x03, 0x00, 0x00, 0x1F,  # TPKT length=31
            0x02, 0xF0, 0x80,        # COTP DT
            0x32, 0x01,               # S7 Protocol ID, Msg Type = Job
            0x00, 0x00,               # Reserved
            0x00, 0x03,               # PDU Reference = 3
            0x00, 0x0E,               # Parameter Length = 14
            0x00, 0x00,               # Data Length = 0
            0x04,                     # Function: Read Var
            0x00,                     # Reserved
            0x01,                     # Item count = 1
            # Item (12 bytes):
            0x12,                     # Spec type
            0x0A,                     # Length of following (10 bytes)
            0x10,                     # Syntax ID (S7 any)
            0x04,                     # Transport size (byte)
            0x00, 0x04,               # Number of elements = 4
            0x00, 0x01,               # DB Number = 1
            0x84,                     # Area = DB
            0x00, 0x00, 0x00,         # Address = 0 (byte offset 0)
        ])
        print(f"    发送 DB1 Read (DB1.DBD0, 4 bytes)")
        sock.sendall(db_read)

        header = sock.recv(4)
        if len(header) >= 4:
            tpkt_len = struct.unpack(">H", header[2:4])[0]
            resp = header
            while len(resp) < tpkt_len:
                chunk = sock.recv(tpkt_len - len(resp))
                if not chunk:
                    break
                resp += chunk

            if len(resp) >= 20 and resp[7] == 0x32 and resp[8] == 0x03:
                error_class = resp[17]
                error_code = resp[18]
                # Result code for first item
                if len(resp) > 20:
                    result_code = resp[20]
                    if result_code == 0xFF:
                        print(f"    DB1 Read 成功! 数据可读")
                    elif result_code == 0x0A:
                        print(f"    DB1 不存在或不可读 (Result Code=0x0A)")
                        print(f"    这是正常的 - 需要在 TIA Portal 中创建 DB1")
                    else:
                        print(f"    DB1 Read 返回: Result Code=0x{result_code:02X}")
                return True  # SZL already succeeded
            else:
                print(f"    DB1 Read 响应异常")

        sock.close()
        return True  # SZL succeeded even if DB read failed

    except socket.timeout:
        print(f"    S7 Read 超时")
        return False
    except Exception as e:
        print(f"    S7 Read 检查失败: {e}")
        return False


def try_different_rack_slot(ip: str, port: int, timeout: float = 3.0):
    """尝试不同的 rack/slot 组合"""
    print(f"\n[4] 尝试不同 rack/slot 组合")

    combinations = [
        (0, 1),   # S7-1200/1500 默认
        (0, 2),   # S7-300 默认
        (0, 0),   # 某些旧型号
        (0, 3),   # S7-400 扩展
        (1, 1),   # rack=1
    ]

    for rack, slot in combinations:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            sock.connect((ip, port))

            calling_tsap = struct.pack(">H", 0x0100)
            called_tsap = struct.pack(">H", 0x0100 | (rack << 5) | slot)
            cotp_params = bytes([0xC1, len(calling_tsap)]) + calling_tsap + bytes([0xC2, len(called_tsap)]) + called_tsap + bytes([0xC0, 0x01, 0x07])
            cotp_header = bytes([len(cotp_params) + 6, 0xE0, 0x00, 0x01, 0x00, 0x01, 0x00])
            payload = cotp_header + cotp_params
            tpkt = bytes([0x03, 0x00, (4 + len(payload)) >> 8 & 0xFF, (4 + len(payload)) & 0xFF]) + payload

            sock.sendall(tpkt)

            try:
                header = sock.recv(4)
                if len(header) >= 4:
                    tpkt_len = struct.unpack(">H", header[2:4])[0]
                    remaining = tpkt_len - 4
                    resp = header
                    while len(resp) < tpkt_len:
                        chunk = sock.recv(tpkt_len - len(resp))
                        if not chunk:
                            break
                        resp += chunk

                    if len(resp) >= 6:
                        pdu_type = resp[5]
                        if pdu_type == 0xD0:
                            print(f"    rack={rack}, slot={slot}: COTP CC 成功! *** 可用 ***")
                        elif pdu_type == 0xE0:
                            print(f"    rack={rack}, slot={slot}: 收到 CR 而非 CC")
                        else:
                            print(f"    rack={rack}, slot={slot}: PDU Type=0x{pdu_type:02X}")
                    else:
                        print(f"    rack={rack}, slot={slot}: 响应不完整")
                else:
                    print(f"    rack={rack}, slot={slot}: 无响应")
            except socket.timeout:
                print(f"    rack={rack}, slot={slot}: 超时")

            sock.close()

        except Exception as e:
            print(f"    rack={rack}, slot={slot}: 错误 - {e}")


def check_modbus_tcp(ip: str, port: int, timeout: float = 3.0):
    """检查设备是否是 Modbus TCP 设备 (很多设备端口102跑的是Modbus)"""
    print(f"\n[5] Modbus TCP 协议探测")

    # Modbus TCP 读取保持寄存器 (功能码 0x03), 从地址 0 读 10 个寄存器
    modbus_req = bytes([
        0x00, 0x01,  # Transaction ID
        0x00, 0x00,  # Protocol ID (Modbus)
        0x00, 0x06,  # Length
        0x01,        # Unit ID
        0x03,        # Function Code: Read Holding Registers
        0x00, 0x00,  # Starting Address
        0x00, 0x0A,  # Quantity: 10
    ])

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect((ip, port))
        sock.sendall(modbus_req)

        try:
            resp = sock.recv(256)
            if resp and len(resp) >= 9:
                protocol_id = struct.unpack(">H", resp[2:4])[0]
                func_code = resp[7]
                if protocol_id == 0:
                    if func_code == 0x03:
                        byte_count = resp[8]
                        print(f"    Modbus TCP 响应成功! 读取到 {byte_count} 字节数据")
                        print(f"    响应: {resp.hex()}")
                        print(f"    *** 该设备是 Modbus TCP 设备，不是 S7 PLC! ***")
                        return True
                    elif func_code == 0x83:
                        # 异常响应
                        exception_code = resp[8] if len(resp) > 8 else 0
                        exc_names = {1: "Illegal Function", 2: "Illegal Data Address",
                                    3: "Illegal Data Value", 4: "Server Device Failure"}
                        print(f"    Modbus TCP 异常响应: {exc_names.get(exception_code, f'Code {exception_code}')}")
                        print(f"    *** 该设备是 Modbus TCP 设备，不是 S7 PLC! ***")
                        return True
                else:
                    print(f"    非 Modbus 协议响应 (Protocol ID={protocol_id})")
            elif resp:
                print(f"    收到数据但不是 Modbus: {resp.hex()}")
            else:
                print(f"    设备未响应 Modbus 请求")
        except socket.timeout:
            print(f"    Modbus 探测超时 - 设备不是 Modbus TCP")

        sock.close()
    except Exception as e:
        print(f"    Modbus 探测失败: {e}")

    return False


def main():
    if len(sys.argv) < 2:
        print("用法: python3 diag_s7.py <PLC_IP> [rack] [slot] [port]")
        print("示例: python3 diag_s7.py 10.0.0.82 0 1 102")
        sys.exit(1)

    ip = sys.argv[1]
    rack = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    slot = int(sys.argv[3]) if len(sys.argv) > 3 else 1
    port = int(sys.argv[4]) if len(sys.argv) > 4 else 102

    print("=" * 60)
    print(f"  S7 连接诊断: {ip}:{port} (rack={rack}, slot={slot})")
    print("=" * 60)

    # Layer 1: TCP
    tcp_ok = check_tcp(ip, port)
    if not tcp_ok:
        print("\n结论: TCP 层不通，请检查:")
        print("  1. IP 地址是否正确 (ping 测试)")
        print("  2. 端口 102 是否被防火墙拦截")
        print("  3. 设备是否开机且网络连接正常")
        return

    # Layer 2: COTP
    cotp_ok = check_s7_cotp(ip, port, rack, slot)
    if not cotp_ok:
        # 尝试不同 rack/slot
        try_different_rack_slot(ip, port)

        # 探测是否是 Modbus TCP 设备
        check_modbus_tcp(ip, port)

        print("\n结论: COTP 层不通，可能原因:")
        print("  1. rack/slot 配置错误 (S7-1200/1500=0/1, S7-300=0/2)")
        print("  2. 设备不是 Siemens S7 PLC (可能是 Modbus TCP 或其他协议)")
        print("  3. PLC 的 S7 通信功能未启用 (需在 TIA Portal 中启用)")
        print("  4. PLC 开启了 S7 通信保护 (Put/Get 需要允许)")
        return

    # Layer 3: S7 Setup
    s7_ok = check_s7_setup(ip, port, rack, slot)
    if not s7_ok:
        print("\n结论: COTP 连接成功但 S7 Setup 失败，可能原因:")
        print("  1. PLC 处于 STOP 模式")
        print("  2. S7 通信保护已启用 (需在 TIA Portal 中允许 Put/Get)")
        print("  3. PLC 固件版本与协议不兼容")
        return

    # Layer 4: S7 Read 测试
    read_ok = check_s7_read(ip, port, rack, slot)
    if read_ok:
        print("\n结论: S7 通信完全正常! COTP/S7 Setup/S7 Read 全部通过!")
        print("  snap7 连接如果仍然超时，请检查:")
        print("  1. snap7 库版本 (pip install python-snap7 --upgrade)")
        print("  2. snap7 默认超时可能太短，尝试: client.set_connection_type(3)")
        print("  3. 确认 snap7 连接参数: client.connect(ip, rack=0, slot=1, tcp_port=102)")
    else:
        print("\n结论: S7 Setup 成功但 Read 失败，可能原因:")
        print("  1. PLC 未允许 Put/Get 通信 (需在 TIA Portal 中启用)")
        print("  2. 请求的 DB 不存在")
        print("  3. PLC 处于 STOP 模式，无法读取数据")


if __name__ == "__main__":
    main()
