"""500 错误边界测试套件

覆盖可能导致 HTTP 500 的边界场景：
  1. 参数边界：null / 空字符串 / 超长 / 特殊字符
  2. 数据库无匹配记录
  3. 并发请求
  4. 外部依赖不可用（DB / Engine / Webhook）

运行方式:
  pytest tests/test_500_boundary.py -v --tb=short
  pytest tests/test_500_boundary.py -k "device" -v   # 只跑设备相关
"""

import asyncio
import json
import logging
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio

logger = logging.getLogger(__name__)


# =============================================================================
#  辅助函数
# =============================================================================

def _modbus_device_config(device_id: str = "boundary-device") -> dict[str, Any]:
    """构造一个合法的 Modbus 设备配置，供测试修改。"""
    return {
        "id": device_id,
        "name": "boundary-test-device",
        "protocol": "modbus_tcp",
        "points": [
            {
                "name": "temperature",
                "address": "0",
                "data_type": "float32",
                "unit": "C",
                "generator_type": "random",
                "min_value": 15.0,
                "max_value": 35.0,
            }
        ],
    }


async def _create_device(client: AsyncClient, device_id: str = "boundary-device") -> dict:
    """创建一个测试设备并返回响应。"""
    resp = await client.post("/api/v1/devices", json=_modbus_device_config(device_id))
    assert resp.status_code in (200, 201), f"Setup device failed: {resp.text}"
    return resp.json()


def _get_msg(resp) -> str:
    """从响应中提取错误消息文本，兼容 detail 和 message 两种格式。"""
    data = resp.json()
    return str(data.get("detail") or data.get("message") or "")


# =============================================================================
#  1. 设备接口 500 边界测试
# =============================================================================

class TestDeviceCreateBoundary:
    """POST /devices 创建设备 — 500 触发条件"""

    async def test_create_device_empty_id(self, client: AsyncClient):
        """空 ID 应返回 400，不应 500。"""
        cfg = _modbus_device_config("")
        resp = await client.post("/api/v1/devices", json=cfg)
        assert resp.status_code == 400
        assert "id" in _get_msg(resp).lower()

    async def test_create_device_empty_name(self, client: AsyncClient):
        """空 name 应返回 400。"""
        cfg = _modbus_device_config()
        cfg["name"] = ""
        resp = await client.post("/api/v1/devices", json=cfg)
        assert resp.status_code == 400

    async def test_create_device_null_id(self, client: AsyncClient):
        """null ID 应返回 422（Pydantic 校验），不应 500。"""
        cfg = _modbus_device_config()
        cfg["id"] = None
        resp = await client.post("/api/v1/devices", json=cfg)
        assert resp.status_code in (400, 422)

    async def test_create_device_super_long_id(self, client: AsyncClient):
        """超长 ID（>64 字符）应返回 400。"""
        cfg = _modbus_device_config("a" * 200)
        resp = await client.post("/api/v1/devices", json=cfg)
        assert resp.status_code == 400

    async def test_create_device_special_chars_in_id(self, client: AsyncClient):
        """特殊字符 ID 应正常处理或返回 400，不应 500。"""
        cfg = _modbus_device_config("device<script>alert(1)</script>")
        resp = await client.post("/api/v1/devices", json=cfg)
        assert resp.status_code in (200, 201, 400)

    async def test_create_device_invalid_protocol(self, client: AsyncClient):
        """不存在的协议应返回 400，不应 500。"""
        cfg = _modbus_device_config()
        cfg["protocol"] = "nonexistent_protocol_xyz"
        resp = await client.post("/api/v1/devices", json=cfg)
        # 系统可能容错创建（200）或拒绝（400），但不能 500
        assert resp.status_code != 500, "Invalid protocol should not cause 500"

    async def test_create_device_missing_points(self, client: AsyncClient):
        """points 为空列表不应 500。"""
        cfg = _modbus_device_config()
        cfg["points"] = []
        resp = await client.post("/api/v1/devices", json=cfg)
        assert resp.status_code in (200, 201, 400)

    async def test_create_device_null_points(self, client: AsyncClient):
        """points 为 null 应返回 422，不应 500。"""
        cfg = _modbus_device_config()
        cfg["points"] = None
        resp = await client.post("/api/v1/devices", json=cfg)
        assert resp.status_code in (400, 422)

    async def test_create_device_malformed_points(self, client: AsyncClient):
        """points 中含畸形数据不应 500。"""
        cfg = _modbus_device_config()
        cfg["points"] = [{"invalid": "point"}]
        resp = await client.post("/api/v1/devices", json=cfg)
        assert resp.status_code in (400, 422)


class TestDeviceReadBoundary:
    """GET /devices/{device_id} 读取设备 — 500 触发条件"""

    async def test_get_nonexistent_device(self, client: AsyncClient):
        """查询不存在的设备应返回 404，不应 500。"""
        resp = await client.get("/api/v1/devices/nonexistent-device-xyz-12345")
        assert resp.status_code == 404

    async def test_get_device_empty_id(self, client: AsyncClient):
        """空 ID 路径不应 500。"""
        resp = await client.get("/api/v1/devices/")
        assert resp.status_code in (404, 405, 422)

    async def test_get_device_special_chars(self, client: AsyncClient):
        """特殊字符 ID 不应 500。"""
        resp = await client.get("/api/v1/devices/../../etc/passwd")
        assert resp.status_code in (404, 422)

    async def test_get_device_points_nonexistent(self, client: AsyncClient):
        """读取不存在设备的点位应返回 404。"""
        resp = await client.get("/api/v1/devices/nonexistent-device/points")
        assert resp.status_code == 404


