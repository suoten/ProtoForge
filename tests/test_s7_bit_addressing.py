"""S7 位寻址回归测试（v1.16.5 FIXED-P1）。

用户实测场景：M 区位地址 M4.1/M2.0，KEPServer 风格客户端位读。
旧实现位号在地址解析时被丢弃：
  - 位读返回整字节原值（M4.1 读回的是字节 4，M4.0=1 时客户端把 M4.1 读成 1）；
  - 布尔点值同步按整字节覆盖写（M4.1=1 实际写成 byte4=0x01，同字节其他位被清零）；
  - 客户端位写按字节偏移匹配点（同字节 M4.0/M4.1 被一起改写）。
修复后：位读从整字节提取对应位；点值同步按位读-改-写；写路径点匹配按位号精确匹配。
"""

import struct

import pytest

from protoforge.protocols.s7.server import S7DeviceBehavior, S7Server


class _P(dict):
    """dict + 属性访问，兼容 behavior 初始化的两种取值方式。"""

    def __getattr__(self, k):
        try:
            return self[k]
        except KeyError:
            raise AttributeError(k)


def _make_points():
    return [
        _P(name="p40", address="M4.0", data_type="bool", generator="fixed",
           fixed_value=0, generator_config={}, min_value=0, max_value=1),
        _P(name="p41", address="M4.1", data_type="bool", generator="fixed",
           fixed_value=1, generator_config={}, min_value=0, max_value=1),
        _P(name="p20", address="M2.0", data_type="bool", generator="fixed",
           fixed_value=0, generator_config={}, min_value=0, max_value=1),
    ]


def _make_server(points):
    behavior = S7DeviceBehavior(points=points)
    srv = S7Server()
    srv._behaviors["dev1"] = behavior
    srv._default_device_id = "dev1"
    srv._on_write = None
    if not hasattr(srv, "_log_debug"):
        srv._log_debug = lambda *a, **k: None
    return srv, behavior


def _read_item(area: int, byte_off: int, bit: int) -> bytes:
    addr = byte_off * 8 + bit
    return bytes([0x12, 0x0A, 0x10, 0x01, 0x00, 0x01, 0x00, 0x00, area,
                  (addr >> 16) & 0xFF, (addr >> 8) & 0xFF, addr & 0xFF])


def _read_frame(area: int, byte_off: int, bit: int) -> bytes:
    frame = bytearray(19 + 12)
    frame[11:13] = b"\x12\x34"                       # PDU ref
    frame[17] = 0x04                                  # Read Var
    frame[18] = 0x01                                  # item count
    frame[19:31] = _read_item(area, byte_off, bit)
    return bytes(frame)


def _parse_read_item(resp: bytes) -> tuple[int, int, int]:
    """响应布局: TPKT(4)+COTP(3)+Header(7..17)+Function(19)+Count(20)+数据项(21..)。"""
    assert resp[19] == 0x04, f"function {resp[19]:#x}"
    ret, ts = resp[21], resp[22]
    ln = (resp[23] << 8) | resp[24]
    data = resp[25]
    return ret, ts, (ln, data)


def _write_frame(area: int, byte_off: int, bit: int, val: int) -> bytes:
    # Write Var 数据项: Reserved(1)+TransportSize(1)+Length(2)+Data(N)+Pad
    frame = bytearray(19 + 12 + 5)
    frame[11:13] = b"\x56\x78"
    frame[17] = 0x05                                  # Write Var
    frame[18] = 0x01
    frame[19:31] = _read_item(area, byte_off, bit)
    frame[31] = 0x00                                  # 保留字节
    frame[32] = 0x03                                  # transport BIT
    frame[33:35] = (1).to_bytes(2, "big")             # 1 bit
    frame[35] = val
    return bytes(frame)


# ---------- 位号解析 ----------

@pytest.mark.parametrize("addr,expected", [
    ("M4.1", 1), ("M2.0", 0), ("I0.0", 0), ("Q1.7", 7),
    ("DB1.DBX3.1", 1), ("DB2.DBX0.7", 7),
    ("MB4", None), ("MW2", None), ("MD4", None),
    ("DB1.DBB4", None), ("DB1.DBW2", None), ("DB1.DBD0", None),
    ("T1", None), ("C1", None),
])
def test_parse_s7_bit(addr, expected):
    assert S7DeviceBehavior._parse_s7_bit(addr) == expected


# ---------- 点值同步按位读-改-写 ----------

def test_bool_sync_rmw_same_byte_bits():
    _, b = _make_server(_make_points())
    b.set_value("p41", True)   # M4.1 = 1
    b.set_value("p40", True)   # M4.0 = 1，不得清除 M4.1
    assert b.read_area(0x83, 0, 4, 1)[0] == 0b11
    b.set_value("p41", False)  # 清 M4.1 不得影响 M4.0
    assert b.read_area(0x83, 0, 4, 1)[0] == 0b01
    b.set_value("p20", False)  # M2.0 独立字节
    assert b.read_area(0x83, 0, 2, 1)[0] == 0x00


# ---------- 位读提取对应位 ----------

def test_bit_read_extracts_bit_not_whole_byte():
    srv, b = _make_server(_make_points())
    b.set_value("p41", True)   # byte4 = 0b10
    b.set_value("p40", False)
    resp = srv._make_s7_read_response(_read_frame(0x83, 4, 1), "dev1")
    ret, ts, (ln, data) = _parse_read_item(resp)
    assert ret == 0xFF and ts == 0x03 and ln == 1
    assert data == 0x01        # 旧实现返回整字节 0b10，客户端无法正确解析位值
    resp = srv._make_s7_read_response(_read_frame(0x83, 4, 0), "dev1")
    ret, ts, (ln, data) = _parse_read_item(resp)
    assert data == 0x00        # 同字节 M4.0 读回 0，不受 M4.1 影响
    resp = srv._make_s7_read_response(_read_frame(0x83, 2, 0), "dev1")
    ret, ts, (ln, data) = _parse_read_item(resp)
    assert data == 0x00


# ---------- 位写与点匹配 ----------

def test_bit_write_touches_only_target_bit():
    srv, b = _make_server(_make_points())
    b.set_value("p41", True)   # byte4 = 0b10
    srv._make_s7_write_response(_write_frame(0x83, 4, 0, 1), "dev1")  # 写 M4.0=1
    assert b.read_area(0x83, 0, 4, 1)[0] == 0b11      # M4.1 保持 1
    assert b._values["p41"] is True                   # 旧实现会被整字节改写
    assert b._values["p40"] is True                   # 点值按位同步
    srv._make_s7_write_response(_write_frame(0x83, 4, 1, 0), "dev1")  # 写 M4.1=0
    assert b.read_area(0x83, 0, 4, 1)[0] == 0b01      # M4.0 保持 1
    assert b._values["p41"] is False
    assert b._values["p40"] is True
