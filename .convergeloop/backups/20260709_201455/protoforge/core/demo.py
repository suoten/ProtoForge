"""Demo data seeding module.

Provides ``seed_demo_data`` to populate the simulation engine with
pre-configured devices and scenarios for demonstration purposes.
"""

import logging
from typing import Any

from protoforge.config import get_protocol_port_map

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Protocol startup order
# ---------------------------------------------------------------------------
_DEMO_PROTOCOLS: list[str] = [
    "modbus_tcp",
    "mqtt",
    "mc",
    "fanuc",
    "toledo",
    "profinet",
    "ethercat",
    "http",
    "gb28181",
    "opcua",
    "s7",
    "bacnet",
    "ab",
]

# ---------------------------------------------------------------------------
# Scenario 1: 智能工厂演示
# ---------------------------------------------------------------------------
_DEMO_DEVICES: list[dict[str, Any]] = [
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
        "name": "西门子 S7-1200",
        "protocol": "s7",
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
        "name": "三菱 FX5U PLC",
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
        "name": "FANUC 0i-F 数控系统",
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
        "name": "PROFINET 远程IO模块",
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
        "name": "EtherCAT 伺服驱动器",
        "protocol": "ethercat",
        "template_id": "ethercat_servo_drive",
        "points": [
            {"name": "status_word", "address": "0", "data_type": "uint16", "generator_type": "fixed", "fixed_value": 6371},
            {"name": "actual_position", "address": "2", "data_type": "int32", "generator_type": "random", "min_value": -100000, "max_value": 100000},
            {"name": "actual_velocity", "address": "6", "data_type": "int32", "generator_type": "random", "min_value": -3000, "max_value": 3000},
            {"name": "actual_torque", "address": "10", "data_type": "int16", "generator_type": "random", "min_value": -500, "max_value": 500},
        ],
    },
    {
        "id": "demo-http-sensor",
        "name": "HTTP 温度传感器",
        "protocol": "http",
        "template_id": "http_rest_sensor",
        "points": [
            {"name": "temperature", "address": "/sensor/temperature", "data_type": "float32", "generator_type": "sine", "min_value": 20, "max_value": 40},
            {"name": "pressure", "address": "/sensor/pressure", "data_type": "float32", "generator_type": "random", "min_value": 900, "max_value": 1100},
            {"name": "status", "address": "/sensor/status", "data_type": "string", "generator_type": "fixed", "fixed_value": "normal"},
        ],
    },
    {
        "id": "demo-gb28181-camera",
        "name": "GB28181 摄像头",
        "protocol": "gb28181",
        "template_id": "gb28181_camera",
        "points": [
            {"name": "stream_status", "address": "stream", "data_type": "bool", "generator_type": "fixed", "fixed_value": True},
            {"name": "ptz_pan", "address": "ptz_pan", "data_type": "float32", "generator_type": "random", "min_value": -180, "max_value": 180},
            {"name": "ptz_tilt", "address": "ptz_tilt", "data_type": "float32", "generator_type": "random", "min_value": -90, "max_value": 90},
        ],
    },
    {
        "id": "demo-opcua-motor",
        "name": "OPC-UA 电机控制器",
        "protocol": "opcua",
        "template_id": "opcua_motor_controller",
        "points": [
            {"name": "rpm", "address": "ns=2;i=2", "data_type": "float32", "generator_type": "sine", "min_value": 500, "max_value": 3000},
            {"name": "torque", "address": "ns=2;i=3", "data_type": "float32", "generator_type": "random", "min_value": 5, "max_value": 50},
            {"name": "power", "address": "ns=2;i=4", "data_type": "float32", "generator_type": "random", "min_value": 0.5, "max_value": 15},
        ],
    },
    {
        "id": "demo-bacnet-controller",
        "name": "BACnet 楼宇控制器",
        "protocol": "bacnet",
        "template_id": "bacnet_ahu",
        "points": [
            {"name": "room_temp", "address": "AI:1", "data_type": "float32", "generator_type": "sine", "min_value": 18, "max_value": 30},
            {"name": "hvac_status", "address": "BI:1", "data_type": "bool", "generator_type": "fixed", "fixed_value": True},
            {"name": "fan_speed", "address": "AO:1", "data_type": "float32", "generator_type": "random", "min_value": 0, "max_value": 100},
        ],
    },
]

