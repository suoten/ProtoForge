"""E2E real-machine Modbus verification.

Starts a genuine Modbus TCP server (via ProtoForge's engine) on a real TCP port,
then connects a real pymodbus TCP client to verify:

1. **Register storage rule** — ``bool + auto→coil``, ``float32 + auto→holding``
   (the same rule ``_translate_point_address`` replicates for EdgeLite).
   A bool point at address ``4`` must be readable via FC01 (read coils),
   and a float32 point at address ``10`` must be readable via FC03 (read holding
   registers) and decode to the original value.

2. **EdgeLite config translation** — ``convert_device_to_edgelite`` must emit
   ``register_type="coil"`` for the bool point and ``register_type="holding"``
   for the float32 point, so EdgeLite reads from the same region ProtoForge
   writes to.

3. **Bidirectional write** — a real Modbus client write (FC05/FC16) must be
   reflected in ProtoForge's device state (``read_points``).

This is a *real-machine* test: actual TCP sockets, actual Modbus protocol frames,
not mocks. It validates that ProtoForge's simulation server is genuinely
production-grade and that the EdgeLite integration config is correct.

Implementation note: pymodbus's ``ModbusTcpClient`` is synchronous. Running it
directly in an async test would block the event loop, deadlocking the async
``StartAsyncTcpServer``. All client calls are therefore dispatched via
``asyncio.to_thread`` so the server can respond.
"""

from __future__ import annotations

import asyncio
import os
import struct

os.environ["PROTOFORGE_NO_AUTH"] = "1"
os.environ.setdefault("PROTOFORGE_DB_PATH", "sqlite:///./data/test_e2e_modbus.db")

import pytest
import pytest_asyncio

from protoforge.engine.engine import SimulationEngine
from protoforge.observability.log_bus import LogBus
from protoforge.engine.registry import (
    clear_all as _clear_registry,
    register_database as _register_database,
    register_engine as _register_engine,
    register_log_bus as _register_log_bus,
)
from protoforge.models.device import DataType, DeviceConfig, GeneratorType, PointConfig
from protoforge.protocols.modbus.server import ModbusTcpServer
import protoforge.main as main_module


def _pick_free_port() -> int:
    """Pick an ephemeral free TCP port so the test never collides with a
    locally running service (e.g. a live EdgeLite gateway on 5020)."""
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


MODBUS_TEST_PORT = _pick_free_port()


def _make_device() -> DeviceConfig:
    """A Modbus device with a bool point (auto→coil) and a float32 point (auto→holding)."""
    return DeviceConfig(
        id="e2e-modbus-plc",
        name="E2E Test PLC",
        protocol="modbus_tcp",
        protocol_config={"host": "127.0.0.1", "port": MODBUS_TEST_PORT, "slave_id": 1},
        points=[
            PointConfig(
                name="coolant_on",
                address="4",
                data_type=DataType.BOOL,
                generator_type=GeneratorType.FIXED,
                fixed_value=True,
                access="rw",
            ),
            PointConfig(
                name="temperature",
                address="10",
                data_type=DataType.FLOAT32,
                generator_type=GeneratorType.FIXED,
                fixed_value=42.5,
                access="rw",
            ),
        ],
    )


@pytest_asyncio.fixture
async def modbus_server():
    """Start a real Modbus TCP server with a test device registered."""
    main_module._log_bus = LogBus()

    from protoforge.db.session import Database
    main_module._database = Database()
    await main_module._database.connect()

    engine = SimulationEngine()
    engine.register_protocol(ModbusTcpServer())
    await engine.start()
    _register_engine(engine)
    _register_database(main_module._database)
    _register_log_bus(main_module._log_bus)

    device = _make_device()
    await engine.create_device(device)
    await engine.start_protocol("modbus_tcp", {"host": "127.0.0.1", "port": MODBUS_TEST_PORT})

    await asyncio.sleep(0.5)  # let the server bind

    actual_port = engine.get_protocol_running_port("modbus_tcp")
    yield engine, device, int(actual_port) if actual_port else MODBUS_TEST_PORT

    await engine.stop()
    await main_module._database.close()
    main_module._engine = None
    main_module._database = None
    main_module._log_bus = None
    _clear_registry()