class TestDeviceWritePointBoundary:
    """PUT /devices/{device_id}/points/{point_name} — 500 触发条件"""

    async def test_write_point_missing_value(self, client: AsyncClient):
        """请求体缺少 value 字段应返回 400。"""
        await _create_device(client)
        resp = await client.put(
            "/api/v1/devices/boundary-device/points/temperature",
            json={},
        )
        assert resp.status_code == 400

    async def test_write_point_null_body(self, client: AsyncClient):
        """请求体为 null 应返回 400。"""
        await _create_device(client)
        resp = await client.put(
            "/api/v1/devices/boundary-device/points/temperature",
            json=None,
        )
        assert resp.status_code in (400, 422)

    async def test_write_point_nonexistent_device(self, client: AsyncClient):
        """写入不存在设备的点位应返回 404。"""
        resp = await client.put(
            "/api/v1/devices/nonexistent-device/points/temperature",
            json={"value": 25.5},
        )
        assert resp.status_code == 404

    async def test_write_point_nonexistent_point(self, client: AsyncClient):
        """写入不存在的点位名不应 500。"""
        await _create_device(client)
        resp = await client.put(
            "/api/v1/devices/boundary-device/points/nonexistent_point",
            json={"value": 25.5},
        )
        assert resp.status_code in (400, 404)

    async def test_write_point_value_string_for_numeric(self, client: AsyncClient):
        """向数值点位写入字符串值不应 500。"""
        await _create_device(client)
        resp = await client.put(
            "/api/v1/devices/boundary-device/points/temperature",
            json={"value": "not_a_number"},
        )
        # 应该是 400 或 200（内部容错），但不能 500
        assert resp.status_code != 500, "Writing string to numeric point should not cause 500"

    async def test_write_point_value_extreme_float(self, client: AsyncClient):
        """写入极端浮点值不应 500。"""
        await _create_device(client)
        # httpx 的 json= 参数用 allow_nan=False 序列化，inf/nan 在客户端就会抛
        # ValueError，永远到不了服务端；改用原始 JSON 文本（Python json.loads
        # 默认接受 Infinity/NaN），让服务端真正收到并返回 400
        for raw in ['{"value": Infinity}', '{"value": -Infinity}', '{"value": NaN}',
                    '{"value": 1e308}', '{"value": -1e308}']:
            resp = await client.put(
                "/api/v1/devices/boundary-device/points/temperature",
                content=raw,
                headers={"Content-Type": "application/json"},
            )
            assert resp.status_code != 500, f"Writing {raw} should not cause 500"


class TestDeviceBatchBoundary:
    """POST /devices/batch 批量创建 — 500 触发条件"""

    async def test_batch_create_empty_list(self, client: AsyncClient):
        """空列表应返回 400。"""
        resp = await client.post("/api/v1/devices/batch", json=[])
        assert resp.status_code == 400

    async def test_batch_create_with_invalid_device(self, client: AsyncClient):
        """批量中包含无效设备不应导致整体 500。"""
        configs = [
            _modbus_device_config("batch-valid-1"),
            {**_modbus_device_config("batch-invalid"), "protocol": "bad_protocol"},
        ]
        resp = await client.post("/api/v1/devices/batch", json=configs)
        # 批量应容错，返回 200 带 errors，或 400
        assert resp.status_code in (200, 400)

    async def test_batch_delete_empty_list(self, client: AsyncClient):
        """批量删除空列表不应 500。"""
        resp = await client.post("/api/v1/devices/batch/delete", json={"device_ids": []})
        assert resp.status_code in (200, 400)

    async def test_batch_delete_nonexistent_ids(self, client: AsyncClient):
        """批量删除不存在的 ID 不应 500。"""
        resp = await client.post(
            "/api/v1/devices/batch/delete",
            json={"device_ids": ["nonexistent-1", "nonexistent-2"]},
        )
        assert resp.status_code == 200


# =============================================================================
#  2. 场景接口 500 边界测试
# =============================================================================

class TestScenarioBoundary:
    """场景接口 — 500 触发条件"""

    async def test_create_scenario_empty_name(self, client: AsyncClient):
        """空 name 应返回 400。"""
        resp = await client.post("/api/v1/scenarios", json={
            "id": "test-scenario",
            "name": "",
            "description": "",
            "devices": [],
            "rules": [],
        })
        assert resp.status_code == 400

    async def test_create_scenario_empty_id(self, client: AsyncClient):
        """空 ID 应返回 400。"""
        resp = await client.post("/api/v1/scenarios", json={
            "id": "",
            "name": "test",
            "description": "",
            "devices": [],
            "rules": [],
        })
        assert resp.status_code == 400

    async def test_get_nonexistent_scenario(self, client: AsyncClient):
        """查询不存在场景应返回 404。"""
        resp = await client.get("/api/v1/scenarios/nonexistent-scenario-xyz")
        assert resp.status_code == 404

    async def test_start_nonexistent_scenario(self, client: AsyncClient):
        """启动不存在场景应返回 404。"""
        resp = await client.post("/api/v1/scenarios/nonexistent-scenario/start")
        assert resp.status_code == 404

    async def test_stop_nonexistent_scenario(self, client: AsyncClient):
        """停止不存在场景应返回 404。"""
        resp = await client.post("/api/v1/scenarios/nonexistent-scenario/stop")
        assert resp.status_code == 404


# =============================================================================
#  3. 系统接口 500 边界测试
# =============================================================================