# ---------------------------------------------------------------------------
# Scenario 2: 水处理厂
# ---------------------------------------------------------------------------
_WATER_DEVICES: list[dict[str, Any]] = [
    {
        "id": "wtp-s7-controller",
        "name": "水处理 S7-1200 控制器",
        "protocol": "s7",
        "template_id": "siemens_s7_1200",
        "points": [
            {"name": "pump_on", "address": "0", "data_type": "bool", "generator_type": "fixed", "fixed_value": True},
            {"name": "valve_pos", "address": "1", "data_type": "float32", "generator_type": "sine", "min_value": 0, "max_value": 100},
            {"name": "pump_speed", "address": "3", "data_type": "float32", "generator_type": "random_walk", "min_value": 20, "max_value": 80},
            {"name": "total_flow", "address": "5", "data_type": "float32", "generator_type": "sine", "min_value": 0, "max_value": 500},
        ],
    },
    {
        "id": "wtp-inlet-flow",
        "name": "进水流量计",
        "protocol": "modbus_tcp",
        "template_id": "flow_meter",
        "points": [
            {"name": "flow_rate", "address": "0", "data_type": "float32", "generator_type": "sine", "min_value": 0, "max_value": 200},
            {"name": "total", "address": "2", "data_type": "float32", "generator_type": "sawtooth", "min_value": 0, "max_value": 99999},
            {"name": "pressure", "address": "4", "data_type": "float32", "generator_type": "random", "min_value": 2.0, "max_value": 6.0},
        ],
    },
    {
        "id": "wtp-ph-sensor",
        "name": "pH水质传感器",
        "protocol": "modbus_tcp",
        "template_id": "modbus_ph_sensor",
        "points": [
            {"name": "ph_value", "address": "0", "data_type": "float32", "generator_type": "sine", "min_value": 5.5, "max_value": 8.5},
            {"name": "orp_value", "address": "2", "data_type": "float32", "generator_type": "random", "min_value": 200, "max_value": 800},
            {"name": "alarm_high", "address": "4", "data_type": "bool", "generator_type": "fixed", "fixed_value": False},
        ],
    },
    {
        "id": "wtp-turbidity",
        "name": "浊度传感器",
        "protocol": "modbus_tcp",
        "template_id": "modbus_turbidity",
        "points": [
            {"name": "turbidity_ntu", "address": "0", "data_type": "float32", "generator_type": "random_walk", "min_value": 0, "max_value": 50},
            {"name": "alarm_high", "address": "2", "data_type": "bool", "generator_type": "fixed", "fixed_value": False},
        ],
    },
    {
        "id": "wtp-chlorine",
        "name": "余氯分析仪",
        "protocol": "modbus_tcp",
        "template_id": "modbus_chlorine",
        "points": [
            {"name": "cl2_mgl", "address": "0", "data_type": "float32", "generator_type": "random_walk", "min_value": 0.1, "max_value": 2.0},
            {"name": "dosing_pump_speed", "address": "2", "data_type": "float32", "generator_type": "fixed", "fixed_value": 50},
        ],
    },
]