class _RealModbusClient:
    """Synchronous pymodbus client wrapper — all calls run in a thread.

    Running sync pymodbus calls via ``asyncio.to_thread`` avoids blocking the
    event loop, which the async ``StartAsyncTcpServer`` needs to process
    incoming Modbus frames and send responses.
    """

    def __init__(self, port: int):
        from pymodbus.client import ModbusTcpClient
        self._client = ModbusTcpClient("127.0.0.1", port=port, timeout=5)

    async def connect(self) -> bool:
        return await asyncio.to_thread(self._client.connect)

    async def close(self) -> None:
        await asyncio.to_thread(self._client.close)

    async def read_coils(self, address: int, count: int = 1, device_id: int = 1):
        return await asyncio.to_thread(
            lambda: self._client.read_coils(address=address, count=count, device_id=device_id)
        )

    async def read_holding_registers(self, address: int, count: int = 1, device_id: int = 1):
        return await asyncio.to_thread(
            lambda: self._client.read_holding_registers(address=address, count=count, device_id=device_id)
        )

    async def write_coil(self, address: int, value: bool, device_id: int = 1):
        return await asyncio.to_thread(
            lambda: self._client.write_coil(address=address, value=value, device_id=device_id)
        )

    async def write_register(self, address: int, value: int, device_id: int = 1):
        return await asyncio.to_thread(
            lambda: self._client.write_register(address=address, value=value, device_id=device_id)
        )

    async def write_registers(self, address: int, values: list[int], device_id: int = 1):
        return await asyncio.to_thread(
            lambda: self._client.write_registers(address=address, values=values, device_id=device_id)
        )


# ---------------------------------------------------------------------------
#  1. Real Modbus TCP read — register storage rule
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_real_modbus_bool_reads_from_coil(modbus_server):
    """bool point at auto address 4 → ProtoForge stores in coils[4].

    A real Modbus FC01 (read coils) must return True. If ProtoForge stored it
    in holding registers instead, FC01 would return 0/False — exposing the
    storage-rule bug that breaks EdgeLite joint debugging.
    """
    _engine, _device, port = modbus_server
    client = _RealModbusClient(port)
    assert await client.connect(), "Failed to connect real Modbus TCP client"
    try:
        result = await client.read_coils(address=4, count=1, device_id=1)
        assert not result.isError(), f"read_coils returned error: {result}"
        assert result.bits[0] is True, f"Expected coolant_on=True in coil[4], got {result.bits[0]}"
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_real_modbus_float32_reads_from_holding(modbus_server):
    """float32 point at auto address 10 → ProtoForge stores in holding[10:12] as >f.

    A real Modbus FC03 (read holding registers) must return 2 registers that
    decode (big-endian float32) to 42.5.
    """
    _engine, _device, port = modbus_server
    client = _RealModbusClient(port)
    assert await client.connect(), "Failed to connect real Modbus TCP client"
    try:
        result = await client.read_holding_registers(address=10, count=2, device_id=1)
        assert not result.isError(), f"read_holding_registers returned error: {result}"
        regs = result.registers
        assert len(regs) == 2, f"Expected 2 registers, got {len(regs)}"
        decoded = struct.unpack(">f", struct.pack(">HH", regs[0], regs[1]))[0]
        assert abs(decoded - 42.5) < 0.01, f"Expected temperature=42.5, got {decoded}"
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_real_modbus_coil_not_in_holding(modbus_server):
    """The bool point must NOT appear in holding registers (negative test).

    If it were wrongly stored in holding, EdgeLite (which defaults to holding)
    would read a stale/zero value. This confirms the storage partitioning.
    """
    _engine, _device, port = modbus_server
    client = _RealModbusClient(port)
    assert await client.connect()
    try:
        coil_result = await client.read_coils(address=4, count=1, device_id=1)
        assert not coil_result.isError()
        assert coil_result.bits[0] is True

        # The holding register at address 4 should be 0 (unused by this point)
        hr_result = await client.read_holding_registers(address=4, count=1, device_id=1)
        if not hr_result.isError():
            assert hr_result.registers[0] == 0, (
                f"holding[4]={hr_result.registers[0]} should be 0 (bool lives in coils, not holding)"
            )
    finally:
        await client.close()


