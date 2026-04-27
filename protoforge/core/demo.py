import logging
from typing import Any

from protoforge.config import get_protocol_port_map

logger = logging.getLogger(__name__)


async def seed_demo_data(engine: Any, template_manager: Any) -> None:
    logger.info("Seeding demo data...")

    port_map = get_protocol_port_map()

    def _cfg(name: str) -> dict:
        return port_map.get(name, {"host": "0.0.0.0", "port": 0})

    await engine.start_protocol("modbus_tcp", _cfg("modbus_tcp"))
    logger.info("  ✓ Modbus TCP 协议已启动 (端口 %s)", _cfg("modbus_tcp").get("port"))

    try:
        await engine.start_protocol("mqtt", _cfg("mqtt"))
        logger.info("  ✓ MQTT 协议已启动 (端口 %s)", _cfg("mqtt").get("port"))
    except Exception as e:
        logger.warning("  ✗ MQTT 协议启动失败 (需安装 amqtt): %s", e)

    try:
        await engine.start_protocol("mc", _cfg("mc"))
        logger.info("  ✓ MC 协议已启动 (端口 %s)", _cfg("mc").get("port"))
    except Exception as e:
        logger.warning("  ✗ MC 协议启动失败: %s", e)

    try:
        await engine.start_protocol("fanuc", _cfg("fanuc"))
        logger.info("  ✓ FANUC 协议已启动 (端口 %s)", _cfg("fanuc").get("port"))
    except Exception as e:
        logger.warning("  ✗ FANUC 协议启动失败: %s", e)

    try:
        await engine.start_protocol("toledo", _cfg("toledo"))
        logger.info("  ✓ Toledo 协议已启动 (端口 %s)", _cfg("toledo").get("port"))
    except Exception as e:
        logger.warning("  ✗ Toledo 协议启动失败: %s", e)

    try:
        await engine.start_protocol("profinet", _cfg("profinet"))
        logger.info("  ✓ PROFINET IO 协议已启动 (端口 %s)", _cfg("profinet").get("port"))
    except Exception as e:
        logger.warning("  ✗ PROFINET IO 协议启动失败: %s", e)

    try:
        await engine.start_protocol("ethercat", _cfg("ethercat"))
        logger.info("  ✓ EtherCAT 协议已启动 (端口 %s)", _cfg("ethercat").get("port"))
    except Exception as e:
        logger.warning("  ✗ EtherCAT 协议启动失败: %s", e)

    demo_devices = [
        {
            "id": "demo-temp-sensor",
            "name": "温湿度传感器-1",
            "protocol": "modbus_tcp",
            "template_id": "modbus_temperature_sensor",
            "points": [
                {"name": "temperature", "address": "0", "data_type": "float32", "generator_type": "sine", "min_value": 15, "max_value": 35},
                {"name": "humidity", "address": "2", "data_type": "float32", "generator_type": "sine", "min_value": 30, "max_value": 80},
                {"name": "alarm_temp_high", "address": "4", "data_type": "bool", "generator_type": "fixed", "min_value": 0, "max_value": 1},
            ],
        },
        {
            "id": "demo-plc-s7",
            "name": "西门子S7-1200",
            "protocol": "modbus_tcp",
            "template_id": "siemens_s7_1200",
            "points": [
                {"name": "running", "address": "0", "data_type": "bool", "generator_type": "fixed", "min_value": 1, "max_value": 1},
                {"name": "speed", "address": "1", "data_type": "float32", "generator_type": "sine", "min_value": 800, "max_value": 1500},
                {"name": "temperature", "address": "3", "data_type": "float32", "generator_type": "random", "min_value": 40, "max_value": 85},
            ],
        },
        {
            "id": "demo-smart-lock",
            "name": "智能门锁",
            "protocol": "mqtt",
            "template_id": "smart_lock",
            "points": [
                {"name": "locked", "address": "0", "data_type": "bool", "generator_type": "fixed", "min_value": 1, "max_value": 1},
                {"name": "battery", "address": "1", "data_type": "int32", "generator_type": "random", "min_value": 20, "max_value": 100},
            ],
        },
        {
            "id": "demo-flow-meter",
            "name": "流量计",
            "protocol": "modbus_tcp",
            "template_id": "flow_meter",
            "points": [
                {"name": "flow_rate", "address": "0", "data_type": "float32", "generator_type": "sine", "min_value": 0, "max_value": 100},
                {"name": "total", "address": "2", "data_type": "float32", "generator_type": "sawtooth", "min_value": 0, "max_value": 99999},
                {"name": "alarm", "address": "4", "data_type": "bool", "generator_type": "fixed", "min_value": 0, "max_value": 0},
            ],
        },
        {
            "id": "demo-mc-fx5u",
            "name": "三菱FX5U PLC",
            "protocol": "mc",
            "template_id": "mc_fx5u",
            "points": [
                {"name": "run_status", "address": "D0", "data_type": "uint16", "generator_type": "fixed", "fixed_value": 1},
                {"name": "speed_rpm", "address": "D4", "data_type": "float32", "generator_type": "sine", "min_value": 500, "max_value": 3000},
                {"name": "pressure", "address": "D6", "data_type": "float32", "generator_type": "random", "min_value": 0.3, "max_value": 2.5},
            ],
        },
        {
            "id": "demo-fanuc-cnc",
            "name": "FANUC 0i-F CNC",
            "protocol": "fanuc",
            "template_id": "fanuc_0if_plus",
            "points": [
                {"name": "x_absolute", "address": "abs_x", "data_type": "float32", "generator_type": "sine", "min_value": -200, "max_value": 200},
                {"name": "spindle_speed", "address": "spindle_speed", "data_type": "float32", "generator_type": "random", "min_value": 1000, "max_value": 8000},
                {"name": "feed_rate", "address": "feed_rate", "data_type": "float32", "generator_type": "random", "min_value": 100, "max_value": 5000},
            ],
        },
        {
            "id": "demo-toledo-scale",
            "name": "梅特勒-托利多电子秤",
            "protocol": "toledo",
            "template_id": "toledo_scale",
            "points": [
                {"name": "weight", "address": "net_weight", "data_type": "float32", "generator_type": "random", "min_value": 0.5, "max_value": 50.0},
                {"name": "tare", "address": "tare_weight", "data_type": "float32", "generator_type": "fixed", "fixed_value": 2.5},
                {"name": "stable", "address": "stable_flag", "data_type": "bool", "generator_type": "fixed", "fixed_value": True},
            ],
        },
        {
            "id": "demo-profinet-io",
            "name": "PROFINET远程IO模块",
            "protocol": "profinet",
            "template_id": "profinet_io_device",
            "points": [
                {"name": "di_0_7", "address": "0", "data_type": "uint16", "generator_type": "random", "min_value": 0, "max_value": 255},
                {"name": "ai_channel0", "address": "8", "data_type": "float32", "generator_type": "random", "min_value": 18.0, "max_value": 32.0},
                {"name": "ai_channel1", "address": "12", "data_type": "float32", "generator_type": "random", "min_value": 0.5, "max_value": 3.0},
            ],
        },
        {
            "id": "demo-ethercat-servo",
            "name": "EtherCAT伺服驱动器",
            "protocol": "ethercat",
            "template_id": "ethercat_servo_drive",
            "points": [
                {"name": "status_word", "address": "0", "data_type": "uint16", "generator_type": "fixed", "fixed_value": 6371},
                {"name": "actual_position", "address": "2", "data_type": "int32", "generator_type": "random", "min_value": -100000, "max_value": 100000},
                {"name": "actual_velocity", "address": "6", "data_type": "int32", "generator_type": "random", "min_value": -3000, "max_value": 3000},
                {"name": "actual_torque", "address": "10", "data_type": "int16", "generator_type": "random", "min_value": -500, "max_value": 500},
            ],
        },
    ]

    for dev_config in demo_devices:
        try:
            from protoforge.models.device import DeviceConfig, PointConfig
            points = [PointConfig(**p) for p in dev_config["points"]]
            config = DeviceConfig(
                id=dev_config["id"], name=dev_config["name"],
                protocol=dev_config["protocol"], template_id=dev_config.get("template_id", ""),
                points=points,
            )
            await engine.create_device(config)
            await engine.start_device(dev_config["id"])
            logger.info("  ✓ 设备已创建并启动: %s", dev_config["name"])
        except Exception as e:
            logger.warning("  ✗ 设备创建失败 %s: %s", dev_config["name"], e)

    demo_scenario = {
        "id": "demo-smart-factory",
        "name": "智慧工厂演示",
        "description": "包含温湿度传感器、PLC、智能门锁和流量计的完整演示场景",
        "devices": demo_devices,
        "rules": [
            {
                "id": "rule-temp-alarm",
                "name": "高温报警",
                "rule_type": "threshold",
                "source_device_id": "demo-temp-sensor",
                "source_point": "temperature",
                "target_device_id": "demo-temp-sensor",
                "target_point": "alarm_temp_high",
                "target_value": "true",
                "condition": {"operator": ">", "value": 30, "cooldown": 10},
                "enabled": True,
            },
            {
                "id": "rule-flow-alarm",
                "name": "流量异常报警",
                "rule_type": "threshold",
                "source_device_id": "demo-flow-meter",
                "source_point": "flow_rate",
                "target_device_id": "demo-flow-meter",
                "target_point": "alarm",
                "target_value": "true",
                "condition": {"operator": ">", "value": 80, "cooldown": 15},
                "enabled": True,
            },
        ],
    }

    try:
        from protoforge.models.device import DeviceConfig, PointConfig
        from protoforge.models.scenario import ScenarioConfig, Rule, RuleType
        rules = []
        for r in demo_scenario["rules"]:
            rules.append(Rule(
                id=r["id"], name=r["name"], rule_type=RuleType(r.get("rule_type", "threshold")),
                source_device_id=r["source_device_id"], source_point=r["source_point"],
                target_device_id=r["target_device_id"], target_point=r["target_point"],
                target_value=r["target_value"], condition=r.get("condition", {}),
                enabled=r.get("enabled", True),
            ))
        scenario_devices = []
        for d in demo_scenario["devices"]:
            points = [PointConfig(**p) for p in d.get("points", [])]
            scenario_devices.append(DeviceConfig(
                id=d.get("id", ""), name=d.get("name", ""),
                protocol=d.get("protocol", ""), template_id=d.get("template_id", ""),
                points=points,
            ))
        scenario_config = ScenarioConfig(
            id=demo_scenario["id"], name=demo_scenario["name"],
            description=demo_scenario["description"],
            devices=scenario_devices,
            rules=rules,
        )
        engine.create_scenario(scenario_config)
        await engine.start_scenario(demo_scenario["id"])
        logger.info("  ✓ 场景已创建并启动: %s", demo_scenario["name"])
    except Exception as e:
        logger.warning("  ✗ 场景创建失败: %s", e)

    logger.info("Demo data seeded! 9 devices + 1 scenario ready.")
