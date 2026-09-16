"""FIXED: 点位写入值按 data_type 归一回归测试（bool 读写异常）。

背景（用户实测，2026-09-16）：modbus_tcp 设备的 DI/DO 布尔量点位，
UI 快速写入 "true" / 11 后：
- bool 点位写数字 11 → 原样入库，UI 显示 11，线圈却编码为 1
- 数值点位写字符串 "true" → int("true") 转换失败被静默吞掉，原始字符串入库，
  UI 显示 true、寄存器保持 0 —— 界面值与协议线上的值不一致

修复后：写入链路（API 层 + 协议层 + DeviceInstance）统一按 data_type 归一：
- bool: "true"/"1"/"on"/"yes" → True，"false"/"0"/"off"/"no" → False，
        数字非零 → True（与 Modbus 线圈语义一致），其余字符串拒绝
- 数值: 字符串可解析则转换钳制，不可解析拒绝（400）
"""

import pytest
from httpx import AsyncClient

from protoforge.models.device import DataType, normalize_point_value


# ---------------------------------------------------------------------------
#  单元测试：normalize_point_value
# ---------------------------------------------------------------------------


class TestNormalizePointValue:
    def test_bool_passthrough(self):
        assert normalize_point_value(DataType.BOOL, True) is True
        assert normalize_point_value(DataType.BOOL, False) is False

    def test_bool_from_number_nonzero_is_true(self):
        """数字写 bool 点位 → 非零为 True（与 Modbus 线圈 int(bool(v)) 编码一致）."""
        assert normalize_point_value("bool", 11) is True
        assert normalize_point_value("bool", 1) is True
        assert normalize_point_value("bool", 0) is False
        assert normalize_point_value("bool", 0.0) is False
        assert normalize_point_value("bool", -2) is True

    def test_bool_from_string(self):
        for s in ("true", "True", "TRUE", "1", "on", "Yes"):
            assert normalize_point_value("bool", s) is True, s
        for s in ("false", "False", "0", "off", "NO", ""):
            assert normalize_point_value("bool", s) is False, s

    def test_bool_garbage_rejected(self):
        """此前 "abc" 会被 bool("abc")=True / in(...) 静默吞掉，现在必须拒绝."""
        with pytest.raises(ValueError):
            normalize_point_value("bool", "abc")

    def test_uint16_string_coerced(self):
        assert normalize_point_value("uint16", "42") == 42
        assert normalize_point_value("uint16", 42) == 42

    def test_uint16_garbage_rejected(self):
        """此前 int("true") 失败被静默吞掉、原始字符串入库，现在必须拒绝."""
        with pytest.raises(ValueError):
            normalize_point_value("uint16", "true")

    def test_int16_clamp(self):
        assert normalize_point_value("int16", 99999) == 32767
        assert normalize_point_value("int16", -99999) == -32768

    def test_float64_coerced(self):
        assert normalize_point_value("float64", "3.14") == pytest.approx(3.14)

    def test_float_garbage_rejected(self):
        with pytest.raises(ValueError):
            normalize_point_value("float32", "hot")

    def test_float_nonfinite_rejected(self):
        with pytest.raises(ValueError):
            normalize_point_value("float64", float("inf"))

    def test_string_coerced(self):
        assert normalize_point_value("string", 123) == "123"


# ---------------------------------------------------------------------------
#  API 层：modbus_tcp 设备写入（复现用户场景）
# ---------------------------------------------------------------------------


def _device(device_id: str) -> dict:
    return {
        "id": device_id,
        "name": f"Bool Norm Test {device_id}",
        "protocol": "modbus_tcp",
        "points": [
            {"name": "run_mode", "address": "0", "data_type": "uint16",
             "generator_type": "fixed", "fixed_value": 2, "access": "rw"},
            {"name": "di0", "address": "2", "data_type": "bool",
             "generator_type": "fixed", "fixed_value": False, "access": "rw"},
            {"name": "di1", "address": "3", "data_type": "bool",
             "generator_type": "fixed", "fixed_value": False, "access": "rw"},
            {"name": "do0", "address": "4", "data_type": "bool",
             "generator_type": "fixed", "fixed_value": False, "access": "rw"},
            {"name": "n16", "address": "5", "data_type": "uint16",
             "generator_type": "fixed", "fixed_value": 0, "access": "rw"},
        ],
    }


class TestPointWriteNormalizationAPI:
    @pytest.mark.asyncio
    async def test_bool_point_write_true_string(self, client: AsyncClient):
        """bool 点位写 "true" → 存储 True（此前数字串原样入库）."""
        await client.post("/api/v1/devices", json=_device("bn-1"))
        try:
            resp = await client.put("/api/v1/devices/bn-1/points/di1", json={"value": "true"})
            assert resp.status_code == 200, resp.text
            detail = await client.get("/api/v1/devices/bn-1")
            vals = {p["name"]: p["value"] for p in detail.json()["points"]}
            assert vals["di1"] is True
        finally:
            await client.delete("/api/v1/devices/bn-1")

    @pytest.mark.asyncio
    async def test_bool_point_write_number_11(self, client: AsyncClient):
        """bool 点位写 11 → 归一为 True（此前 UI 显示 11、线圈是 1）."""
        await client.post("/api/v1/devices", json=_device("bn-2"))
        try:
            resp = await client.put("/api/v1/devices/bn-2/points/do0", json={"value": 11})
            assert resp.status_code == 200, resp.text
            detail = await client.get("/api/v1/devices/bn-2")
            vals = {p["name"]: p["value"] for p in detail.json()["points"]}
            assert vals["do0"] is True
        finally:
            await client.delete("/api/v1/devices/bn-2")

    @pytest.mark.asyncio
    async def test_uint16_point_write_garbage_rejected(self, client: AsyncClient):
        """uint16 点位写 "true" → 400 明确报错（此前静默存字符串）."""
        await client.post("/api/v1/devices", json=_device("bn-3"))
        try:
            resp = await client.put("/api/v1/devices/bn-3/points/n16", json={"value": "true"})
            assert resp.status_code == 400, f"expected 400, got {resp.status_code}: {resp.text}"
            # 全局异常处理器会把 detail 包装为 message 字段
            body = resp.json()
            detail = body.get("detail") or body.get("message") or ""
            assert "n16" in detail
        finally:
            await client.delete("/api/v1/devices/bn-3")

    @pytest.mark.asyncio
    async def test_uint16_point_write_numeric_string_ok(self, client: AsyncClient):
        """uint16 点位写 "42"（数字字符串）→ 正常转换 42."""
        await client.post("/api/v1/devices", json=_device("bn-4"))
        try:
            resp = await client.put("/api/v1/devices/bn-4/points/n16", json={"value": "42"})
            assert resp.status_code == 200, resp.text
            detail = await client.get("/api/v1/devices/bn-4")
            vals = {p["name"]: p["value"] for p in detail.json()["points"]}
            assert vals["n16"] == 42
        finally:
            await client.delete("/api/v1/devices/bn-4")

    @pytest.mark.asyncio
    async def test_bool_point_write_garbage_rejected(self, client: AsyncClient):
        """bool 点位写 "abc" → 400 明确报错（此前静默变 False）."""
        await client.post("/api/v1/devices", json=_device("bn-5"))
        try:
            resp = await client.put("/api/v1/devices/bn-5/points/di0", json={"value": "abc"})
            assert resp.status_code == 400, f"expected 400, got {resp.status_code}: {resp.text}"
        finally:
            await client.delete("/api/v1/devices/bn-5")
