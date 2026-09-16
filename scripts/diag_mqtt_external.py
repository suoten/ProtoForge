"""End-to-end diag: MQTT device reports to a CUSTOM external MQTT server.

Simulates the "device simulation" scenario requested by users:
- ProtoForge internal broker runs on 18830 (unused for this device)
- A plain amqtt Broker plays the user's own MQTT server on 18832
- The simulated device is configured with server_host/server_port and must
  connect as an MQTT client and report data to the external server

Phase 2 additionally verifies an unreachable external server does not crash
the publish loop (throttled warning + automatic retry).
"""
import asyncio
import os
import sys

os.environ["PROTOFORGE_NO_AUTH"] = "1"
os.environ.setdefault("PROTOFORGE_ADMIN_PASSWORD", "diag-admin-pw")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from amqtt.broker import Broker  # noqa: E402
from amqtt.client import MQTTClient  # noqa: E402
from amqtt.mqtt.constants import QOS_0  # noqa: E402

from protoforge.engine.engine import SimulationEngine  # noqa: E402
from protoforge.models.device import DeviceConfig, PointConfig  # noqa: E402
from protoforge.protocols.mqtt.server import MqttBroker  # noqa: E402


async def main() -> None:
    # ---- user's own MQTT server (external) ----
    ext_broker = Broker({
        "listeners": {"default": {"type": "tcp", "bind": "127.0.0.1:18832"}},
        "plugins": {"amqtt.plugins.authentication.AnonymousAuthPlugin": {"allow_anonymous": True}},
    })
    await ext_broker.start()

    engine = SimulationEngine()
    await engine.start()

    broker = MqttBroker()
    await broker.start({"host": "0.0.0.0", "port": 18830})
    print(f"internal broker status: {broker.status}")

    cfg = DeviceConfig(
        id="ext_gps",
        name="ext_gps",
        protocol="mqtt",
        points=[
            PointConfig(name="latitude", address="latitude", data_type="float64", access="rw"),
            PointConfig(name="speed", address="speed", data_type="float64", access="rw"),
        ],
        protocol_config={
            "topic_prefix": "protoforge", "qos": 0, "publish_interval": 1,
            # FIXED-F2: device reports to the user's own MQTT server
            "server_host": "127.0.0.1", "server_port": 18832,
        },
    )
    await broker.create_device(cfg)

    sub = MQTTClient(client_id="ext_subscriber")
    await sub.connect("mqtt://127.0.0.1:18832/")
    await sub.subscribe([("protoforge/ext_gps/#", QOS_0)])
    print("external subscriber connected + subscribed")

    received = []

    async def reader():
        for _ in range(8):
            try:
                msg = await asyncio.wait_for(sub.deliver_message(), timeout=4)
                received.append((msg.topic, bytes(msg.data)[:80]))
            except asyncio.TimeoutError:
                break

    await reader()
    if received:
        print(f"PHASE1 OK: received {len(received)} messages on EXTERNAL server, sample:")
        for topic, data in received[:3]:
            print(f"  {topic} -> {data}")
    else:
        print("PHASE1 FAIL: no messages on external server")

    # ---- phase 2: unreachable external server must not crash the loop ----
    cfg2 = DeviceConfig(
        id="bad_gps",
        name="bad_gps",
        protocol="mqtt",
        points=[PointConfig(name="v", address="v", data_type="float64", access="rw")],
        protocol_config={
            "topic_prefix": "protoforge", "qos": 0, "publish_interval": 1,
            "server_host": "127.0.0.1", "server_port": 1,  # nothing listens here
        },
    )
    await broker.create_device(cfg2)
    await asyncio.sleep(3)
    assert broker.status.value == "running", f"broker crashed: {broker.status}"
    print(f"PHASE2 OK: broker still {broker.status.value} with unreachable external server")

    await sub.disconnect()
    await broker.stop()
    await engine.stop()
    await ext_broker.shutdown()
    print("MQTT EXTERNAL BROKER PATH OK" if received else "MQTT EXTERNAL BROKER PATH BROKEN")


if __name__ == "__main__":
    asyncio.run(main())
    os._exit(0)  # amqtt 后台任务会挂住事件循环导致进程不退出，强制结束避免僵尸进程污染端口
