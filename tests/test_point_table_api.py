"""v1.7.0 点表导入 API 端点测试（POST /devices/import-point-table）。"""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from protoforge.main import app
import protoforge.main as main_module

SIEMENS_CSV = "\n".join([
    "位号,地址,数据类型,单位,读写,描述",
    "reactor_temp,DB1.DBD0,float32,℃,rw,反应釜温度",
    "agitator_run,DB1.DBX8.0,bool,,rw,搅拌机运行",
])


@pytest_asyncio.fixture
async def client():
    main_module._log_bus = __import__(
        "protoforge.observability.log_bus", fromlist=["LogBus"]).LogBus()
    from protoforge.db.session import Database
    main_module._database = Database()
    await main_module._database.connect()

    from protoforge.engine.engine import SimulationEngine
    from protoforge.engine.registry import (
        clear_all as _clear_registry,
        register_database as _register_database,
        register_engine as _register_engine,
        register_log_bus as _register_log_bus,
    )
    engine = SimulationEngine()
    await engine.start()
    _register_engine(engine)
    _register_database(main_module._database)
    _register_log_bus(main_module._log_bus)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c

    await engine.stop()
    await main_module._database.close()
    _clear_registry()


@pytest.mark.asyncio
async def test_point_table_dry_run_preview(client):
    """dry_run 只返回预览不建设备。"""
    resp = await client.post("/api/v1/devices/import-point-table", json={
        "content": SIEMENS_CSV, "file_format": "csv",
        "protocol": "s7", "dry_run": True,
    })
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "preview"
    assert data["total_points"] == 2
    assert "siemens_db" in data["style_counts"]
    assert data["points"][0]["name"] == "reactor_temp"
    assert data["points"][0]["data_type"] == "float32"


@pytest.mark.asyncio
async def test_point_table_create_device(client):
    """正式导入建设备 + 点位齐全 + 冲突预检通过。"""
    csv_text = "\n".join([
        "name,address,data_type,unit",
        "pt_a,DB1.DBD0,float32,℃",
        "pt_b,DB1.DBD4,float32,kPa",
        "pt_c,DB1.DBX8.0,bool,",
    ])
    resp = await client.post("/api/v1/devices/import-point-table", json={
        "content": csv_text, "file_format": "csv",
        "protocol": "s7", "dry_run": False,
        "device_id": "pt-import-test", "device_name": "点表导入测试",
        "auto_start": False,
    })
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "created"
    assert data["device_id"] == "pt-import-test"
    assert data["total_points"] == 3

    # 清理
    del_resp = await client.delete("/api/v1/devices/pt-import-test")
    assert del_resp.status_code in (200, 404)


@pytest.mark.asyncio
async def test_point_table_conflict_rejected_422(client):
    """Modbus 寄存器重叠 → 422 拒绝（全局异常处理器把 detail 字符串化，
    因此断言状态码 + 冲突关键字而非结构化字段）。"""
    csv_text = "\n".join([
        "name,address,data_type",
        "over_a,40001,float32",
        "over_b,40002,uint16",
    ])
    resp = await client.post("/api/v1/devices/import-point-table", json={
        "content": csv_text, "file_format": "csv",
        "protocol": "modbus_tcp", "dry_run": False,
        "device_id": "pt-conflict-test",
    })
    assert resp.status_code == 422
    body = resp.text
    assert "conflict" in body.lower() or "重叠" in body or "rejected" in body.lower(), body[:300]

    # 预览模式同内容应能成功返回（冲突只阻止正式导入）
    resp2 = await client.post("/api/v1/devices/import-point-table", json={
        "content": csv_text, "file_format": "csv",
        "protocol": "modbus_tcp", "dry_run": True,
    })
    assert resp2.status_code == 200
    assert resp2.json()["conflicts"]


@pytest.mark.asyncio
async def test_point_table_missing_columns_rejected(client):
    resp = await client.post("/api/v1/devices/import-point-table", json={
        "content": "foo,bar\n1,2\n", "file_format": "csv",
        "protocol": "modbus_tcp", "dry_run": True,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert not data["ok"]
    assert data["errors"]
