"""最小复现：amqtt 0.11.3 内部广播 vs 回环客户端发布，哪条路能送达订阅者"""
import asyncio
import logging
import sys

from amqtt.broker import Broker
from amqtt.client import MQTTClient
from amqtt.mqtt.constants import QOS_0


async def main() -> None:
    logging.basicConfig(level=logging.DEBUG)
    # 只看 amqtt broker 关键日志，避免刷屏
    for name in list(logging.root.manager.loggerDict):
        if name.startswith("amqtt") and name not in ("amqtt.broker",):
            logging.getLogger(name).setLevel(logging.INFO)

    broker_cfg = {
        "listeners": {"default": {"type": "tcp", "bind": "127.0.0.1:18831"}},
        "plugins": {
            "amqtt.plugins.authentication.AnonymousAuthPlugin": {"allow_anonymous": True},
        },
    }
    broker = Broker(broker_cfg)
    await broker.start()

    sub = MQTTClient(client_id="sub1")
    await sub.connect("mqtt://127.0.0.1:18831/")
    await sub.subscribe([("protoforge/gps/#", QOS_0)])
    await asyncio.sleep(0.3)

    # 观察订阅表
    print("SUBSCRIPTIONS TABLE:", {
        k: [(s.client_id, s.transitions.state) for (s, q) in v]
        for k, v in broker._subscriptions.items()
    })

    # 路径1: 内部广播（ProtoForge 当前用法）
    await broker.internal_message_broadcast("protoforge/gps/latitude", b'{"v": 1}', QOS_0)
    await asyncio.sleep(0.5)

    # 路径2: 回环客户端发布
    pub = MQTTClient(client_id="pub1")
    await pub.connect("mqtt://127.0.0.1:18831/")
    await pub.publish("protoforge/gps/longitude", b'{"v": 2}', QOS_0)
    await asyncio.sleep(0.5)

    try:
        while True:
            msg = await asyncio.wait_for(sub.deliver_message(), timeout=1.0)
            print("RECV:", msg.topic, msg.data)
    except asyncio.TimeoutError:
        pass

    await pub.disconnect()
    await sub.disconnect()
    await broker.shutdown()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
