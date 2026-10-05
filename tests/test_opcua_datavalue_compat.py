"""v1.4.3 OPC-UA 数据变化消失回归测试。

用户反馈：win10 更新到最新版后 OPC-UA 的正弦波/随机数不再变化。
根因：pyproject 对 asyncua 未设上限，用户更新时 pip 解析到 asyncua 2.0.x；
2.0 将 DataValue 的 StatusCode 字段由 ``StatusCode_`` 改名为 ``StatusCode``，
服务端 sync_point_value/_sync_loop 构造 DataValue 即抛 TypeError，且错误
只记 debug 日志 → 所有节点值静默停止更新。

修复：_make_datavalue 双版本兼容（成功关键字缓存）+ 同步错误首次 warning
降级机制 + pyproject asyncua 上限 <3.0。
"""

import asyncio
import datetime

import pytest


def test_make_datavalue_works_on_installed_asyncua():
    """_make_datavalue 在当前 asyncua（1.x 或 2.x）下都能构造出合法 DataValue。"""
    from asyncua import ua
    from protoforge.protocols.opcua.server import _make_datavalue

    dv = _make_datavalue(42.5, ua.VariantType.Float, 0, datetime.datetime.now(datetime.timezone.utc))
    assert dv.Value is not None
    assert dv.Value.VariantType == ua.VariantType.Float
    assert dv.StatusCode_.is_good() if hasattr(dv, "StatusCode_") else dv.StatusCode.is_good()


@pytest.mark.asyncio
async def test_opcua_node_values_change_after_sync():
    """端到端：sync_point_value 注入不同值后，客户端读到的节点值必须变化。

    （回归用户场景：以前该路径在 asyncua 2.0 下静默失败，值永远不变。）
    """
    from asyncua import Client

    from protoforge.models.device import DeviceConfig, PointConfig
    from protoforge.protocols.opcua.server import OpcUaServer

    server = OpcUaServer()
    await server.create_device(DeviceConfig(
        id="opc-t", name="opct", protocol="opcua",
        points=[PointConfig(name="temp", data_type="float32", address="1001")],
    ))
    await server.start({"host": "127.0.0.1", "port": 54841, "sync_interval": 0.2})
    try:
        await asyncio.sleep(0.5)
        results = []
        async with Client("opc.tcp://127.0.0.1:54841/freeopcua/server/") as client:
            node = None
            for child in await client.nodes.objects.get_children():
                if (await child.read_browse_name()).Name == "opct":
                    for p in await child.get_children():
                        if (await p.read_browse_name()).Name == "temp":
                            node = p
            assert node is not None, "未找到设备测点节点"
            for v in (11.5, 42.7):
                await server.sync_point_value("opc-t", "temp", v)
                await asyncio.sleep(0.25)
                results.append(await node.read_value())
        assert len(set(results)) >= 2, f"节点值未变化（静默同步失败回归）：{results}"
    finally:
        await server.stop()
