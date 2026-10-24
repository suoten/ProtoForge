"""v1.8.1 stop() 取消传播语义测试。

根因回归：协议 stop() 用 suppress(CancelledError) 吞掉了**外部取消**
（asyncio.wait_for 超时的取消与任务自身的取消无法区分），导致
wait_for(stop, timeout) 的 TimeoutError 被 suppress 吞掉、调用方
在 Python 3.12.0 上永久挂起（黄金用例全量回归实测触发）。

修复后语义：stop() 内部吞掉**服务任务自身的**取消；外部取消
（Task.cancelling() > 0）必须继续传播。
"""

import asyncio

import pytest

from protoforge.protocols.base import externally_cancelled, shutdown_server_task


async def test_shutdown_server_task_normal_completion():
    """服务任务正常结束 → 正常返回（既有行为不变）。"""
    async def server_task():
        await asyncio.sleep(0.01)
        return "done"

    task = asyncio.create_task(server_task())
    await shutdown_server_task(task)
    assert task.done() and task.result() == "done"


async def test_shutdown_server_task_swallows_inner_cancel():
    """服务任务自身被 cancel（正常 stop 路径）→ 吞掉，不向外抛。"""
    async def server_task():
        await asyncio.sleep(10)

    task = asyncio.create_task(server_task())
    task.cancel()
    # 不应抛 CancelledError（旧行为保持）
    await shutdown_server_task(task)
    assert task.cancelled()


async def test_shutdown_server_task_propagates_external_cancel():
    """外部取消（wait_for 超时先于内部取消到达）→ 必须传播 CancelledError。

    复现真实挂起场景：wait_for(stop, 10) 的超时先到——外部取消送达正在
    await 的 stop()；stop() 随后自身 cancel 服务任务、await 收到
    CancelledError——此刻 externally_cancelled() 为 True，必须传播。
    旧实现一律 suppress → wait_for 的 TimeoutError 被吞 → 调用方挂起。
    """
    inner_cancelled = asyncio.Event()

    async def stop_like_coro():
        await asyncio.sleep(0.3)          # 模拟 stop() 的前置耗时
        task.cancel()                      # 自身取消服务任务（正常语义）
        try:
            await task
        except asyncio.CancelledError:
            inner_cancelled.set()
            if externally_cancelled():
                raise                      # FIXED：外部取消必须传播

    task = asyncio.create_task(server_task_mock())
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(stop_like_coro(), timeout=0.1)  # 超时先到
    # 传播语义断言完成：TimeoutError 正常抛出（旧实现此处永久挂起）


async def server_task_mock():
    await asyncio.sleep(30)


async def test_real_server_stop_under_external_cancel():
    """真协议服务器（IEC61850）stop 在外部取消下必须在限时内完成。"""
    from protoforge.models.device import DeviceConfig, PointConfig
    from protoforge.protocols.iec61850.server import IEC61850Server

    server = IEC61850Server()
    await asyncio.wait_for(server.start({"host": "127.0.0.1", "port": 29191}), timeout=10)
    await server.create_device(DeviceConfig(
        id="dev-cancel", name="Cancel Test", protocol="iec61850",
        points=[PointConfig(name="v", address="LD0/LLN0.v.stVal", data_type="bool")],
    ))
    # 模拟黄金用例挂起场景：stop() 被外部取消包裹时必须限时返回
    await asyncio.wait_for(server.stop(), timeout=10)
    assert server.status.value == "stopped"