# ---------------------------------------------------------------------------
# Scenario 3: 智能楼宇暖通空调
# ---------------------------------------------------------------------------
_HVAC_DEVICES: list[dict[str, Any]] = [
    {
        "id": "hvac-bacnet-ahu",
        "name": "BACnet 空调机组(主)",
        "protocol": "bacnet",
        "template_id": "bacnet_ahu",
        "points": [
            {"name": "room_temp", "address": "AI:1", "data_type": "float32", "generator_type": "sine", "min_value": 18, "max_value": 28},
            {"name": "supply_temp", "address": "AI:2", "data_type": "float32", "generator_type": "sine", "min_value": 10, "max_value": 18},
            {"name": "hvac_status", "address": "BI:1", "data_type": "bool", "generator_type": "fixed", "fixed_value": True},
            {"name": "fan_speed", "address": "AO:1", "data_type": "float32", "generator_type": "random", "min_value": 0, "max_value": 100},
            {"name": "co2_level", "address": "AI:3", "data_type": "float32", "generator_type": "random_walk", "min_value": 400, "max_value": 1500},
            {"name": "damper_pos", "address": "AO:2", "data_type": "float32", "generator_type": "random", "min_value": 0, "max_value": 100},
        ],
    },
    {
        "id": "hvac-zone-1",
        "name": "1区温控器",
        "protocol": "modbus_tcp",
        "template_id": "modbus_thermostat",
        "points": [
            {"name": "zone_temp", "address": "0", "data_type": "float32", "generator_type": "sine", "min_value": 20, "max_value": 26},
            {"name": "setpoint", "address": "2", "data_type": "float32", "generator_type": "fixed", "fixed_value": 23},
            {"name": "occupancy", "address": "4", "data_type": "bool", "generator_type": "fixed", "fixed_value": True},
        ],
    },
    {
        "id": "hvac-zone-2",
        "name": "2区温控器",
        "protocol": "modbus_tcp",
        "template_id": "modbus_thermostat",
        "points": [
            {"name": "zone_temp", "address": "0", "data_type": "float32", "generator_type": "sine", "min_value": 21, "max_value": 27},
            {"name": "setpoint", "address": "2", "data_type": "float32", "generator_type": "fixed", "fixed_value": 24},
            {"name": "occupancy", "address": "4", "data_type": "bool", "generator_type": "fixed", "fixed_value": False},
        ],
    },
    {
        "id": "hvac-chiller",
        "name": "冷水机组",
        "protocol": "modbus_tcp",
        "template_id": "modbus_chiller",
        "points": [
            {"name": "chilled_water_temp", "address": "0", "data_type": "float32", "generator_type": "sine", "min_value": 5, "max_value": 10},
            {"name": "condenser_temp", "address": "2", "data_type": "float32", "generator_type": "random", "min_value": 25, "max_value": 40},
            {"name": "compressor_status", "address": "4", "data_type": "bool", "generator_type": "fixed", "fixed_value": True},
        ],
    },
    {
        "id": "hvac-boiler",
        "name": "锅炉机组",
        "protocol": "modbus_tcp",
        "template_id": "modbus_boiler",
        "points": [
            {"name": "hot_water_temp", "address": "0", "data_type": "float32", "generator_type": "sine", "min_value": 55, "max_value": 85},
            {"name": "burner_status", "address": "2", "data_type": "bool", "generator_type": "fixed", "fixed_value": True},
            {"name": "gas_valve", "address": "3", "data_type": "float32", "generator_type": "random", "min_value": 0, "max_value": 100},
        ],
    },
]

