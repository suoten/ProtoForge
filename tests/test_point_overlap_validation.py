"""FIXED: 同设备点位地址重叠校验回归测试（API 层）。

背景：FLOAT32/INT32/UINT32 占 2 个寄存器、STRING 占 32 个。用户在模板里
配置 FLOAT32@2（humidity）与 FLOAT32@3（point_4）时寄存器 3 被两个点位
共用，互相覆盖数据——固定值失效、读出 -1.86e-27 之类乱值且随相邻正弦波
"变动"。此前平台不校验，问题几乎无法从界面值上排查。

修复后：设备创建/更新/quick-create/批量/克隆/CSV 导入及模板保存/实例化
全部入口拦截重叠配置，返回 400 并给出冲突明细。
"""

import pytest
from httpx import AsyncClient

OVERLAP_POINTS = [
    {"name": "temperature", "address": "0", "data_type": "float32",
     "generator_type": "fixed", "fixed_value": 26.0, "access": "rw"},
    {"name": "humidity", "address": "2", "data_type": "float32",
     "generator_type": "fixed", "fixed_value": 58.0, "access": "rw"},
    {"name": "alarm_temp_hi", "address": "4", "data_type": "bool",
     "generator_type": "fixed", "fixed_value": False, "access": "rw"},
    # point_4 与 humidity 共用寄存器 3（FLOAT32 占 2 个寄存器）
    {"name": "point_4", "address": "3", "data_type": "float32",
     "generator_type": "fixed", "fixed_value": 10.0, "access": "rw"},
]

OK_POINTS = [dict(p, address="6") if p["name"] == "point_4" else p for p in OVERLAP_POINTS]


def _device(device_id: str, points: list[dict]) -> dict:
    return {
        "id": device_id, "name": f"Overlap Test {device_id}",
        "protocol": "modbus_tcp", "points": points,
    }


class TestDeviceOverlapValidation:
    @pytest.mark.asyncio
    async def test_create_device_with_overlap_rejected(self, client: AsyncClient):
        """创建设备：FLOAT32@2 与 FLOAT32@3 重叠 → 400，冲突明细含两个点位名."""
        resp = await client.post("/api/v1/devices", json=_device("ov-test-1", OVERLAP_POINTS))
        assert resp.status_code == 400, f"expected 400, got {resp.status_code}: {resp.text}"
        body = resp.json()
        detail = body.get("detail") or body.get("message", "")
        assert "humidity" in detail and "point_4" in detail
        assert "重叠" in detail

    @pytest.mark.asyncio
    async def test_create_device_without_overlap_ok(self, client: AsyncClient):
        """修复后的正确配置（point_4 挪到 6）→ 创建成功."""
        resp = await client.post("/api/v1/devices", json=_device("ov-test-ok", OK_POINTS))
        assert resp.status_code == 200, resp.text
        # 清理
        await client.delete("/api/v1/devices/ov-test-ok")

    @pytest.mark.asyncio
    async def test_create_device_cross_area_overlap_allowed(self, client: AsyncClient):
        """不同存储区地址相同不算冲突（bool@4 落线圈区，float32@4 落保持寄存器区）."""
        points = [
            {"name": "coil_a", "address": "4", "data_type": "bool",
             "generator_type": "fixed", "fixed_value": False, "access": "rw"},
            {"name": "reg_a", "address": "4", "data_type": "uint16",
             "generator_type": "fixed", "fixed_value": 1, "access": "rw"},
        ]
        resp = await client.post("/api/v1/devices", json=_device("ov-test-cross", points))
        assert resp.status_code == 200, resp.text
        await client.delete("/api/v1/devices/ov-test-cross")

    @pytest.mark.asyncio
    async def test_update_device_to_overlap_rejected_400(self, client: AsyncClient):
        """更新设备为重叠配置 → 400（不是 404）."""
        resp = await client.post("/api/v1/devices", json=_device("ov-test-upd", OK_POINTS))
        assert resp.status_code == 200, resp.text
        try:
            bad = _device("ov-test-upd", OVERLAP_POINTS)
            resp = await client.put("/api/v1/devices/ov-test-upd", json=bad)
            assert resp.status_code == 400, f"expected 400, got {resp.status_code}: {resp.text}"
            body = resp.json()
            assert "重叠" in (body.get("detail") or body.get("message", ""))
        finally:
            await client.delete("/api/v1/devices/ov-test-upd")

    @pytest.mark.asyncio
    async def test_quick_create_with_overlap_template_rejected(self, client: AsyncClient):
        """quick-create：含重叠点位的模板 → 400."""
        tpl = {
            "id": "tpl-ov-test", "name": "Overlap Template",
            "protocol": "modbus_tcp", "points": OVERLAP_POINTS,
        }
        resp = await client.post("/api/v1/templates", json=tpl)
        assert resp.status_code == 400, f"template with overlap should be rejected: {resp.text}"
        # 确保模板未落库
        resp = await client.post("/api/v1/devices/quick-create", json={
            "template_id": "tpl-ov-test", "name": "Should Fail",
        })
        assert resp.status_code in (400, 404)  # 模板不存在（quick-create 走全局 ValueError 处理器 → 400）

    @pytest.mark.asyncio
    async def test_batch_create_overlap_recorded_as_error(self, client: AsyncClient):
        """批量创建：重叠设备记入 error 列表，不影响其他设备."""
        payload = [
            _device("ov-batch-ok", OK_POINTS),
            _device("ov-batch-bad", OVERLAP_POINTS),
        ]
        resp = await client.post("/api/v1/devices/batch", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["created"] == 1
        errors = [d for d in data["devices"] if "error" in d]
        assert len(errors) == 1 and errors[0]["id"] == "ov-batch-bad"
        assert "重叠" in errors[0]["error"]
        await client.delete("/api/v1/devices/ov-batch-ok")

    @pytest.mark.asyncio
    async def test_non_modbus_protocol_not_validated(self, client: AsyncClient):
        """非 Modbus 协议（地址语义不同）不做重叠拦截."""
        points = [
            {"name": "a", "address": "x", "data_type": "float32",
             "generator_type": "fixed", "fixed_value": 1.0, "access": "rw"},
            {"name": "b", "address": "x", "data_type": "float32",
             "generator_type": "fixed", "fixed_value": 2.0, "access": "rw"},
        ]
        resp = await client.post("/api/v1/devices", json=_device("ov-mqtt", points) | {"protocol": "mqtt"})
        assert resp.status_code == 200, resp.text
        await client.delete("/api/v1/devices/ov-mqtt")