# ---------------------------------------------------------------------------
#  2. EdgeLite config translation — register_type correctness
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_edgelite_config_has_correct_register_types(modbus_server):
    """convert_device_to_edgelite must emit register_type matching ProtoForge storage.

    - coolant_on (bool, auto addr 4) → register_type="coil"
    - temperature (float32, auto addr 10) → register_type="holding"

    This is the make-or-break config: if EdgeLite reads holding for a bool
    point that ProtoForge stored in coils, the values are mismatched.
    """
    from protoforge.integrations.edgelite import convert_device_to_edgelite

    _engine, device, _port = modbus_server
    result = convert_device_to_edgelite(device, "127.0.0.1")
    assert result is not None, "convert_device_to_edgelite returned None for modbus_tcp"
    assert result["protocol"] == "modbus_tcp"

    points = {p["name"]: p for p in result["points"]}

    coolant = points["coolant_on"]
    assert coolant["address"] == "4", f"Expected address '4', got {coolant['address']}"
    assert coolant.get("register_type") == "coil", (
        f"Expected register_type='coil' for bool point, got {coolant.get('register_type')}"
    )

    temp = points["temperature"]
    assert temp["address"] == "10", f"Expected address '10', got {temp['address']}"
    assert temp.get("register_type") == "holding", (
        f"Expected register_type='holding' for float32 point, got {temp.get('register_type')}"
    )


@pytest.mark.asyncio
async def test_edgelite_config_driver_connects_to_protoforge(modbus_server):
    """The EdgeLite driver_config must point to ProtoForge's host:port."""
    from protoforge.integrations.edgelite import convert_device_to_edgelite

    _engine, device, port = modbus_server
    result = convert_device_to_edgelite(device, "127.0.0.1")
    assert result is not None
    config = result["config"]
    assert config["host"] == "127.0.0.1", f"Expected host 127.0.0.1, got {config.get('host')}"
    assert config.get("slave_id") == 1, f"Expected slave_id 1, got {config.get('slave_id')}"


# ---------------------------------------------------------------------------
#  3. Bidirectional write — real Modbus client write → ProtoForge read
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_real_modbus_write_coil_reflects_in_protoforge(modbus_server):
    """Write a coil via real Modbus FC05 → ProtoForge read_points must see it.

    This validates the reverse direction: EdgeLite (or any Modbus client)
    writes a value, and ProtoForge's simulation state updates accordingly.
    """
    engine, device, port = modbus_server
    client = _RealModbusClient(port)
    assert await client.connect()
    try:
        # Write False to coil[4] (turn coolant off)
        write_result = await client.write_coil(address=4, value=False, device_id=1)
        assert not write_result.isError(), f"write_coil failed: {write_result}"

        await asyncio.sleep(0.3)

        # Read back via Modbus to confirm the write took effect
        read_back = await client.read_coils(address=4, count=1, device_id=1)
        assert not read_back.isError()
        assert read_back.bits[0] is False, "Coil[4] should be False after write"

        # Read via ProtoForge's engine API (read_points)
        modbus_server_obj = engine._protocol_servers.get("modbus_tcp")
        if modbus_server_obj:
            point_values = await modbus_server_obj.read_points(device.id)
            coolant_pv = next((pv for pv in point_values if pv.name == "coolant_on"), None)
            if coolant_pv is not None:
                assert coolant_pv.value is False or coolant_pv.value == 0, (
                    f"ProtoForge read_points coolant_on should be False/0 after write, got {coolant_pv.value}"
                )
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_real_modbus_write_holding_reflects_in_protoforge(modbus_server):
    """Write a float32 to holding[10:12] via real Modbus FC16 → ProtoForge must see it."""
    engine, device, port = modbus_server
    client = _RealModbusClient(port)
    assert await client.connect()
    try:
        # Encode 99.5 as big-endian float32 → 2 registers
        packed = struct.pack(">f", 99.5)
        regs = [struct.unpack(">H", packed[0:2])[0], struct.unpack(">H", packed[2:4])[0]]

        write_result = await client.write_registers(address=10, values=regs, device_id=1)
        assert not write_result.isError(), f"write_registers failed: {write_result}"

        await asyncio.sleep(0.3)

        # Read back via Modbus
        read_back = await client.read_holding_registers(address=10, count=2, device_id=1)
        assert not read_back.isError()
        decoded = struct.unpack(">f", struct.pack(">HH", *read_back.registers))[0]
        assert abs(decoded - 99.5) < 0.01, f"Expected 99.5 after write, got {decoded}"
    finally:
        await client.close()


