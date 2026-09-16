"""Probe: is the internal publish loop alive and does _publish_device deliver?"""
import asyncio
import os
import sys

os.environ["PROTOFORGE_NO_AUTH"] = "1"
os.environ.setdefault("PROTOFORGE_ADMIN_PASSWORD", "probe-pw")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from amqtt.client import MQTTClient
from amqtt.mqtt.constants import QOS_0

from protoforge.engine.engine import SimulationEngine
from protoforge.models.device import DeviceConfig, PointConfig
from protoforge.protocols.mqtt.server import MqttBroker


async def main() -> None:
    engine = SimulationEngine()
    await engine.start()
    broker = MqttBroker()
    engine.register_protocol_server(broker) if hasattr(engine, "register_protocol_server") else None
    await broker.start({"host": "0.0.0.0", "port": 18830})
    print("status:", broker.status)

    cfg = DeviceConfig(
        id="gps", name="gps", protocol="mqtt",
        points=[PointConfig(name="latitude", address="latitude", data_type="float64", access="rw")],
        protocol_config={"topic_prefix": "protoforge", "qos": 0, "publish_interval": 2},
    )
    await broker.create_device(cfg)
    print("is_external_device(gps):", broker._is_external_device("gps"))
    print("publish_task alive:", broker._publish_task is not None and not broker._publish_task.done())

    sub = MQTTClient(client_id="probe_sub")
    await sub.connect("mqtt://127.0.0.1:18830/")
    await sub.subscribe([("protoforge/gps/#", QOS_0)])

    # direct publish path
    ok = await broker._publish_to_device_broker("gps", "protoforge/gps/latitude", b'{"v":1}', qos=0)
    print("direct _publish_to_device_broker returned:", ok)
    try:
        msg = await asyncio.wait_for(sub.deliver_message(), timeout=3)
        print("DIRECT DELIVERY:", msg.topic)
    except asyncio.TimeoutError:
        print("DIRECT DELIVERY: TIMEOUT - broken")

    # wait one loop cycle
    await asyncio.sleep(6)
    print("publish_task alive after 6s:", not broker._publish_task.done())
    if broker._publish_task.done():
        print("TASK EXCEPTION:", broker._publish_task.exception())
    try:
        msg = await asyncio.wait_for(sub.deliver_message(), timeout=3)
        print("LOOP DELIVERY:", msg.topic)
    except asyncio.TimeoutError:
        print("LOOP DELIVERY: TIMEOUT - loop not publishing")

    await broker.stop()
    await engine.stop()
    print("PROBE DONE")
    os._exit(0)  # amqtt 后台任务会挂住事件循环导致进程不退出，强制结束避免僵尸进程污染端口


if __name__ == "__main__":
    asyncio.run(main())