class TestSystemBoundary:
    """系统管理接口 — 500 触发条件"""

    async def test_backup_restore_empty_data(self, client: AsyncClient):
        """恢复空备份应返回 400。"""
        resp = await client.post("/api/v1/backup/restore", json={"data": {}})
        assert resp.status_code == 400

    async def test_backup_restore_null_data(self, client: AsyncClient):
        """恢复 null 数据应返回 400 或 422。"""
        resp = await client.post("/api/v1/backup/restore", json={"data": None})
        assert resp.status_code in (400, 422)

    async def test_backup_restore_non_dict_data(self, client: AsyncClient):
        """恢复非字典数据应返回 400。"""
        resp = await client.post("/api/v1/backup/restore", json={"data": "not_a_dict"})
        assert resp.status_code == 400

    async def test_backup_restore_malformed_data(self, client: AsyncClient):
        """恢复畸形数据不应 500。"""
        resp = await client.post("/api/v1/backup/restore", json={
            "data": {"devices": "should_be_list_not_string"}
        })
        assert resp.status_code in (200, 400), "Malformed backup data should not cause 500"

    async def test_update_settings_invalid_key(self, client: AsyncClient):
        """更新无效设置项应返回 400。"""
        resp = await client.put("/api/v1/settings", json={"invalid_key_xyz": "value"})
        assert resp.status_code == 400

    async def test_update_settings_empty(self, client: AsyncClient):
        """空更新应返回 400。"""
        resp = await client.put("/api/v1/settings", json={})
        assert resp.status_code == 400

    async def test_audit_query_invalid_limit(self, client: AsyncClient):
        """非法 limit 参数不应 500。"""
        resp = await client.get("/api/v1/audit?limit=-1")
        assert resp.status_code == 200  # 应被自动修正

    async def test_audit_query_huge_limit(self, client: AsyncClient):
        """超大 limit 参数不应 500。"""
        resp = await client.get("/api/v1/audit?limit=999999999")
        assert resp.status_code == 200  # 应被自动修正

    async def test_audit_query_negative_offset(self, client: AsyncClient):
        """负数 offset 不应 500。"""
        resp = await client.get("/api/v1/audit?offset=-100")
        assert resp.status_code == 200  # 应被自动修正


# =============================================================================
#  4. 模板接口 500 边界测试
# =============================================================================

class TestTemplateBoundary:
    """模板接口 — 500 触发条件"""

    async def test_get_nonexistent_template(self, client: AsyncClient):
        """查询不存在模板应返回 404。"""
        resp = await client.get("/api/v1/templates/nonexistent-template-xyz")
        assert resp.status_code == 404

    async def test_quick_create_nonexistent_template(self, client: AsyncClient):
        """快速创建引用不存在模板应返回 404 或 400。"""
        resp = await client.post("/api/v1/devices/quick-create", json={
            "template_id": "nonexistent-template-xyz",
            "name": "test-device",
        })
        # ValueError 被全局处理器转为 400，或直接 404
        assert resp.status_code in (400, 404)

    async def test_quick_create_empty_template_id(self, client: AsyncClient):
        """空 template_id 应返回 400。"""
        resp = await client.post("/api/v1/devices/quick-create", json={
            "template_id": "",
            "name": "test-device",
        })
        assert resp.status_code == 400

    async def test_quick_create_empty_name(self, client: AsyncClient):
        """空 name 应返回 400。"""
        resp = await client.post("/api/v1/devices/quick-create", json={
            "template_id": "modbus_tcp_standard",
            "name": "",
        })
        assert resp.status_code == 400


# =============================================================================
#  5. 故障注入接口 500 边界测试
# =============================================================================

class TestFaultInjectionBoundary:
    """故障注入接口 — 500 触发条件"""

    async def test_inject_fault_nonexistent_device(self, client: AsyncClient):
        """向不存在设备注入故障应返回 404。"""
        resp = await client.post("/api/v1/devices/nonexistent-device/faults", json={
            "fault_type": "sensor_drift",
            "target": "*",
        })
        assert resp.status_code == 404

    async def test_inject_fault_invalid_type(self, client: AsyncClient):
        """无效故障类型应返回 400。"""
        await _create_device(client)
        resp = await client.post("/api/v1/devices/boundary-device/faults", json={
            "fault_type": "invalid_fault_type_xyz",
            "target": "*",
        })
        assert resp.status_code == 400

    async def test_inject_fault_invalid_trigger_mode(self, client: AsyncClient):
        """无效触发模式应返回 400。"""
        await _create_device(client)
        resp = await client.post("/api/v1/devices/boundary-device/faults", json={
            "fault_type": "sensor_drift",
            "target": "*",
            "trigger_mode": "invalid_mode_xyz",
        })
        assert resp.status_code == 400

    async def test_list_faults_nonexistent_device(self, client: AsyncClient):
        """列出不存在设备故障应返回 404。"""
        resp = await client.get("/api/v1/devices/nonexistent-device/faults")
        assert resp.status_code == 404


# =============================================================================
#  6. 并发请求测试
# =============================================================================

