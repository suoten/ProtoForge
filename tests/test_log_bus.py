import asyncio
import pytest

from protoforge.core.log_bus import LogBus


@pytest.fixture
def log_bus():
    return LogBus(max_entries=100)


def test_emit_and_get(log_bus):
    log_bus.emit("modbus_tcp", "recv", "dev-001", "read_holding", "Read 10 registers")
    log_bus.emit("opcua", "send", "dev-002", "write_node", "Write value=42")

    entries = log_bus.get_recent(count=10)
    assert len(entries) == 2
    assert entries[0]["protocol"] == "modbus_tcp"
    assert entries[1]["protocol"] == "opcua"


def test_filter_by_protocol(log_bus):
    log_bus.emit("modbus_tcp", "recv", "dev-001", "read", "Read")
    log_bus.emit("opcua", "send", "dev-002", "write", "Write")
    log_bus.emit("modbus_tcp", "recv", "dev-003", "read", "Read")

    entries = log_bus.get_recent(count=10, protocol="modbus_tcp")
    assert len(entries) == 2


def test_filter_by_device(log_bus):
    log_bus.emit("modbus_tcp", "recv", "dev-001", "read", "Read")
    log_bus.emit("opcua", "send", "dev-002", "write", "Write")

    entries = log_bus.get_recent(count=10, device_id="dev-001")
    assert len(entries) == 1
    assert entries[0]["device_id"] == "dev-001"


def test_max_entries():
    bus = LogBus(max_entries=5)
    for i in range(10):
        bus.emit("test", "recv", f"dev-{i}", "test", f"Message {i}")
    entries = bus.get_recent(count=100)
    assert len(entries) == 5


@pytest.mark.asyncio
async def test_subscribe():
    bus = LogBus()
    queue = bus.subscribe()
    bus.emit("test", "recv", "dev-001", "test", "Hello")

    entry = await asyncio.wait_for(queue.get(), timeout=1.0)
    assert entry.protocol == "test"
    assert entry.summary == "Hello"

    bus.unsubscribe(queue)