# ---------------------------------------------------------------------------
# Scenario 4: 数控加工单元
# ---------------------------------------------------------------------------
_CNC_DEVICES: list[dict[str, Any]] = [
    {
        "id": "cnc-cell-s7",
        "name": "数控单元 S7-1500 控制器",
        "protocol": "s7",
        "template_id": "siemens_s7_1500",
        "points": [
            {"name": "cell_running", "address": "0", "data_type": "bool", "generator_type": "fixed", "fixed_value": True},
            {"name": "cell_mode", "address": "1", "data_type": "uint16", "generator_type": "fixed", "fixed_value": 1},
            {"name": "workorder_count", "address": "2", "data_type": "uint16", "generator_type": "sawtooth", "min_value": 0, "max_value": 9999},
            {"name": "cycle_time_sec", "address": "4", "data_type": "float32", "generator_type": "random", "min_value": 30, "max_value": 120},
            {"name": "quality_pass_rate", "address": "6", "data_type": "float32", "generator_type": "random_walk", "min_value": 90, "max_value": 99.5},
        ],
    },
    {
        "id": "cnc-mc-fx5u",
        "name": "数控铣床 FX5U PLC",
        "protocol": "mc",
        "template_id": "mc_fx5u",
        "points": [
            {"name": "run_status", "address": "D0", "data_type": "uint16", "generator_type": "fixed", "fixed_value": 1},
            {"name": "spindle_rpm", "address": "D4", "data_type": "float32", "generator_type": "sine", "min_value": 500, "max_value": 8000},
            {"name": "feed_rate", "address": "D8", "data_type": "float32", "generator_type": "random", "min_value": 50, "max_value": 3000},
            {"name": "coolant_pressure", "address": "D10", "data_type": "float32", "generator_type": "random", "min_value": 0.5, "max_value": 8.0},
            {"name": "tool_number", "address": "D12", "data_type": "uint16", "generator_type": "fixed", "fixed_value": 1},
        ],
    },
    {
        "id": "cnc-fanuc-0i",
        "name": "FANUC 0i-T 数控车床",
        "protocol": "fanuc",
        "template_id": "fanuc_0if_plus",
        "points": [
            {"name": "x_position", "address": "abs_x", "data_type": "float32", "generator_type": "sine", "min_value": -100, "max_value": 100},
            {"name": "z_position", "address": "abs_z", "data_type": "float32", "generator_type": "sine", "min_value": -300, "max_value": 300},
            {"name": "spindle_speed", "address": "spindle_speed", "data_type": "float32", "generator_type": "sine", "min_value": 500, "max_value": 3000},
            {"name": "load_meter", "address": "load_meter", "data_type": "float32", "generator_type": "random_walk", "min_value": 0, "max_value": 100},
            {"name": "cycle_time", "address": "cycle_time", "data_type": "float32", "generator_type": "random", "min_value": 20, "max_value": 300},
        ],
    },
    {
        "id": "cnc-servo-drive",
        "name": "EtherCAT 伺服轴1",
        "protocol": "ethercat",
        "template_id": "ethercat_servo_drive",
        "points": [
            {"name": "status_word", "address": "0", "data_type": "uint16", "generator_type": "fixed", "fixed_value": 6371},
            {"name": "actual_position", "address": "2", "data_type": "int32", "generator_type": "sine", "min_value": -50000, "max_value": 50000},
            {"name": "actual_velocity", "address": "6", "data_type": "int32", "generator_type": "random", "min_value": -1500, "max_value": 1500},
            {"name": "actual_torque", "address": "10", "data_type": "int16", "generator_type": "random_walk", "min_value": -300, "max_value": 300},
            {"name": "drive_temp", "address": "14", "data_type": "float32", "generator_type": "random", "min_value": 20, "max_value": 75},
        ],
    },
    {
        "id": "cnc-profinet-io",
        "name": "PROFINET 远程IO",
        "protocol": "profinet",
        "template_id": "profinet_io_device",
        "points": [
            {"name": "digital_inputs", "address": "0", "data_type": "uint16", "generator_type": "random", "min_value": 0, "max_value": 255},
            {"name": "ai_pressure", "address": "8", "data_type": "float32", "generator_type": "random", "min_value": 0, "max_value": 10},
            {"name": "ai_vibration", "address": "12", "data_type": "float32", "generator_type": "random_walk", "min_value": 0, "max_value": 10},
        ],
    },
    {
        "id": "cnc-toledo-measure",
        "name": "托利多零件测量",
        "protocol": "toledo",
        "template_id": "toledo_scale",
        "points": [
            {"name": "part_weight", "address": "net_weight", "data_type": "float32", "generator_type": "random", "min_value": 0.5, "max_value": 50.0},
            {"name": "tare_weight", "address": "tare_weight", "data_type": "float32", "generator_type": "fixed", "fixed_value": 1.2},
            {"name": "measurement_ok", "address": "stable_flag", "data_type": "bool", "generator_type": "fixed", "fixed_value": True},
        ],
    },
]

