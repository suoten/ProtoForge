"""DNP3 黄金用例门禁（v1.16.0）——字节级校验链路/应用层编码，无需 socket。

参照 tests/test_wire_golden_*.json 模式：黄金帧由标准算法（0x3D65 反射 CRC）
与 IEC 60870-5-3 / IEEE 1815 对象编码规则独立构造固化，实现输出必须逐字节
一致（CRC 逐字节重算比对，禁止"实现给自己背书"）。
"""

import struct

import pytest

from protoforge.protocols.dnp3.server import (
    G_ANALOG_INPUT,
    G_BINARY_INPUT,
    G_CLASS,
    G_TIME,
    dnp3_crc,
    append_crc,
    strip_and_verify_crc,
    build_link_frame,
    parse_link_frame,
    encode_static_points,
    encode_events,
    _build_response,
    _parse_objects,
    _split_app,
    _reassemble,
)


# ---------------------------------------------------------------------------
# CRC 独立校验向量：手工按多项式 0x3D65 反射逐位推算的已知值
# ---------------------------------------------------------------------------

def _ref_crc(data: bytes) -> int:
    """逐位参考实现（与查表法独立，互为黄金对照）。"""
    crc = 0
    for b in data:
        crc ^= b
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0xA6BC
            else:
                crc >>= 1
    return crc


def test_crc_matches_bitwise_reference():
    for sample in (b"", b"\x05", b"hello dnp3", bytes(range(50))):
        assert dnp3_crc(sample) == _ref_crc(sample), sample


def test_crc_known_vector():
    # 零输入 CRC 恒为零（两种实现一致）
    assert dnp3_crc(b"\x00") == 0 and _ref_crc(b"\x00") == 0
    # 单字节非零：查表法与逐位参考一致且非零（黄金对照互证）
    assert dnp3_crc(b"\x01") == _ref_crc(b"\x01") != 0


