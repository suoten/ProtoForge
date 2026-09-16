"""Diagnose MQTT publish path: broker + device -> external subscriber.

Simulates exactly the user scenario: MQTTX subscribes protoforge/gps/#
on the ProtoForge embedded broker and should receive periodic data.
"""
import asyncio
import os
import sys

os.environ["PROTOFORGE_NO_AUTH"] = "1"
os.environ.setdefault("PROTOFORGE_ADMIN_PASSWORD", "diag-admin-pw")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import amqtt  # noqa: E402

print(f"amqtt version: {getattr(amqtt, '__version__', 'unknown')}")

from amqtt.client import MQTTClient  # noqa: E402
from amqtt.mqtt.constants import QOS_0  # noqa: E402

from protoforge.engine.engine import SimulationEngine  # noqa: E402
from protoforge.models.device import DeviceConfig, PointConfig  # noqa: E402


async def main() -> None:
    import amqtt.broker as _b
    import inspect
    from protoforge.protocols.mqtt.server import MqttBroker
    print("broadcast sig:", inspect.signature(_b.Broker.internal_message_broadcast))

    engine = SimulationEngine()
    await engine.start()

    # find or start the mqtt protocol
    broker = MqttBroker()
    engine.register_protocol_server(broker) if hasattr(engine, "register_protocol_server") else None
    await broker.start({"host": "0.0.0.0", "port": 18830})
    print(f"broker status: {broker.status}")

    # create GPS-like device
    cfg = DeviceConfig(
        id="gps",
        name="gps",
        protocol="mqtt",
        points=[
            PointConfig(name="latitude", address="latitude", data_type="float64", access="rw"),
            PointConfig(name="longitude", address="longitude", data_type="float64", access="rw"),
        ],
        protocol_config={"topic_prefix": "protoforge", "qos": 0, "publish_interval": 2},
    )
    await broker.create_device(cfg)

    # external subscriber (MQTTX equivalent)
    sub = MQTTClient(client_id="diag_subscriber")
    await sub.connect("mqtt://127.0.0.1:18830/")
    await sub.subscribe([("protoforge/gps/#", QOS_0)])
    print("subscriber connected + subscribed")

    # wait for publish loop (2s interval)
    received = []
    async def reader():
        for _ in range(8):
            try:
                msg = await asyncio.wait_for(sub.deliver_message(), timeout=6)
                received.append((msg.topic, bytes(msg.data)[:80]))
            except asyncio.TimeoutError:
                break

    await reader()
    if received:
        print(f"RECEIVED {len(received)} messages, sample:")
        for topic, data in received[:3]:
            print(f"  {topic} -> {data}")
        print("MQTT PUBLISH PATH OK")
    else:
        print("NO MESSAGES RECEIVED - publish path broken (matches user report)")

    await broker.stop()
    await engine.stop()


if __name__ == "__main__":
    asyncio.run(main())
