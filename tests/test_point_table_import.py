"""v1.7.0 点表导入引擎测试（protoforge/core/point_table.py）。

规划验收：5 种厂商风格真实点表样例导入成功率 >95%；地址风格自动识别；
冲突/类型疑点在预览中显式标出（绝不静默）。
"""

import sys
from pathlib import Path

import pytest

from protoforge.core.point_table import (
    detect_address_style,
    normalize_data_type,
    parse_point_table,
)

SAMPLES = Path(__file__).parent / "samples"


def _load(name: str) -> str:
    return (SAMPLES / name).read_text(encoding="utf-8-sig")


# ---------------------------------------------------------------------------
# 地址风格识别
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("addr,expected", [
    ("DB1.DBD0", "siemens_db"),
    ("DB10.DBX8.0", "siemens_db"),
    ("M0.0", "siemens_m"),
    ("MD20", "siemens_m"),
    ("I0.0", "siemens_i"),
    ("QW4", "siemens_q"),
    ("D100", "mitsubishi_dwr"),
    ("ZR10", "mitsubishi_dwr"),
    ("X10", "mitsubishi_xy"),
    ("Y1A", "mitsubishi_xy"),
    ("CIO0.00", "omron_cio"),
    ("W10", "omron_w"),
    ("DM100", "omron_dm"),
    ("00010000", "dlt645_di"),
    ("4x0001", "modbus_prefix"),
    ("40001", "modbus_5digit"),
    ("400001", "modbus_6digit"),
    ("2404", "iec104_ioa"),
    ("", "unknown"),
    (" nonsense ", "unknown"),
])
def test_detect_address_style(addr, expected):
    assert detect_address_style(addr.strip()) == expected


def test_normalize_data_type_aliases():
    assert normalize_data_type("Real")[0] == "float32"
    assert normalize_data_type("WORD")[0] == "uint16"
    assert normalize_data_type("BIT")[0] == "bool"
    assert normalize_data_type("DWORD")[0] == "uint32"
    assert normalize_data_type("")[1]  # 空类型有提示
    ok, warn = normalize_data_type(" mystery ")
    assert ok == "float32" and warn  # 未知类型降级 float32 且提示


# ---------------------------------------------------------------------------
# 五厂商样例全量导入（规划验收 >95% 成功率 → 这里要求 100%）
# ---------------------------------------------------------------------------

def test_sample_siemens_imports():
    r = parse_point_table(_load("sample_siemens.csv"), protocol="s7")
    assert not r.errors, r.errors
    assert not r.conflicts, r.conflicts
    assert len(r.points) == 10
    # MD20 是 M 双字（引擎正确归类），I0.0 输入区、Q0.2 输出区各 1
    assert r.style_counts.get("siemens_db", 0) == 5
    assert r.style_counts.get("siemens_m", 0) == 3
    assert r.style_counts.get("siemens_i", 0) == 1
    assert r.style_counts.get("siemens_q", 0) == 1
    names = {p.name for p in r.points}
    assert "reactor_temp" in names and "drain_valve" in names
    # 类型归一化正确
    temp = next(p for p in r.points if p.name == "reactor_temp")
    assert temp.data_type == "float32"
    run = next(p for p in r.points if p.name == "agitator_run")
    assert run.data_type == "bool"


def test_sample_mitsubishi_imports():
    r = parse_point_table(_load("sample_mitsubishi.csv"), protocol="mc")
    assert not r.errors
    assert not r.conflicts
    assert len(r.points) == 8
    assert r.style_counts.get("mitsubishi_dwr", 0) >= 7
    assert r.style_counts.get("mitsubishi_xy", 0) == 1  # cooling_fan Y10


def test_sample_omron_imports():
    r = parse_point_table(_load("sample_omron.csv"), protocol="fins")
    assert not r.errors
    assert not r.conflicts
    assert len(r.points) == 7
    assert r.style_counts.get("omron_dm", 0) == 4
    assert r.style_counts.get("omron_cio", 0) == 1
    assert r.style_counts.get("omron_w", 0) == 2


