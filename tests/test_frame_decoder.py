"""v1.9.0 报文字段级解析器测试：9 协议解码 + 校验失败检出 + 截断容错。

样例帧取自黄金用例同源构造（与 ProtoForge 自身实现严格一致），
校验和类字段（CRC16/CS/BCC）在测试内按标准重算，保证黄金确定性。
"""

import struct

import pytest

from protoforge.testing.frame_decoder import decode_frame, supported_protocols


def hexframe(h: str) -> bytes:
    return bytes.fromhex(h.replace(" ", ""))


def crc16(buf: bytes) -> int:
    crc = 0xFFFF
    for b in buf:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc & 0xFFFF


def field_names(result: dict) -> list[str]:
    return [f["name"] for f in result["fields"]]


# ---------------------------------------------------------------------------
# 注册表
# ---------------------------------------------------------------------------

def test_supported_protocols_at_least_8():
    assert len(supported_protocols()) >= 8
    for p in ("modbus_tcp", "modbus_rtu", "s7", "iec104", "dlt645",
              "cjt188", "fins", "mc", "mewtocol"):
        assert p in supported_protocols()


def test_unsupported_protocol_raises():
    with pytest.raises(ValueError, match="Unsupported protocol"):
        decode_frame("modbus_ascii", b"\x01")


# ---------------------------------------------------------------------------
# Modbus
# ---------------------------------------------------------------------------

def test_modbus_tcp_request_fields():
    r = decode_frame("modbus_tcp", hexframe("54 1D 00 00 00 06 01 03 00 00 00 0A"))
    assert r["errors"] == []
    assert "Read Holding Registers" in r["summary"]
    names = field_names(r)
    assert "Transaction ID" in names and "Unit ID" in names
    pdu = next(f for f in r["fields"] if f["name"] == "PDU")
    child_names = [c["name"] for c in pdu["children"]]
    assert "Start Address" in child_names and "Quantity" in child_names


def test_modbus_tcp_response_detected():
    r = decode_frame("modbus_tcp", hexframe("54 1D 00 00 00 07 01 03 04 41 BC 00 00"))
    assert r["errors"] == []
    assert "响应" in r["summary"]


def test_modbus_tcp_mbap_length_mismatch_flagged():
    r = decode_frame("modbus_tcp", hexframe("54 1D 00 00 00 99 01 03 00 00 00 0A"))
    assert any("MBAP length" in e for e in r["errors"])


def test_modbus_rtu_crc_check():
    body = hexframe("01 03 04 41 A0 00 00")
    r = decode_frame("modbus_rtu", body + struct.pack("<H", crc16(body)))
    assert r["errors"] == []
    assert "响应" in r["summary"]
    r_bad = decode_frame("modbus_rtu", body + b"\x00\x00")
    assert any("CRC" in e for e in r_bad["errors"])


# ---------------------------------------------------------------------------
# S7
# ---------------------------------------------------------------------------

def test_s7_read_response():
    r = decode_frame("s7", hexframe(
        "03 00 00 1D 02 F0 80 32 03 00 00 00 01 00 0E 00 08 00 00 04 01"
        " FF 04 00 20 41 BC 00 00"))
    assert r["errors"] == []
    assert "Read Var" in r["summary"] and "Ack_Data" in r["summary"]
    names = field_names(r)
    assert "TPKT Length" in names and "COTP PDU Type" in names
    s7 = next(f for f in r["fields"] if f["name"] == "S7 PDU")
    assert "PDU Reference" in [c["name"] for c in s7["children"]]


def test_s7_tpkt_length_mismatch_flagged():
    r = decode_frame("s7", hexframe(
        "03 00 00 1B 02 F0 80 32 03 00 00 00 01 00 0E 00 08 00 00 04 01"
        " FF 04 00 20 41 BC 00 00"))
    assert any("TPKT length" in e for e in r["errors"])


def test_s7_cotp_cr_recognized():
    r = decode_frame("s7", hexframe(
        "03 00 00 16 11 E0 00 00 00 01 00 C1 02 01 00 C2 02 01 02 C0 01 07"))
    assert "COTP" in r["summary"]


# ---------------------------------------------------------------------------
# IEC 104
# ---------------------------------------------------------------------------

def test_iec104_u_format_startdt():
    r = decode_frame("iec104", hexframe("68 04 07 00 00 00"))
    assert r["errors"] == []
    assert "STARTDT_ACT" in r["summary"]


def test_iec104_gi_activation_confirm():
    r = decode_frame("iec104", hexframe(
        "68 0E 02 00 02 00 64 01 07 00 01 00 00 00 00 14"))
    assert r["errors"] == []
    assert "总召" in r["summary"] and "激活确认" in r["summary"]
    asdu = next(f for f in r["fields"] if f["name"] == "ASDU")
    assert "CA 公共地址" in [c["name"] for c in asdu["children"]]


def test_iec104_monitor_float_value():
    # M_ME_NC_1 (TI=13) IOA=1 float 220.5, COT=20 响应总召
    payload = struct.pack("<f", 220.5) + b"\x00"
    ioa = bytes([1, 0, 0])
    asdu = bytes([13, 1, 20, 0]) + struct.pack("<H", 1) + ioa + payload
    apdu = struct.pack("<HH", 0, 0) + asdu  # 控制域(4) + ASDU
    r = decode_frame("iec104", bytes([0x68, len(apdu)]) + apdu)
    assert r["errors"] == []
    assert "短浮点" in r["summary"]
    asdu_f = next(f for f in r["fields"] if f["name"] == "ASDU")
    obj = asdu_f["children"][-1]
    assert "浮点值" in [c["name"] for c in obj["children"]]