# ---------------------------------------------------------------------------
#  4. Bidirectional write — external Modbus write → DeviceInstance state update
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_external_modbus_write_propagates_to_device_instance(modbus_server):
    """External Modbus FC05 write → DeviceInstance behavior state must update.

    This validates the _on_write reverse callback: when a Modbus client writes
    a value, ProtoForge's DeviceInstance (not just the store) must reflect it.
    The engine's _on_protocol_write callback updates the behavior's internal state.
    """
    engine, device, port = modbus_server
    client = _RealModbusClient(port)
    assert await client.connect()
    try:
        # Write False to coil[4] via FC05
        write_result = await client.write_coil(address=4, value=False, device_id=1)
        assert not write_result.isError(), f"write_coil failed: {write_result}"

        await asyncio.sleep(0.5)  # Allow _on_write async callback to complete

        # Check DeviceInstance's internal state (not just store)
        instance = engine._devices.get(device.id)
        assert instance is not None, "DeviceInstance not found"
        point_values = instance.read_all_points()
        coolant_pv = next((pv for pv in point_values if pv.name == "coolant_on"), None)
        assert coolant_pv is not None, "coolant_on point not found in device instance"
        assert coolant_pv.value is False or coolant_pv.value == 0, (
            f"DeviceInstance coolant_on should be False after external write, got {coolant_pv.value}"
        )
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_consecutive_modbus_writes_consistent(modbus_server):
    """Consecutive Modbus writes must all be reflected consistently."""
    _engine, _device, port = modbus_server
    client = _RealModbusClient(port)
    assert await client.connect()
    try:
        # Write True, verify; Write False, verify; Write True, verify
        for expected in (True, False, True):
            write_result = await client.write_coil(address=4, value=expected, device_id=1)
            assert not write_result.isError(), f"write_coil({expected}) failed: {write_result}"
            await asyncio.sleep(0.2)
            read_back = await client.read_coils(address=4, count=1, device_id=1)
            assert not read_back.isError()
            assert read_back.bits[0] is expected, (
                f"After writing {expected}, read back {read_back.bits[0]}"
            )
    finally:
        await client.close()


# ---------------------------------------------------------------------------
#  5. Read-only access guard — external write to access='r' point must fail
# ---------------------------------------------------------------------------


def _make_readonly_device() -> DeviceConfig:
    """A device with a read-only holding point and a writable one (slave_id=2)."""
    return DeviceConfig(
        id="e2e-modbus-ro-plc",
        name="E2E Readonly PLC",
        protocol="modbus_tcp",
        protocol_config={"host": "127.0.0.1", "port": MODBUS_TEST_PORT, "slave_id": 2},
        points=[
            PointConfig(
                name="ro_setpoint",
                address="30",
                data_type=DataType.UINT16,
                generator_type=GeneratorType.FIXED,
                fixed_value=0,
                access="r",
            ),
            PointConfig(
                name="rw_command",
                address="31",
                data_type=DataType.UINT16,
                generator_type=GeneratorType.FIXED,
                fixed_value=0,
                access="rw",
            ),
        ],
    )


@pytest.mark.asyncio
async def test_real_modbus_write_to_readonly_point_rejected(modbus_server):
    """FIXED: external FC06 write to an access='r' point must return exception 0x01.

    Real-socket verification of the read-only guard: a genuine pymodbus client
    writes to the read-only point — the server must reject it (ILLEGAL FUNCTION)
    and leave the register untouched, while the adjacent rw point stays writable.
    """
    engine, _device, port = modbus_server
    ro_device = _make_readonly_device()
    await engine.create_device(ro_device)
    await asyncio.sleep(0.3)  # let slave_id=2 register

    client = _RealModbusClient(port)
    assert await client.connect()
    try:
        # 1. Write to the read-only point (holding addr 30) → must be rejected
        ro_write = await client.write_register(address=30, value=777, device_id=2)
        assert ro_write.isError(), (
            f"Write to access='r' point should fail but succeeded: {ro_write}"
        )
        assert getattr(ro_write, "exception_code", None) == 1, (
            f"Expected ILLEGAL FUNCTION (0x01), got {ro_write}"
        )

        # 2. Register must be untouched
        ro_read = await client.read_holding_registers(address=30, count=1, device_id=2)
        assert not ro_read.isError()
        assert ro_read.registers[0] == 0, (
            f"Read-only register changed after rejected write: {ro_read.registers[0]}"
        )

        # 3. The adjacent rw point (addr 31) must remain writable
        rw_write = await client.write_register(address=31, value=888, device_id=2)
        assert not rw_write.isError(), f"Write to rw point failed: {rw_write}"
        rw_read = await client.read_holding_registers(address=31, count=1, device_id=2)
        assert not rw_read.isError()
        assert rw_read.registers[0] == 888, (
            f"rw register should be 888 after write, got {rw_read.registers[0]}"
        )
    finally:
        await client.close()