def test_sample_modbus_imports():
    r = parse_point_table(_load("sample_modbus.csv"), protocol="modbus_tcp")
    assert not r.errors
    assert not r.conflicts, r.conflicts
    assert len(r.points) == 7
    assert r.style_counts.get("modbus_prefix", 0) == 6
    assert r.style_counts.get("modbus_5digit", 0) == 1  # 40010 在 40001-49999 区间
    # 只读列归一化
    remote = next(p for p in r.points if p.name == "remote_lock")
    assert remote.access == "r"


def test_sample_dlt645_imports():
    r = parse_point_table(_load("sample_dlt645.csv"), protocol="dlt645")
    assert not r.errors
    assert not r.conflicts
    assert len(r.points) == 6
    assert r.style_counts.get("dlt645_di", 0) == 6


def test_all_samples_high_success_rate():
    """规划验收：5 厂商风格样例导入成功率 >95%（成功解析点数/总数据行；
    warnings 是随行提示不算失败，errors/conflicts 才是失败）。"""
    cases = [
        ("sample_siemens.csv", "s7"),
        ("sample_mitsubishi.csv", "mc"),
        ("sample_omron.csv", "fins"),
        ("sample_modbus.csv", "modbus_tcp"),
        ("sample_dlt645.csv", "dlt645"),
    ]
    total_rows = total_ok = 0
    for fname, protocol in cases:
        r = parse_point_table(_load(fname), protocol=protocol)
        rows = len(r.points) + len(r.errors)
        total_rows += rows
        total_ok += len(r.points)
        assert not r.errors, f"{fname}: {r.errors}"
        assert not r.conflicts, f"{fname}: {r.conflicts}"
    assert total_rows >= 35, f"样例点数不足: {total_rows}"
    assert total_ok / total_rows > 0.95, f"{total_ok}/{total_rows}"


# ---------------------------------------------------------------------------
# 冲突与疑点显式暴露（绝不静默）
# ---------------------------------------------------------------------------

def test_modbus_register_overlap_flagged():
    """float32(2寄存器) 与相邻 uint16 重叠 → 冲突列表可见。"""
    csv = "name,address,data_type\na,40001,float32\nb,40002,uint16\n"
    r = parse_point_table(csv, protocol="modbus_tcp")
    assert r.conflicts, "寄存器重叠必须出现在 conflicts 中"
    assert not r.ok


def test_duplicate_address_flagged_non_modbus():
    csv = "name,address\nx,DM100\ny,DM100\n"
    r = parse_point_table(csv, protocol="fins")
    assert any("DM100" in c for c in r.conflicts)


def test_duplicate_point_names_flagged():
    csv = "name,address\n同一点,40001\n同一点,40002\n"
    r = parse_point_table(csv, protocol="modbus_tcp")
    assert r.duplicate_names


def test_style_protocol_mismatch_warns():
    """三菱地址导入到西门子协议 → 逐点警告（原样传入，人工确认）。"""
    csv = "name,address\nspeed,D100\n"
    r = parse_point_table(csv, protocol="s7")
    assert r.points[0].warnings, "风格与协议不匹配应产生警告"


def test_style_hint_overrides_detection():
    csv = "name,address\nx,100\n"  # 会被识别为 iec104_ioa
    r = parse_point_table(csv, protocol="modbus_tcp", style_hint="modbus_prefix")
    assert r.points[0].style == "modbus_prefix"


def test_missing_required_columns_rejected():
    r = parse_point_table("foo,bar\n1,2\n", protocol="modbus_tcp")
    assert r.errors and not r.points
    assert "点名" in r.errors[0] or "name" in r.errors[0].lower()


def test_tsv_and_blank_rows():
    csv = "name\taddress\tdata_type\n\na\t40001\tfloat32\n\n"
    r = parse_point_table(csv, protocol="modbus_tcp")
    assert len(r.points) == 1 and r.points[0].name == "a"


def test_thousand_points_under_10s():
    """规划验收：1000 点导入 <10 秒（纯解析路径，无 IO）。"""
    import time
    lines = ["name,address,data_type,unit"] + [
        f"p{i},4x{i % 60000:05d},uint16,unit" for i in range(1000)
    ]
    csv = "\n".join(lines)
    t0 = time.monotonic()
    r = parse_point_table(csv, protocol="modbus_tcp")
    elapsed = time.monotonic() - t0
    assert len(r.points) == 1000
    assert elapsed < 10, f"1000 点导入耗时 {elapsed:.2f}s（规划验收 <10s）"