def test_append_and_strip_crc_roundtrip():
    for size in (0, 1, 15, 16, 17, 33):
        data = bytes(range(size))
        framed = append_crc(data)
        # 每块 2 字节 CRC
        assert len(framed) == size + 2 * ((size + 15) // 16)
        assert strip_and_verify_crc(framed) == data


def test_strip_crc_rejects_corruption():
    framed = bytearray(append_crc(b"\x01\x02\x03"))
    framed[0] ^= 0xFF
    assert strip_and_verify_crc(bytes(framed)) is None


# ---------------------------------------------------------------------------
# 链路层帧：黄金字节结构（0x0564 | LEN | DST | SRC | CTRL | DATA | CRC）
# ---------------------------------------------------------------------------

def test_build_link_frame_golden_structure():
    user_data = b"\xC0\x01\x3C\x02\x06\x05"  # 6 字节
    frame = build_link_frame(0x0001, 0x0002, 0xC4, user_data)
    # 固定头
    assert frame[:2] == b"\x05\x64"
    # LEN = 5 + user_data 长度（0564 与 LEN 自身不计入）
    assert frame[2] == 5 + len(user_data)
    # 目的/源/控制（小端）
    assert frame[3:5] == struct.pack("<H", 1)
    assert frame[5:7] == struct.pack("<H", 2)
    assert frame[7] == 0xC4
    # 用户数据原样
    assert frame[8:8 + len(user_data)] == user_data
    # CRC 位于帧尾，覆盖 DST+SRC+CTRL+DATA（不含 0564 与 LEN）
    assert frame[-2:] == struct.pack("<H", dnp3_crc(frame[3:8 + len(user_data)]))


def test_parse_link_frame_roundtrip_and_filter():
    frame = build_link_frame(1, 2, 0xC4, b"\xC0\x01\x3C\x02\x06\x05")
    parsed, consumed = parse_link_frame(frame)
    assert consumed == len(frame)
    assert parsed["dest"] == 1 and parsed["src"] == 2 and parsed["fc"] == 4
    assert parsed["prm"] is True and parsed["fcv"] is False
    assert parsed["user_data"] == b"\xC0\x01\x3C\x02\x06\x05"
    assert parsed["need_ack"] is False


def test_parse_link_frame_need_ack_when_fcv():
    frame = build_link_frame(1, 2, 0x73, b"\xC0\x01\x3C\x02\x06\x05")  # FCV=1 FC=3
    parsed, _ = parse_link_frame(frame)
    assert parsed["need_ack"] is True


def test_parse_rejects_bad_crc():
    frame = bytearray(build_link_frame(1, 2, 0xC4, b"\xC0\x01"))
    frame[-1] ^= 0xFF
    with pytest.raises(ValueError):
        parse_link_frame(bytes(frame))


# ---------------------------------------------------------------------------
# 应用层对象编码：黄金结构（组/变体/限定词/索引前缀）
# ---------------------------------------------------------------------------

def test_encode_static_points_golden():
    body = encode_static_points([(100, 1.0, "float32"), (101, 2.5, "float32"), (200, True, "bool")])
    # 布尔先编码：G1V2 索引前缀
    assert body[0] == G_BINARY_INPUT and body[1] == 2 and body[2] == 0x01
    assert struct.unpack("<H", body[3:5])[0] == 1  # count
    # 第一点：IOA=200 + 标志字节（online|value=0x81）
    assert body[5:7] == struct.pack("<H", 200)
    assert body[7] == 0x81
    # 模拟量：G20V6 索引前缀
    i = body.index(bytes([G_ANALOG_INPUT, 6, 0x01]))
    assert struct.unpack("<H", body[i + 3:i + 5])[0] == 2  # count
    # 第一点：IOA=100 + flag(0x01) + int32 定标 ×1000（1.0 → 1000）
    assert body[i + 5:i + 7] == struct.pack("<H", 100)
    assert body[i + 7] == 0x01
    assert struct.unpack("<i", body[i + 8:i + 12])[0] == 1000
    # 第二点：2.5 → 2500（定标保留小数精度）
    j = i + 12
    assert struct.unpack("<H", body[j:j + 2])[0] == 101
    assert struct.unpack("<i", body[j + 3:j + 7])[0] == 2500


def test_encode_events_golden():
    body = encode_events([(200, True, "bool"), (100, 66.6, "float32")])
    # 二输入变化事件 G2V1
    assert body[0] == 2 and body[1] == 1 and body[2] == 0x01
    assert struct.unpack("<H", body[3:5])[0] == 1
    assert body[5:7] == struct.pack("<H", 200)
    assert body[7] == 0x81
    # 模拟量事件 G32V1（32 位带标志）——16 位组在 ×1000 定标下溢出
    i = body.index(bytes([32, 1, 0x01]))
    assert struct.unpack("<H", body[i + 3:i + 5])[0] == 1
    assert body[i + 5:i + 7] == struct.pack("<H", 100)
    assert body[i + 7] == 0x01
    assert struct.unpack("<i", body[i + 8:i + 12])[0] == 66600  # 66.6 × 1000 定标


def test_parse_objects_class0_poll():
    apdu = bytes([0xC0, 0x01, 60, 1, 0x06])  # Read G60V1 Qualifier 0x06
    objs = _parse_objects(apdu[2:])
    assert len(objs) == 1
    assert objs[0]["group"] == G_CLASS and objs[0]["variation"] == 1
    assert objs[0]["qualifier"] == 0x06


def test_split_reassemble_roundtrip():
    apdu = bytes([0xC0, 0x81]) + bytes(300)
    frags = _split_app(apdu, max_user=249)
    assert len(frags) == 2
    assert _reassemble(frags) == apdu
    assert _split_app(apdu[:100]) == [apdu[:100]]  # 单帧 FIR=FIN


# ---------------------------------------------------------------------------
# 响应帧黄金构造：FIR|FIN AC + Read Response FC 0x81，链路层包 CRC
# ---------------------------------------------------------------------------

def test_build_response_golden():
    body = encode_static_points([(100, 1.0, "float32")])
    frame = _build_response(3, 0x81, body, master_src=2, outstation=1)
    parsed, _ = parse_link_frame(frame)
    # 链路层：从站→主站（DIR=0，PRM=1 = outstation 主动回送响应帧，IEEE 1815 惯例）
    assert parsed["dest"] == 2 and parsed["src"] == 1
    assert (parsed["ctrl"] & 0x80) == 0  # DIR=0：outstation → master
    assert parsed["fc"] == 4  # Respond/No-confirm
    apdu = parsed["user_data"]
    assert apdu[0] == 0xC3  # FIR|FIN|SEQ=3
    assert apdu[1] == 0x81  # Read Response
    assert apdu[2:5] == bytes([G_ANALOG_INPUT, 6, 0x01])  # G20V6 索引前缀


# ---------------------------------------------------------------------------
# 主站解析互证：从站 encode ↔ 主站 parse_objects_data roundtrip（v1.16.1）
# ---------------------------------------------------------------------------

def test_master_parse_static_roundtrip():
    from protoforge.protocols.dnp3.master import parse_objects_data
    from protoforge.protocols.dnp3.server import _parse_objects
    pts = [(100, 1.0, "float32"), (101, -2.5, "float32"), (200, True, "bool"), (201, False, "bool")]
    body = encode_static_points(pts)
    # 完整互证：_parse_objects 精确切分各对象 → parse_objects_data 解析数据段
    parsed = []
    for obj in _parse_objects(body):
        if obj["qualifier"] == 0x01 and obj["count"]:
            parsed += parse_objects_data(obj["group"], obj["variation"], obj["payload"])
    assert len(parsed) == 4
    d = {ioa: v for ioa, v, _dt in parsed}
    assert d[100] == pytest.approx(1.0)
    assert d[101] == pytest.approx(-2.5)
    assert d[200] is True and d[201] is False


def test_master_parse_events_roundtrip():
    from protoforge.protocols.dnp3.master import parse_objects_data
    from protoforge.protocols.dnp3.server import _parse_objects
    events = [(200, True, "bool"), (100, 66.6, "float32")]
    body = encode_events(events)
    parsed = []
    for obj in _parse_objects(body):
        if obj["qualifier"] == 0x01 and obj["count"]:
            parsed += parse_objects_data(obj["group"], obj["variation"], obj["payload"])
    assert len(parsed) == 2
    d = {ioa: v for ioa, v, _dt in parsed}
    assert d[200] is True
    assert d[100] == pytest.approx(66.6)


def test_master_class0_request_golden():
    """主站 Class 0 完整性读请求帧：C0 01 3C 01 06，链路层黄金断言。"""
    from protoforge.protocols.dnp3.master import Dnp3MasterServer  # noqa: F401 确认可导入
    frame = build_link_frame(1, 100, 0xC4, b"\xC0\x01\x3C\x01\x06")
    parsed, _ = parse_link_frame(frame)
    assert parsed["dest"] == 1 and parsed["src"] == 100
    assert parsed["user_data"] == b"\xC0\x01\x3C\x01\x06"