# ---------------------------------------------------------------------------
# Scenario configs: (id, name, devices, rules)
# ---------------------------------------------------------------------------
_SCENARIO_CONFIGS: list[tuple[str, str, list[dict[str, Any]], list[dict[str, Any]]]] = [
    ("demo-smart-factory", "智能工厂演示", _DEMO_DEVICES, [
        {"id": "rule-temp-alarm", "name": "高温报警", "rule_type": "threshold",
         "source_device_id": "demo-temp-sensor", "source_point": "temperature",
         "target_device_id": "demo-temp-sensor", "target_point": "alarm_temp_high",
         "target_value": "true", "condition": {"operator": ">", "value": 30, "cooldown": 10}, "enabled": True},
        {"id": "rule-flow-alarm", "name": "流量异常报警", "rule_type": "threshold",
         "source_device_id": "demo-flow-meter", "source_point": "flow_rate",
         "target_device_id": "demo-flow-meter", "target_point": "alarm",
         "target_value": "true", "condition": {"operator": ">", "value": 80, "cooldown": 15}, "enabled": True},
    ]),
    ("demo-water-treatment", "水处理厂", _WATER_DEVICES, [
        {"id": "wtp-ph-high-alarm", "name": "pH值偏高报警", "rule_type": "threshold",
         "source_device_id": "wtp-ph-sensor", "source_point": "ph_value",
         "target_device_id": "wtp-ph-sensor", "target_point": "alarm_high",
         "target_value": "true", "condition": {"operator": ">", "value": 8.0, "cooldown": 30}, "enabled": True},
        {"id": "wtp-turbidity-alarm", "name": "浊度偏高报警", "rule_type": "threshold",
         "source_device_id": "wtp-turbidity", "source_point": "turbidity_ntu",
         "target_device_id": "wtp-turbidity", "target_point": "alarm_high",
         "target_value": "true", "condition": {"operator": ">", "value": 30, "cooldown": 60}, "enabled": True},
        {"id": "wtp-chlorine-low", "name": "余氯偏低预警", "rule_type": "threshold",
         "source_device_id": "wtp-chlorine", "source_point": "cl2_mgl",
         "target_device_id": "wtp-chlorine", "target_point": "dosing_pump_speed",
         "target_value": "80", "condition": {"operator": "<", "value": 0.5, "cooldown": 120}, "enabled": True},
        {"id": "wtp-valve-modulate", "name": "流量调节阀门", "rule_type": "threshold",
         "source_device_id": "wtp-inlet-flow", "source_point": "flow_rate",
         "target_device_id": "wtp-s7-controller", "target_point": "valve_pos",
         "target_value": "60", "condition": {"operator": ">", "value": 150, "cooldown": 5}, "enabled": True},
    ]),
    ("demo-smart-hvac", "智能楼宇暖通空调", _HVAC_DEVICES, [
        {"id": "hvac-co2-high", "name": "CO2偏高→开风门", "rule_type": "threshold",
         "source_device_id": "hvac-bacnet-ahu", "source_point": "co2_level",
         "target_device_id": "hvac-bacnet-ahu", "target_point": "damper_pos",
         "target_value": "80", "condition": {"operator": ">", "value": 1000, "cooldown": 30}, "enabled": True},
        {"id": "hvac-zone1-cool", "name": "1区制冷需求", "rule_type": "threshold",
         "source_device_id": "hvac-zone-1", "source_point": "zone_temp",
         "target_device_id": "hvac-bacnet-ahu", "target_point": "fan_speed",
         "target_value": "75", "condition": {"operator": ">", "value": 25, "cooldown": 20}, "enabled": True},
        {"id": "hvac-chiller-high-temp", "name": "冷水机冷凝温度过高", "rule_type": "threshold",
         "source_device_id": "hvac-chiller", "source_point": "condenser_temp",
         "target_device_id": "hvac-chiller", "target_point": "compressor_status",
         "target_value": "false", "condition": {"operator": ">", "value": 38, "cooldown": 60}, "enabled": True},
        {"id": "hvac-occupancy-night", "name": "无人夜间节能模式", "rule_type": "value_change",
         "source_device_id": "hvac-zone-2", "source_point": "occupancy",
         "target_device_id": "hvac-zone-2", "target_point": "setpoint",
         "target_value": "18", "condition": {"logic": "and", "delta": None}, "enabled": False},
    ]),
    ("demo-cnc-cell", "数控加工单元", _CNC_DEVICES, [
        {"id": "cnc-servo-temp-high", "name": "伺服驱动器过温", "rule_type": "threshold",
         "source_device_id": "cnc-servo-drive", "source_point": "drive_temp",
         "target_device_id": "cnc-cell-s7", "target_point": "cell_mode",
         "target_value": "3", "condition": {"operator": ">", "value": 70, "cooldown": 30}, "enabled": True},
        {"id": "cnc-coolant-low", "name": "冷却液压力偏低", "rule_type": "threshold",
         "source_device_id": "cnc-mc-fx5u", "source_point": "coolant_pressure",
         "target_device_id": "cnc-cell-s7", "target_point": "cell_mode",
         "target_value": "2", "condition": {"operator": "<", "value": 1.0, "cooldown": 10}, "enabled": True},
        {"id": "cnc-quality-alarm", "name": "合格率偏低报警", "rule_type": "threshold",
         "source_device_id": "cnc-cell-s7", "source_point": "quality_pass_rate",
         "target_device_id": "cnc-cell-s7", "target_point": "workorder_count",
         "target_value": "0", "condition": {"operator": "<", "value": 95, "cooldown": 300}, "enabled": True},
        {"id": "cnc-cycle-time-slow", "name": "加工周期超时", "rule_type": "threshold",
         "source_device_id": "cnc-cell-s7", "source_point": "cycle_time_sec",
         "target_device_id": "cnc-cell-s7", "target_point": "cell_mode",
         "target_value": "4", "condition": {"operator": ">", "value": 100, "cooldown": 120}, "enabled": True},
    ]),
]


