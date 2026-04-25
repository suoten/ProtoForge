import pytest

from protoforge.protocols.gb28181.server import GB28181Device, GB28181Server


def test_gb28181_device_register():
    device = GB28181Device(
        device_id="34020000001320000001",
        server_id="34020000002000000001",
        host="127.0.0.1",
        port=5061,
    )
    msg = device.make_register_request()
    assert "REGISTER" in msg
    assert "34020000001320000001" in msg
    assert "SIP/2.0" in msg


def test_gb28181_catalog_response():
    device = GB28181Device(
        device_id="34020000001320000001",
        server_id="34020000002000000001",
        host="127.0.0.1",
        port=5061,
    )
    xml = device.make_catalog_response("100")
    assert "Catalog" in xml
    assert "34020000001320000001" in xml
    assert "100" in xml


def test_gb28181_heartbeat_response():
    device = GB28181Device(
        device_id="34020000001320000001",
        server_id="34020000002000000001",
        host="127.0.0.1",
        port=5061,
    )
    xml = device.make_heartbeat_response("200")
    assert "Keepalive" in xml
    assert "OK" in xml


def test_gb28181_server_config_schema():
    server = GB28181Server()
    schema = server.get_config_schema()
    assert "properties" in schema
    assert "port" in schema["properties"]
    assert schema["properties"]["port"]["default"] == 5060
