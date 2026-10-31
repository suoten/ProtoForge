"""v1.9.0 报文字段级解析 API 端点测试（/compliance/decode-frame）。"""

import base64

import pytest


@pytest.mark.asyncio
async def test_decode_frame_hex_request(client):
    resp = await client.post("/api/v1/compliance/decode-frame", json={
        "protocol": "modbus_tcp",
        "hex": "54 1D 00 00 00 06 01 03 00 00 00 0A",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["protocol"] == "modbus_tcp"
    assert data["summary"]
    assert data["errors"] == []
    assert any(f["name"] == "Unit ID" for f in data["fields"])
    # 字段树结构完整
    for f in data["fields"]:
        assert {"name", "offset", "length", "raw", "value", "children"} <= set(f)


@pytest.mark.asyncio
async def test_decode_frame_base64_and_colon_hex(client):
    raw = bytes.fromhex("680407000000")
    resp = await client.post("/api/v1/compliance/decode-frame", json={
        "protocol": "iec104",
        "data_base64": base64.b64encode(raw).decode(),
    })
    assert resp.status_code == 200
    assert "STARTDT_ACT" in resp.json()["summary"]

    resp2 = await client.post("/api/v1/compliance/decode-frame", json={
        "protocol": "iec104", "hex": "68:04:07:00:00:00",
    })
    assert resp2.status_code == 200


@pytest.mark.asyncio
async def test_decode_frame_validation_errors(client):
    # 缺 protocol
    resp = await client.post("/api/v1/compliance/decode-frame", json={"hex": "00"})
    assert resp.status_code == 400
    # 缺数据
    resp = await client.post("/api/v1/compliance/decode-frame", json={"protocol": "modbus_tcp"})
    assert resp.status_code == 400
    # 非法 hex
    resp = await client.post("/api/v1/compliance/decode-frame", json={
        "protocol": "modbus_tcp", "hex": "ZZZZ"})
    assert resp.status_code == 400
    # 不支持的协议
    resp = await client.post("/api/v1/compliance/decode-frame", json={
        "protocol": "modbus_ascii", "hex": "00"})
    assert resp.status_code == 400
    # 全局异常处理器可能包装 detail 键名，直接在响应文本里匹配
    assert "Supported" in resp.text


@pytest.mark.asyncio
async def test_decode_frame_lists_protocols(client):
    resp = await client.get("/api/v1/compliance/decode-frame/protocols")
    assert resp.status_code == 200
    protocols = resp.json()["protocols"]
    assert len(protocols) >= 8
    assert "modbus_tcp" in protocols and "s7" in protocols


@pytest.mark.asyncio
async def test_device_points_returns_master_status(client):
    """v1.9.0 主站设备点位响应携带 master_status（轮询统计）。"""
    from protoforge.models.device import DeviceConfig, PointConfig

    import protoforge.main as main_module
    engine = main_module._engine
    from protoforge.protocols.master.modbus_master import ModbusMasterServer
    engine.register_protocol(ModbusMasterServer())
    await engine.create_device(DeviceConfig(
        id="mst-api", name="M", protocol="modbus_master",
        protocol_config={"host": "127.0.0.1", "port": 1, "mode": "tcp",
                         "slave_id": 1, "scan_interval": 5.0, "timeout": 1.0},
        points=[PointConfig(name="v", address="HR0", data_type="uint16")],
    ))
    await engine.start_device("mst-api")
    resp = await client.get("/api/v1/devices/mst-api/points")
    assert resp.status_code == 200
    body = resp.json()
    assert body["master_status"] is not None
    assert "poll_ok" in body["master_status"]
    assert "last_error" in body["master_status"]
    assert "connected" in body["master_status"]


@pytest.mark.asyncio
async def test_device_points_master_status_null_for_slave(client):
    """从站协议（无 get_master_status）响应 master_status 为 None。"""
    from protoforge.models.device import DeviceConfig, PointConfig

    import protoforge.main as main_module
    engine = main_module._engine
    await engine.create_device(DeviceConfig(
        id="slv-api", name="S", protocol="modbus_tcp",
        protocol_config={"host": "127.0.0.1", "port": 15020},
        points=[PointConfig(name="v", address="HR0", data_type="uint16")],
    ))
    await engine.start_device("slv-api")
    resp = await client.get("/api/v1/devices/slv-api/points")
    assert resp.status_code == 200
    assert resp.json()["master_status"] is None