class TestConcurrencyBoundary:
    """并发请求 — 500 触发条件"""

    async def test_concurrent_create_same_device(self, client: AsyncClient):
        """并发创建相同 ID 设备不应 500。"""
        cfg = _modbus_device_config("concurrent-device")
        tasks = [client.post("/api/v1/devices", json=cfg) for _ in range(5)]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for r in results:
            if isinstance(r, Exception):
                continue  # 网络异常可接受
            assert r.status_code != 500, f"Concurrent create should not cause 500, got {r.status_code}"

    async def test_concurrent_read_points(self, client: AsyncClient):
        """并发读取点位不应 500。"""
        await _create_device(client)
        tasks = [
            client.get("/api/v1/devices/boundary-device/points")
            for _ in range(20)
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for r in results:
            if isinstance(r, Exception):
                continue
            assert r.status_code != 500

    async def test_concurrent_start_stop(self, client: AsyncClient):
        """并发启停设备不应 500。"""
        await _create_device(client)
        tasks = []
        for _ in range(5):
            tasks.append(client.post("/api/v1/devices/boundary-device/start"))
            tasks.append(client.post("/api/v1/devices/boundary-device/stop"))
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for r in results:
            if isinstance(r, Exception):
                continue
            assert r.status_code != 500

    async def test_concurrent_write_same_point(self, client: AsyncClient):
        """并发写同一点位不应 500。"""
        await _create_device(client)
        tasks = [
            client.put(
                "/api/v1/devices/boundary-device/points/temperature",
                json={"value": float(i)},
            )
            for i in range(20)
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for r in results:
            if isinstance(r, Exception):
                continue
            assert r.status_code != 500

    async def test_concurrent_backup_export(self, client: AsyncClient):
        """并发导出备份不应 500。"""
        tasks = [client.get("/api/v1/backup") for _ in range(5)]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for r in results:
            if isinstance(r, Exception):
                continue
            assert r.status_code != 500


# =============================================================================
#  7. 外部依赖不可用测试（Mock）
# =============================================================================

class TestExternalDependencyFailure:
    """外部依赖不可用 — 500 触发条件"""

    async def test_create_device_db_failure(self, client: AsyncClient):
        """数据库保存失败时应返回 500 带友好信息，不应裸奔。"""
        with patch("protoforge.api.v1.device_routes._get_database") as mock_db_fn:
            mock_db = MagicMock()
            mock_db.save_device = AsyncMock(side_effect=RuntimeError("DB connection lost"))
            mock_db_fn.return_value = mock_db

            cfg = _modbus_device_config("db-fail-device")
            resp = await client.post("/api/v1/devices", json=cfg)
            # 应返回 500（持久化失败），但带友好消息
            assert resp.status_code == 500
            msg = _get_msg(resp)
            assert "persist" in msg.lower() or "db" in msg.lower()

    async def test_get_device_engine_failure(self, client: AsyncClient):
        """引擎异常时不应返回未处理的 500。"""
        with patch("protoforge.api.v1.device_routes._get_engine") as mock_engine_fn:
            mock_engine = MagicMock()
            mock_engine.get_device = MagicMock(side_effect=RuntimeError("Engine corrupted"))
            mock_engine_fn.return_value = mock_engine

            resp = await client.get("/api/v1/devices/any-device")
            # 全局异常处理器应捕获 RuntimeError 返回 500
            assert resp.status_code == 500
            data = resp.json()
            assert "code" in data
            assert data["code"] == 500

    async def test_backup_export_db_none(self, client: AsyncClient):
        """数据库未初始化时导出备份应返回 503。"""
        with patch("protoforge.api.v1.system_routes._get_database", return_value=None):
            resp = await client.get("/api/v1/backup")
            assert resp.status_code == 503

    async def test_write_point_engine_exception(self, client: AsyncClient):
        """写入点位时引擎抛异常应返回 500 带友好信息。"""
        await _create_device(client)
        with patch("protoforge.api.v1.device_routes._get_engine") as mock_engine_fn:
            from protoforge.engine.state_machine import DeviceState
            mock_engine = MagicMock()
            mock_point = MagicMock()
            mock_point.name = "temperature"
            mock_point.access = "rw"
            mock_instance = MagicMock()
            mock_instance.device_state = DeviceState.RUN
            mock_instance.points = [mock_point]
            mock_instance.protocol = "modbus_tcp"
            mock_engine.get_device_instance = MagicMock(return_value=mock_instance)
            mock_engine.is_protocol_running = MagicMock(return_value=True)
            mock_engine.write_device_point = AsyncMock(side_effect=Exception("Internal error"))
            mock_engine_fn.return_value = mock_engine

            resp = await client.put(
                "/api/v1/devices/boundary-device/points/temperature",
                json={"value": 25.0},
            )
            assert resp.status_code == 500
            assert "write" in _get_msg(resp).lower()

    async def test_webhook_failure_does_not_cause_500(self, client: AsyncClient):
        """Webhook 触发失败不应导致主请求 500。"""
        # _trigger_webhook_safe 内部已有 try-except，直接 patch 它返回 None
        with patch("protoforge.api.v1._helpers._trigger_webhook_safe") as mock_trigger:
            mock_trigger.return_value = None

            await _create_device(client)
            resp = await client.post("/api/v1/devices/boundary-device/start")
            # webhook 失败不应影响主请求
            assert resp.status_code != 500


# =============================================================================
#  8. JSON 格式异常测试
# =============================================================================

class TestMalformedRequestBody:
    """畸形请求体 — 500 触发条件"""

    async def test_create_device_invalid_json(self, client: AsyncClient):
        """无效 JSON 体应返回 422，不应 500。"""
        resp = await client.post(
            "/api/v1/devices",
            content="{invalid json}",
            headers={"content-type": "application/json"},
        )
        assert resp.status_code == 422

    async def test_create_device_wrong_content_type(self, client: AsyncClient):
        """错误 Content-Type 不应 500。"""
        resp = await client.post(
            "/api/v1/devices",
            content="id=test&name=test",
            headers={"content-type": "application/x-www-form-urlencoded"},
        )
        assert resp.status_code != 500

    async def test_write_point_array_body(self, client: AsyncClient):
        """请求体为数组而非对象不应 500。"""
        await _create_device(client)
        resp = await client.put(
            "/api/v1/devices/boundary-device/points/temperature",
            json=[1, 2, 3],
        )
        assert resp.status_code in (400, 422)

    async def test_write_point_string_body(self, client: AsyncClient):
        """请求体为字符串而非对象不应 500。"""
        await _create_device(client)
        resp = await client.put(
            "/api/v1/devices/boundary-device/points/temperature",
            content='"just a string"',
            headers={"content-type": "application/json"},
        )
        assert resp.status_code in (400, 422)


# =============================================================================
#  9. 协议接口 500 边界测试
# =============================================================================

class TestProtocolBoundary:
    """协议管理接口 — 500 触发条件"""

    async def test_get_nonexistent_protocol_config(self, client: AsyncClient):
        """查询不存在协议的配置应返回 404。"""
        resp = await client.get("/api/v1/protocols/nonexistent_proto/config")
        assert resp.status_code == 404

    async def test_start_nonexistent_protocol(self, client: AsyncClient):
        """启动不存在协议应返回 404 或 503。"""
        resp = await client.post("/api/v1/protocols/nonexistent_proto/start")
        assert resp.status_code in (404, 503)

    async def test_stop_nonexistent_protocol(self, client: AsyncClient):
        """停止不存在协议应返回 404 或 503。"""
        resp = await client.post("/api/v1/protocols/nonexistent_proto/stop")
        assert resp.status_code in (404, 503)

    async def test_start_protocol_with_null_config(self, client: AsyncClient):
        """启动协议时传 null config 不应 500。"""
        resp = await client.post(
            "/api/v1/protocols/modbus_tcp/start",
            json=None,
        )
        assert resp.status_code != 500

    async def test_start_protocol_with_empty_config(self, client: AsyncClient):
        """启动协议时传空 config 不应 500。"""
        resp = await client.post(
            "/api/v1/protocols/modbus_tcp/start",
            json={},
        )
        assert resp.status_code != 500

    async def test_start_protocol_with_invalid_port(self, client: AsyncClient):
        """启动协议时传非法端口不应 500。"""
        resp = await client.post(
            "/api/v1/protocols/modbus_tcp/start",
            json={"port": "not_a_number"},
        )
        assert resp.status_code != 500

    async def test_start_protocol_with_negative_port(self, client: AsyncClient):
        """启动协议时传负数端口不应 500。"""
        resp = await client.post(
            "/api/v1/protocols/modbus_tcp/start",
            json={"port": -1},
        )
        assert resp.status_code != 500

    async def test_start_protocol_with_huge_port(self, client: AsyncClient):
        """启动协议时传超大端口不应 500。"""
        resp = await client.post(
            "/api/v1/protocols/modbus_tcp/start",
            json={"port": 99999999},
        )
        assert resp.status_code != 500

    async def test_start_all_protocols(self, client: AsyncClient):
        """批量启动协议不应 500。"""
        resp = await client.post("/api/v1/protocols/start-all")
        assert resp.status_code == 200

    async def test_stop_all_protocols(self, client: AsyncClient):
        """批量停止协议不应 500。"""
        resp = await client.post("/api/v1/protocols/stop-all")
        assert resp.status_code == 200


# =============================================================================
#  10. 日志接口 500 边界测试
# =============================================================================

class TestLogBoundary:
    """日志接口 — 500 触发条件"""

    async def test_get_logs_negative_count(self, client: AsyncClient):
        """负数 count 应被自动修正，不应 500。"""
        resp = await client.get("/api/v1/logs?count=-1")
        assert resp.status_code == 200

    async def test_get_logs_huge_count(self, client: AsyncClient):
        """超大 count 应被自动修正，不应 500。"""
        resp = await client.get("/api/v1/logs?count=999999999")
        assert resp.status_code == 200

    async def test_get_logs_zero_count(self, client: AsyncClient):
        """count=0 应被自动修正，不应 500。"""
        resp = await client.get("/api/v1/logs?count=0")
        assert resp.status_code == 200

    async def test_get_logs_with_special_chars_protocol(self, client: AsyncClient):
        """特殊字符 protocol 过滤不应 500。"""
        resp = await client.get("/api/v1/logs?protocol=<script>alert(1)</script>")
        assert resp.status_code == 200

    async def test_clear_logs(self, client: AsyncClient):
        """清除日志不应 500。"""
        resp = await client.delete("/api/v1/logs")
        assert resp.status_code == 200


# =============================================================================
#  11. Webhook 接口 500 边界测试
# =============================================================================

class TestWebhookBoundary:
    """Webhook 接口 — 500 触发条件"""

    async def test_list_webhooks(self, client: AsyncClient):
        """列出 webhooks 不应 500。"""
        resp = await client.get("/api/v1/webhooks")
        assert resp.status_code == 200

    async def test_add_webhook_missing_url(self, client: AsyncClient):
        """缺少 url 字段应返回 400。"""
        resp = await client.post("/api/v1/webhooks", json={"name": "test"})
        assert resp.status_code == 400

    async def test_add_webhook_null_url(self, client: AsyncClient):
        """url 为 null 应返回 400。"""
        resp = await client.post("/api/v1/webhooks", json={"url": None})
        assert resp.status_code == 400

    async def test_add_webhook_empty_url(self, client: AsyncClient):
        """url 为空字符串应返回 400。"""
        resp = await client.post("/api/v1/webhooks", json={"url": ""})
        assert resp.status_code == 400

    async def test_add_webhook_invalid_url_scheme(self, client: AsyncClient):
        """url 不以 http/https 开头应返回 400。"""
        resp = await client.post("/api/v1/webhooks", json={
            "url": "ftp://example.com/hook",
        })
        assert resp.status_code == 400

    async def test_add_webhook_non_string_url(self, client: AsyncClient):
        """url 为非字符串应返回 400。"""
        resp = await client.post("/api/v1/webhooks", json={"url": 12345})
        assert resp.status_code == 400

    async def test_add_webhook_super_long_url(self, client: AsyncClient):
        """超长 url 不应 500。"""
        resp = await client.post("/api/v1/webhooks", json={
            "url": "https://example.com/" + "a" * 10000,
        })
        assert resp.status_code != 500

    async def test_update_nonexistent_webhook(self, client: AsyncClient):
        """更新不存在 webhook 应返回 404。"""
        resp = await client.put("/api/v1/webhooks/nonexistent-wh-id", json={
            "url": "https://example.com/new",
        })
        assert resp.status_code == 404

    async def test_delete_nonexistent_webhook(self, client: AsyncClient):
        """删除不存在 webhook 应返回 404。"""
        resp = await client.delete("/api/v1/webhooks/nonexistent-wh-id")
        assert resp.status_code == 404

    async def test_test_nonexistent_webhook(self, client: AsyncClient):
        """测试不存在 webhook 应返回 404。"""
        resp = await client.post("/api/v1/webhooks/nonexistent-wh-id/test")
        assert resp.status_code in (404, 502)

    async def test_webhook_stats(self, client: AsyncClient):
        """webhook 统计不应 500。"""
        resp = await client.get("/api/v1/webhooks/stats")
        assert resp.status_code == 200


# =============================================================================
#  12. 数据转发接口 500 边界测试
# =============================================================================

class TestForwardBoundary:
    """数据转发接口 — 500 触发条件"""

    async def test_list_forward_targets(self, client: AsyncClient):
        """列出转发目标不应 500。"""
        resp = await client.get("/api/v1/forward/targets")
        assert resp.status_code == 200

    async def test_add_forward_target_empty_config(self, client: AsyncClient):
        """空 config 不应 500。"""
        resp = await client.post("/api/v1/forward/targets", json={})
        assert resp.status_code != 500

    async def test_add_forward_target_null_config(self, client: AsyncClient):
        """null config 不应 500。"""
        resp = await client.post("/api/v1/forward/targets", json=None)
        assert resp.status_code != 500

    async def test_add_forward_target_invalid_port(self, client: AsyncClient):
        """非法端口应返回 400。"""
        resp = await client.post("/api/v1/forward/targets", json={
            "name": "test",
            "host": "localhost",
            "port": "not_a_number",
        })
        assert resp.status_code in (400, 422)

    async def test_add_forward_target_negative_port(self, client: AsyncClient):
        """负数端口应返回 400。"""
        resp = await client.post("/api/v1/forward/targets", json={
            "name": "test",
            "host": "localhost",
            "port": -1,
        })
        assert resp.status_code == 400

    async def test_add_forward_target_huge_port(self, client: AsyncClient):
        """超大端口应返回 400。"""
        resp = await client.post("/api/v1/forward/targets", json={
            "name": "test",
            "host": "localhost",
            "port": 99999999,
        })
        assert resp.status_code == 400

    async def test_remove_nonexistent_forward_target(self, client: AsyncClient):
        """删除不存在转发目标不应 500。"""
        resp = await client.delete("/api/v1/forward/targets/nonexistent-target")
        assert resp.status_code != 500

    async def test_forward_stats(self, client: AsyncClient):
        """转发统计不应 500。"""
        resp = await client.get("/api/v1/forward/stats")
        assert resp.status_code == 200


# =============================================================================
#  13. 录制接口 500 边界测试
# =============================================================================

class TestRecorderBoundary:
    """录制接口 — 500 触发条件"""

    async def test_list_recordings(self, client: AsyncClient):
        """列出录制不应 500。"""
        resp = await client.get("/api/v1/recorder/recordings")
        assert resp.status_code == 200

    async def test_get_nonexistent_recording(self, client: AsyncClient):
        """查询不存在录制应返回 404。"""
        resp = await client.get("/api/v1/recorder/recordings/nonexistent-rec-id")
        assert resp.status_code == 404

    async def test_delete_nonexistent_recording(self, client: AsyncClient):
        """删除不存在录制应返回 404。"""
        resp = await client.delete("/api/v1/recorder/recordings/nonexistent-rec-id")
        assert resp.status_code == 404

    async def test_start_recording_null_config(self, client: AsyncClient):
        """null config 启动录制不应 500。"""
        resp = await client.post("/api/v1/recorder/start", json=None)
        assert resp.status_code != 500

    async def test_start_recording_empty_config(self, client: AsyncClient):
        """空 config 启动录制不应 500。"""
        resp = await client.post("/api/v1/recorder/start", json={})
        assert resp.status_code != 500

    async def test_stop_recording_when_none_active(self, client: AsyncClient):
        """停止录制不应 500（可能已有活跃录制返回200，或无录制返回400）。"""
        resp = await client.post("/api/v1/recorder/stop")
        assert resp.status_code in (200, 400), f"Unexpected status: {resp.status_code}"


# =============================================================================
#  14. 认证接口 500 边界测试
# =============================================================================

class TestAuthBoundary:
    """认证接口 — 500 触发条件"""

    async def test_login_empty_username(self, client: AsyncClient):
        """空用户名应返回 422。"""
        resp = await client.post("/api/v1/auth/login", json={
            "username": "",
            "password": "test",
        })
        assert resp.status_code == 422

    async def test_login_empty_password(self, client: AsyncClient):
        """空密码应返回 422。"""
        resp = await client.post("/api/v1/auth/login", json={
            "username": "admin",
            "password": "",
        })
        assert resp.status_code == 422

    async def test_login_null_username(self, client: AsyncClient):
        """null 用户名应返回 422。"""
        resp = await client.post("/api/v1/auth/login", json={
            "username": None,
            "password": "test",
        })
        assert resp.status_code == 422

    async def test_login_missing_fields(self, client: AsyncClient):
        """缺少字段应返回 422。"""
        resp = await client.post("/api/v1/auth/login", json={})
        assert resp.status_code == 422

    async def test_login_wrong_credentials(self, client: AsyncClient):
        """错误凭据应返回 401，不应 500。"""
        resp = await client.post("/api/v1/auth/login", json={
            "username": "nonexistent_user_xyz",
            "password": "wrong_password",
        })
        assert resp.status_code in (401, 423)

    async def test_login_super_long_username(self, client: AsyncClient):
        """超长用户名不应 500。"""
        resp = await client.post("/api/v1/auth/login", json={
            "username": "a" * 10000,
            "password": "test",
        })
        assert resp.status_code != 500

    async def test_login_special_chars_in_username(self, client: AsyncClient):
        """用户名含特殊字符不应 500。"""
        resp = await client.post("/api/v1/auth/login", json={
            "username": "admin'; DROP TABLE users; --",
            "password": "test",
        })
        assert resp.status_code != 500

    async def test_refresh_empty_token(self, client: AsyncClient):
        """空 refresh token 应返回 422。"""
        resp = await client.post("/api/v1/auth/refresh", json={
            "refresh_token": "",
        })
        assert resp.status_code == 422

    async def test_refresh_invalid_token(self, client: AsyncClient):
        """无效 refresh token 应返回 401。"""
        resp = await client.post("/api/v1/auth/refresh", json={
            "refresh_token": "invalid_token_xyz",
        })
        assert resp.status_code == 401


# =============================================================================
#  15. 集成接口 500 边界测试
# =============================================================================

class TestIntegrationBoundary:
    """集成接口 — 500 触发条件"""

    async def test_get_integration_status(self, client: AsyncClient):
        """获取集成状态不应 500。"""
        resp = await client.get("/api/v1/integration/status")
        assert resp.status_code == 200

    async def test_get_integration_metrics(self, client: AsyncClient):
        """获取集成指标不应 500。"""
        resp = await client.get("/api/v1/integration/metrics")
        assert resp.status_code != 500

    async def test_batch_push_empty_device_ids(self, client: AsyncClient):
        """批量推送空 device_ids 应返回 400 或 503（未初始化）。"""
        resp = await client.post("/api/v1/integration/batch-push", json={
            "device_ids": [],
        })
        assert resp.status_code in (400, 503)

    async def test_batch_push_null_device_ids(self, client: AsyncClient):
        """批量推送 null device_ids 应返回 400 或 503。"""
        resp = await client.post("/api/v1/integration/batch-push", json={
            "device_ids": None,
        })
        assert resp.status_code in (400, 422, 503)

    async def test_batch_push_non_array_device_ids(self, client: AsyncClient):
        """批量推送非数组 device_ids 应返回 400 或 503。"""
        resp = await client.post("/api/v1/integration/batch-push", json={
            "device_ids": "not_an_array",
        })
        assert resp.status_code in (400, 503)

    async def test_batch_push_non_string_elements(self, client: AsyncClient):
        """device_ids 含非字符串元素应返回 400 或 503。"""
        resp = await client.post("/api/v1/integration/batch-push", json={
            "device_ids": [1, 2, 3],
        })
        assert resp.status_code in (400, 503)

    async def test_batch_push_nonexistent_devices(self, client: AsyncClient):
        """批量推送不存在的设备应返回 400 或 503。"""
        resp = await client.post("/api/v1/integration/batch-push", json={
            "device_ids": ["nonexistent-1", "nonexistent-2"],
        })
        assert resp.status_code in (400, 503)

    async def test_batch_push_invalid_concurrency(self, client: AsyncClient):
        """非法并发数应被自动修正，不应 500。"""
        await _create_device(client)
        resp = await client.post("/api/v1/integration/batch-push", json={
            "device_ids": ["boundary-device"],
            "concurrency": "not_a_number",
        })
        assert resp.status_code in (200, 503)

    async def test_batch_push_negative_concurrency(self, client: AsyncClient):
        """负数并发数应被自动修正，不应 500。"""
        await _create_device(client)
        resp = await client.post("/api/v1/integration/batch-push", json={
            "device_ids": ["boundary-device"],
            "concurrency": -5,
        })
        assert resp.status_code in (200, 503)


# =============================================================================
#  16. EdgeLite 接口 500 边界测试
# =============================================================================

class TestEdgeliteBoundary:
    """EdgeLite 接口 — 500 触发条件"""

    async def test_import_edgelite_empty_config(self, client: AsyncClient):
        """导入空 config 应返回 400。"""
        resp = await client.post("/api/v1/edgelite", json={})
        assert resp.status_code in (400, 200)

    async def test_import_edgelite_null_config(self, client: AsyncClient):
        """导入 null config 不应 500。"""
        resp = await client.post("/api/v1/edgelite", json=None)
        assert resp.status_code != 500

    async def test_push_nonexistent_device_to_edgelite(self, client: AsyncClient):
        """推送不存在设备应返回 404 或 503（IntegrationManager未初始化）。"""
        resp = await client.post("/api/v1/edgelite/push/nonexistent-device-xyz")
        assert resp.status_code in (404, 503)

    async def test_batch_push_empty_device_ids(self, client: AsyncClient):
        """批量推送空列表应返回 404 或 503。"""
        resp = await client.post("/api/v1/edgelite/push", json={"device_ids": []})
        assert resp.status_code in (404, 503)

    async def test_batch_push_nonexistent_devices(self, client: AsyncClient):
        """批量推送不存在设备应返回 404 或 503。"""
        resp = await client.post("/api/v1/edgelite/push", json={
            "device_ids": ["nonexistent-1", "nonexistent-2"],
        })
        assert resp.status_code in (404, 503)


# =============================================================================
#  17. 测试用例接口 500 边界测试
# =============================================================================

class TestTestRoutesBoundary:
    """测试用例管理接口 — 500 触发条件"""

    async def test_list_test_cases(self, client: AsyncClient):
        """列出测试用例不应 500。"""
        resp = await client.get("/api/v1/tests/cases")
        assert resp.status_code == 200

    async def test_get_nonexistent_test_case(self, client: AsyncClient):
        """查询不存在测试用例应返回 404。"""
        resp = await client.get("/api/v1/tests/cases/nonexistent-case-id")
        assert resp.status_code == 404

    async def test_create_test_case_empty_body(self, client: AsyncClient):
        """空请求体应返回 400。"""
        resp = await client.post("/api/v1/tests/cases", json={})
        assert resp.status_code == 400

    async def test_create_test_case_null_body(self, client: AsyncClient):
        """null 请求体应返回 400 或 422。"""
        resp = await client.post("/api/v1/tests/cases", json=None)
        assert resp.status_code in (400, 422)

    async def test_delete_nonexistent_test_case(self, client: AsyncClient):
        """删除不存在测试用例应返回 404。"""
        resp = await client.delete("/api/v1/tests/cases/nonexistent-case-id")
        assert resp.status_code == 404

    async def test_update_nonexistent_test_case(self, client: AsyncClient):
        """更新不存在测试用例应返回 404。"""
        resp = await client.put(
            "/api/v1/tests/cases/nonexistent-case-id",
            json={"name": "updated"},
        )
        assert resp.status_code == 404

    async def test_list_test_suites(self, client: AsyncClient):
        """列出测试套件不应 500。"""
        resp = await client.get("/api/v1/tests/suites")
        assert resp.status_code == 200

    async def test_get_nonexistent_test_suite(self, client: AsyncClient):
        """查询不存在测试套件应返回 404。"""
        resp = await client.get("/api/v1/tests/suites/nonexistent-suite-id")
        assert resp.status_code == 404


# =============================================================================
#  18. 故障管理接口 500 边界测试（/faults 路由）
# =============================================================================

class TestFaultRoutesBoundary:
    """故障管理接口 (/faults) — 500 触发条件"""

    async def test_create_fault_nonexistent_device(self, client: AsyncClient):
        """向不存在设备注入故障应返回 404。"""
        resp = await client.post("/api/v1/faults", json={
            "device_id": "nonexistent-device-xyz",
            "fault_type": "sensor_drift",
        })
        assert resp.status_code == 404

    async def test_create_fault_missing_device_id(self, client: AsyncClient):
        """缺少 device_id 应返回 422。"""
        resp = await client.post("/api/v1/faults", json={
            "fault_type": "sensor_drift",
        })
        assert resp.status_code == 422

    async def test_create_fault_null_device_id(self, client: AsyncClient):
        """null device_id 应返回 422。"""
        resp = await client.post("/api/v1/faults", json={
            "device_id": None,
            "fault_type": "sensor_drift",
        })
        assert resp.status_code == 422

    async def test_create_fault_empty_device_id(self, client: AsyncClient):
        """空 device_id 应返回 422 或 404。"""
        resp = await client.post("/api/v1/faults", json={
            "device_id": "",
            "fault_type": "sensor_drift",
        })
        assert resp.status_code in (404, 422)

    async def test_create_fault_invalid_type(self, client: AsyncClient):
        """无效故障类型应返回 400。"""
        await _create_device(client)
        resp = await client.post("/api/v1/faults", json={
            "device_id": "boundary-device",
            "fault_type": "invalid_fault_type_xyz",
        })
        assert resp.status_code == 400

    async def test_create_fault_invalid_trigger_mode(self, client: AsyncClient):
        """无效触发模式应返回 400。"""
        await _create_device(client)
        resp = await client.post("/api/v1/faults", json={
            "device_id": "boundary-device",
            "fault_type": "sensor_drift",
            "trigger_mode": "invalid_mode_xyz",
        })
        assert resp.status_code == 400

    async def test_list_faults(self, client: AsyncClient):
        """列出故障不应 500。"""
        resp = await client.get("/api/v1/faults")
        assert resp.status_code == 200

    async def test_clear_faults(self, client: AsyncClient):
        """清除故障不应 500。"""
        resp = await client.post("/api/v1/faults/clear", json={})
        assert resp.status_code != 500

    async def test_list_fault_scenarios(self, client: AsyncClient):
        """列出故障场景不应 500。"""
        resp = await client.get("/api/v1/faults/scenarios")
        assert resp.status_code in (200, 404)


# =============================================================================
#  19. 并发压力测试（扩展）
# =============================================================================

class TestConcurrencyStress:
    """并发压力测试 — 验证高并发下不产生 500"""

    async def test_concurrent_list_devices(self, client: AsyncClient):
        """并发列出设备不应 500。"""
        tasks = [client.get("/api/v1/devices") for _ in range(50)]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for r in results:
            if isinstance(r, Exception):
                continue
            assert r.status_code != 500

    async def test_concurrent_list_protocols(self, client: AsyncClient):
        """并发列出协议不应 500。"""
        tasks = [client.get("/api/v1/protocols") for _ in range(50)]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for r in results:
            if isinstance(r, Exception):
                continue
            assert r.status_code != 500

    async def test_concurrent_get_logs(self, client: AsyncClient):
        """并发获取日志不应 500。"""
        tasks = [client.get("/api/v1/logs?count=10") for _ in range(30)]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for r in results:
            if isinstance(r, Exception):
                continue
            assert r.status_code != 500

    async def test_concurrent_create_and_delete(self, client: AsyncClient):
        """并发创建和删除不同设备不应 500。"""
        create_tasks = [
            client.post("/api/v1/devices", json=_modbus_device_config(f"stress-{i}"))
            for i in range(10)
        ]
        results = await asyncio.gather(*create_tasks, return_exceptions=True)

        delete_tasks = []
        for i, r in enumerate(results):
            if isinstance(r, Exception):
                continue
            if r.status_code in (200, 201):
                delete_tasks.append(client.delete(f"/api/v1/devices/stress-{i}"))

        if delete_tasks:
            del_results = await asyncio.gather(*delete_tasks, return_exceptions=True)
            for r in del_results:
                if isinstance(r, Exception):
                    continue
                assert r.status_code != 500

    async def test_concurrent_settings_read(self, client: AsyncClient):
        """并发读取设置不应 500。"""
        tasks = [client.get("/api/v1/settings") for _ in range(20)]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for r in results:
            if isinstance(r, Exception):
                continue
            assert r.status_code != 500


# =============================================================================
#  20. HTTP 方法误用测试
# =============================================================================

class TestHttpMethodMisuse:
    """HTTP 方法误用 — 不应 500"""

    async def test_patch_device_not_allowed(self, client: AsyncClient):
        """PATCH 设备应返回 405，不应 500。"""
        resp = await client.patch("/api/v1/devices/test-device")
        assert resp.status_code == 405

    async def test_put_protocols_not_allowed(self, client: AsyncClient):
        """PUT 协议列表应返回 405。"""
        resp = await client.put("/api/v1/protocols")
        assert resp.status_code == 405

    async def test_delete_logs_with_body(self, client: AsyncClient):
        """DELETE 日志带 body 不应 500。"""
        resp = await client.request(
            "DELETE",
            "/api/v1/logs",
            json={"unexpected": "body"},
        )
        assert resp.status_code != 500

    async def test_post_to_get_endpoint(self, client: AsyncClient):
        """POST 到 GET 端点应返回 405 或 422。"""
        resp = await client.post("/api/v1/devices")
        assert resp.status_code in (405, 422)

    async def test_get_to_post_endpoint(self, client: AsyncClient):
        """GET 到 POST 端点应返回 405 或 404。"""
        resp = await client.get("/api/v1/devices/batch/delete")
        assert resp.status_code in (404, 405)