async def _start_demo_protocols(engine: Any) -> None:
    """Start all demo protocols with error handling.

    Each protocol is started independently; failures are logged as warnings
    but do not prevent other protocols from starting.
    """
    port_map = get_protocol_port_map()

    def _cfg(name: str) -> dict[str, Any]:
        return port_map.get(name, {"host": "0.0.0.0", "port": 0})

    for proto_name in _DEMO_PROTOCOLS:
        try:
            await engine.start_protocol(proto_name, _cfg(proto_name))
            logger.info("  ✓ %s started (port %s)", proto_name, _cfg(proto_name).get("port"))
        except Exception as e:
            logger.warning("  ✗ %s start failed: %s", proto_name, e)


async def _create_demo_device(engine: Any, dev_config: dict[str, Any]) -> None:
    """Create and start a single demo device.

    Args:
        engine: The simulation engine instance.
        dev_config: Device configuration dictionary with id, name, protocol,
            template_id, and points.
    """
    try:
        from protoforge.models.device import DeviceConfig, PointConfig

        points = [PointConfig(**p) for p in dev_config["points"]]
        config = DeviceConfig(
            id=dev_config["id"],
            name=dev_config["name"],
            protocol=dev_config["protocol"],
            template_id=dev_config.get("template_id", ""),
            points=points,
        )
        await engine.create_device(config)
        await engine.start_device(dev_config["id"])
        logger.info("  ✓ Device created and started: %s", dev_config["name"])
    except Exception as e:
        logger.warning("  ✗ Device creation failed %s: %s", dev_config["name"], e)


async def _create_demo_scenario(
    engine: Any,
    scenario_id: str,
    scenario_name: str,
    scenario_devices: list[dict[str, Any]],
    scenario_rules: list[dict[str, Any]],
) -> None:
    """Create and start a demo scenario with its rules.

    Args:
        engine: The simulation engine instance.
        scenario_id: Unique scenario identifier.
        scenario_name: Human-readable scenario name.
        scenario_devices: List of device configuration dictionaries.
        scenario_rules: List of alarm/rule configuration dictionaries.
    """
    try:
        from protoforge.models.device import DeviceConfig, PointConfig
        from protoforge.models.scenario import Rule, RuleType, ScenarioConfig

        rules = [
            Rule(
                id=r["id"],
                name=r["name"],
                rule_type=RuleType(r.get("rule_type", "threshold")),
                source_device_id=r["source_device_id"],
                source_point=r["source_point"],
                target_device_id=r["target_device_id"],
                target_point=r["target_point"],
                target_value=r["target_value"],
                condition=r.get("condition", {}),
                enabled=r.get("enabled", True),
            )
            for r in scenario_rules
        ]
        sc_devices = [
            DeviceConfig(
                id=d.get("id", ""),
                name=d.get("name", ""),
                protocol=d.get("protocol", ""),
                template_id=d.get("template_id", ""),
                points=[PointConfig(**p) for p in d.get("points", [])],
            )
            for d in scenario_devices
        ]
        scenario_config = ScenarioConfig(
            id=scenario_id,
            name=scenario_name,
            description=f"演示场景：{scenario_name}",
            devices=sc_devices,
            rules=rules,
        )
        await engine.create_scenario(scenario_config)
        await engine.start_scenario(scenario_id)
        logger.info("  ✓ Scenario created and started: %s", scenario_name)
    except Exception as e:
        logger.warning("  ✗ Scenario creation failed %s: %s", scenario_name, e)


async def seed_demo_data(engine: Any, template_manager: Any) -> None:
    """Seed the simulation engine with demo protocols, devices, and scenarios.

    This function starts all supported protocols, creates devices across four
    demo scenarios (smart factory, water treatment, smart HVAC, CNC cell),
    and configures alarm rules for each scenario.

    Args:
        engine: The simulation engine instance to populate.
        template_manager: The template manager (unused but kept for API
            compatibility).
    """
    logger.info("Seeding demo data...")

    await _start_demo_protocols(engine)

    for scenario_id, scenario_name, scenario_devices, scenario_rules in _SCENARIO_CONFIGS:
        for dev_config in scenario_devices:
            await _create_demo_device(engine, dev_config)
        await _create_demo_scenario(engine, scenario_id, scenario_name, scenario_devices, scenario_rules)

    logger.info("Demo data seeded! %d scenarios ready.", len(_SCENARIO_CONFIGS))