# ---------------------------------------------------------------------------
# DL/T 645（6/7 字节地址两种变体）
# ---------------------------------------------------------------------------

def test_dlt645_a6_variant_and_checksum():
    f = bytearray(hexframe("68 01 02 03 04 05 06 F9 68 11 04 33 33 33 33 00 16"))
    f[15] = sum(f[1:15]) & 0xFF
    r = decode_frame("dlt645", bytes(f))
    assert r["errors"] == []
    assert "060504030201" in r["summary"]  # 表号 BCD 小端
    # 线上原始 DI（+0x33 传输后的 33 33）；语义注解才是 00010000 读电能
    assert "3333" in [ff["value"] for ff in r["fields"] if ff["name"] == "数据标识 DI"]


def test_dlt645_standard_variant():
    f = bytearray(hexframe("68 01 02 03 04 05 06 68 11 04 33 33 33 33 00 16"))
    f[14] = sum(f[1:14]) & 0xFF
    r = decode_frame("dlt645", bytes(f))
    assert r["errors"] == []
    assert any(ff["name"] == "帧起始符 2" for ff in r["fields"])


def test_dlt645_checksum_failure_flagged():
    f = bytearray(hexframe("68 01 02 03 04 05 06 F9 68 11 04 33 33 33 33 00 16"))
    f[15] = (sum(f[1:15]) + 1) & 0xFF  # 校验和错 1
    r = decode_frame("dlt645", bytes(f))
    assert any("CS" in e for e in r["errors"])


# ---------------------------------------------------------------------------
# CJ/T 188
# ---------------------------------------------------------------------------

def test_cjt188_checksum_and_end():
    f = bytearray(hexframe("68 10 20 30 40 50 60 70 91 04 02 65 08 00 00 16"))
    f[14] = sum(f[1:14]) & 0xFF
    r = decode_frame("cjt188", bytes(f))
    assert r["errors"] == []
    assert "70605040302010" in r["summary"]


def test_cjt188_bad_end_flagged():
    f = bytearray(hexframe("68 10 20 30 40 50 60 70 91 04 02 65 08 00 00 16"))
    f[14] = sum(f[1:14]) & 0xFF
    f[15] = 0x17  # 结束符错误
    r = decode_frame("cjt188", bytes(f))
    assert any("结束符" in e for e in r["errors"])


# ---------------------------------------------------------------------------
# FINS
# ---------------------------------------------------------------------------

def test_fins_tcp_read_command():
    fins = b"FINS" + struct.pack(">I", 26) + struct.pack(">I", 2) + struct.pack(">I", 0)
    frame = bytes([0x80, 0, 2, 0, 5, 0, 0, 1, 0, 1, 0x01, 0x01,
                   0x82, 0x00, 0x00, 0x00, 0x00, 0x0A])
    r = decode_frame("fins", fins + frame)
    assert r["errors"] == []
    assert "读" in r["summary"] and "MRC=0x01" in r["summary"]
    dg = next(f for f in r["fields"] if f["name"] == "FINS 数据报")
    assert "SID 服务号" in [c["name"] for c in dg["children"]]


def test_fins_missing_magic():
    r = decode_frame("fins", b"\x00\x01\x02\x03\x00\x00\x00\x00")
    assert any("FINS magic" in e for e in r["errors"])


# ---------------------------------------------------------------------------
# MC (SLMP 3E)
# ---------------------------------------------------------------------------

def test_mc_3e_batch_read():
    r = decode_frame("mc", hexframe(
        "50 00 00 FF FF 03 00 0C 00 10 00 01 04 01 00 64 00 00 90 04 00"))
    assert r["errors"] == []
    assert "批量读" in r["summary"]
    names = field_names(r)
    assert "设备字段" in names and "点数" in names


def test_mc_bad_subheader():
    r = decode_frame("mc", hexframe("51 00 00 FF FF 03 00 0C 00 10 00"))
    assert "非 3E" in r["summary"]


# ---------------------------------------------------------------------------
# MEWTOCOL
# ---------------------------------------------------------------------------

def test_mewtocol_request_bcc():
    body = "%01#RD0010001"
    bcc = 0
    for ch in body:
        bcc ^= ord(ch)
    r = decode_frame("mewtocol", (body + f"{bcc:02X}\r").encode())
    assert r["errors"] == []
    assert "RD" in r["summary"] and "请求" in r["summary"]


def test_mewtocol_bcc_failure_flagged():
    r = decode_frame("mewtocol", b"%01#RD0010001ZZ\r")
    assert any("BCC" in e for e in r["errors"])


def test_mewtocol_missing_cr_flagged():
    body = "%01#RD0010001"
    bcc = 0
    for ch in body:
        bcc ^= ord(ch)
    r = decode_frame("mewtocol", (body + f"{bcc:02X}").encode())
    assert any("CR" in e for e in r["errors"])


# ---------------------------------------------------------------------------
# 截断容错：任何解码器收到短帧都不应抛异常
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("protocol", sorted([
    "modbus_tcp", "modbus_rtu", "s7", "iec104", "dlt645", "cjt188",
    "fins", "mc", "mewtocol"]))
def test_truncated_frames_never_raise(protocol):
    for raw in (b"", b"\x01", b"\x68\x00", b"\x03\x00\x00", b"FINS"):
        result = decode_frame(protocol, raw)
        assert isinstance(result, dict)
        assert "fields" in result and "errors" in result
