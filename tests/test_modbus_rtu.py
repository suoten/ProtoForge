import pytest

from protoforge.protocols.modbus.rtu_server import ModbusRtuServer


def test_modbus_rtu_config_schema():
    server = ModbusRtuServer()
    schema = server.get_config_schema()
    assert "properties" in schema
    assert "port" in schema["properties"]
    assert "baudrate" in schema["properties"]
    assert schema["properties"]["baudrate"]["default"] == 9600


def test_modbus_rtu_protocol_name():
    server = ModbusRtuServer()
    assert server.protocol_name == "modbus_rtu"
    assert server.protocol_display_name == "Modbus RTU"


def test_modbus_rtu_initial_status():
    server = ModbusRtuServer()
    from protoforge.protocols.base import ProtocolStatus
    assert server.status == ProtocolStatus.STOPPED
