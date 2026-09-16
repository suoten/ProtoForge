"""真机三连验证：EdgeLite 真联调 + 回放数据真机贯通 + 协同链式真机贯通。

本文件是"真机验证"的核心交付——不复用 mock EdgeLite，而是：

1. **启动真实 EdgeLite 子进程**（`python main.py`，临时 SQLite，已知 admin 密码，随机端口）
2. **启动真实 ProtoForge 引擎 + 真实 ModbusTcpServer**（监听真实 TCP 端口）
3. 用真实 ``IntegrationManager.push_device`` 把设备推到真 EdgeLite
4. 验证 EdgeLite 的 modbus_tcp 驱动**真正通过 TCP 连接 ProtoForge 的 Modbus 服务器**采集到
   实时仿真数据（值 = ProtoForge 当前值，且随仿真变化而变化，非硬编码）
5. 用**真实 pymodbus 客户端**读 Modbus server，验证 TimeSeriesReplay 回放帧真的流到协议层
6. 用**真实 pymodbus 客户端**读被联动设备，验证 COLLABORATION 规则链式写真的对外可观测

只有这三步全绿，"真正的仿真 / EdgeLite 联调真正可用 / 工业级生产级"才站得住脚。

运行：
    python -m pytest tests/test_real_machine_joint.py -v -s -o "addopts="
"""

from __future__ import annotations

import asyncio
import os
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import time

os.environ["PROTOFORGE_NO_AUTH"] = "1"
os.environ.setdefault("PROTOFORGE_DB_PATH", "sqlite:///./data/test_real_machine_joint.db")

import httpx
import pytest
import pytest_asyncio

from protoforge.engine.engine import SimulationEngine
from protoforge.engine.event_bus import EventBus
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

# 真实 EdgeLite 项目根目录（本机已存在）
EDGELITE_DIR = r"E:\硕腾网络\PyGBSentry\EdgeLite\EdgeLite-v1.0-Community"
EDGELITE_ADMIN_PW = "RealTest123!"

# ProtoForge Modbus 服务器监听端口（避开默认 5020，防止与运行中实例冲突）
PF_MODBUS_PORT = 15021      # EdgeLite 联调 + 回放测试
PF_MODBUS_PORT_C = 15023    # 协同测试（单服务器双设备）


# ---------------------------------------------------------------------------
#  通用辅助
# ---------------------------------------------------------------------------


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def _wait_http_ok(url: str, timeout: float = 45.0) -> bool:
    """轮询直到目标 HTTP 服务响应任意非 5xx（含 401/404 均视为已就绪）。"""
    deadline = time.time() + timeout
    async with httpx.AsyncClient(timeout=3.0) as c:
        while time.time() < deadline:
            try:
                r = await c.get(url)
                if r.status_code < 500:
                    return True
            except Exception as e:
                print(f"[WARN] Health check failed: {e}")
            await asyncio.sleep(1.0)
    return False


async def _el_login(base: str, password: str = EDGELITE_ADMIN_PW) -> str:
    async with httpx.AsyncClient(timeout=10.0) as c:
        r = await c.post(
            f"{base}/api/v1/auth/login",
            json={"username": "admin", "password": password},
        )
        assert r.status_code == 200, f"EdgeLite login failed {r.status_code}: {r.text[:300]}"
        data = r.json().get("data", {}) or {}
        token = data.get("access_token", "")
        assert token, f"EdgeLite login returned no token: {r.text[:300]}"
        return token


async def _el_get(base: str, token: str, path: str) -> tuple[int, dict]:
    async with httpx.AsyncClient(timeout=10.0) as c:
        r = await c.get(f"{base}{path}", headers={"Authorization": f"Bearer {token}"})
        try:
            body = r.json()
        except Exception as e:
            print(f"[WARN] Response JSON parse failed: {e}")
            body = {"_raw": r.text[:500]}
        return r.status_code, body


def _extract_point_value(points_data, name: str):
    """从 EdgeLite /devices/{id}/points 响应里取出指定点名的 value。

    EdgeLite 可能返回 list[{name/point_name, value, ...}] 或 dict{name: value}。
    """
    if isinstance(points_data, list):
        for item in points_data:
            if not isinstance(item, dict):
                continue
            key = item.get("name") or item.get("point_name") or item.get("id", "")
            if key == name:
                return item.get("value")
    elif isinstance(points_data, dict):
        if name in points_data:
            v = points_data[name]
            if isinstance(v, dict):
                return v.get("value")
            return v
        for k, v in points_data.items():
            if isinstance(v, dict) and (v.get("name") == name or v.get("point_name") == name):
                return v.get("value")
    return None


class _RealModbusClient:
    """同步 pymodbus 客户端封装，所有调用经 asyncio.to_thread 避免阻塞事件循环。"""

    def __init__(self, port: int, host: str = "127.0.0.1"):
        from pymodbus.client import ModbusTcpClient
        self._client = ModbusTcpClient(host, port=port, timeout=5)

    async def connect(self) -> bool:
        return await asyncio.to_thread(self._client.connect)

    async def close(self) -> None:
        await asyncio.to_thread(self._client.close)

    async def read_holding_registers(self, address: int, count: int = 1, device_id: int = 1):
        return await asyncio.to_thread(
            lambda: self._client.read_holding_registers(address=address, count=count, device_id=device_id)
        )

    async def read_coils(self, address: int, count: int = 1, device_id: int = 1):
        return await asyncio.to_thread(
            lambda: self._client.read_coils(address=address, count=count, device_id=device_id)
        )

    async def write_coil(self, address: int, value: bool, device_id: int = 1):
        return await asyncio.to_thread(
            lambda: self._client.write_coil(address=address, value=value, device_id=device_id)
        )


async def _read_float32(client: _RealModbusClient, address: int) -> float:
    r = await client.read_holding_registers(address=address, count=2, device_id=1)
    assert not r.isError(), f"read_holding_registers error: {r}"
    regs = r.registers
    return struct.unpack(">f", struct.pack(">HH", regs[0], regs[1]))[0]


# ---------------------------------------------------------------------------
#  真实 EdgeLite 子进程 fixture
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def real_edgelite():
    """启动真实 EdgeLite 子进程（临时 DB + 已知 admin 密码 + 随机端口）。

    yields (base_url, admin_password)。结束后终止子进程并清理临时目录。
    """
    if not os.path.isdir(EDGELITE_DIR):
        pytest.skip(f"EdgeLite not found at {EDGELITE_DIR}")

    port = _free_port()
    tmpdir = tempfile.mkdtemp(prefix="edgelite_real_")
    db_path = os.path.join(tmpdir, "edgelite.db")
    log_path = os.path.join(tmpdir, "edgelite.log")

    env = {
        **os.environ,
        "EDGELITE_ADMIN_PASSWORD": EDGELITE_ADMIN_PW,
        "EDGELITE_RESET_ADMIN_PASSWORD": "true",
        "EDGELITE_DATABASE__SQLITE_PATH": db_path,
        # 抑制 influxdb 健康检查延迟（未部署 influx 时避免连接等待）
        "EDGELITE_INFLUXDB__URL": "",
        # SecretManager 主密钥（测试环境固定值，生产环境必须使用随机密钥）
        "EDGELITE_MASTER_KEY": "test-master-key-for-real-machine-verification-only",
    }

    log_file = open(log_path, "w", encoding="utf-8", errors="replace")
    proc = subprocess.Popen(
        [sys.executable, "main.py", "--host", "127.0.0.1", "--port", str(port)],
        cwd=EDGELITE_DIR,
        env=env,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        text=True,
    )

    base = f"http://127.0.0.1:{port}"
    try:
        ready = await _wait_http_ok(f"{base}/health/live", timeout=120.0)
        if not ready:
            log_file.flush()
            with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                tail = f.read()[-6000:]
            pytest.fail(f"EdgeLite did not become ready within 120s. Log tail:\n{tail}")
        yield base, EDGELITE_ADMIN_PW, log_path
    except Exception as e:
        # 测试失败时保留 EdgeLite 日志副本到项目根目录供诊断
        print(f"[WARN] EdgeLite fixture failed: {e}; preserving logs")
        try:
            shutil.copy(log_path, "edgelite_test_failure.log")
            print(f"\n[EDGELOG] EdgeLite log preserved to edgelite_test_failure.log (source: {log_path})")
            with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                print(f"[EDGELOG-TAIL] {f.read()[-6000:]}")
        except Exception as e:
            print(f"测试清理失败: {e}")
            pass
        raise
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception as e:
            print(f"[WARN] proc.wait did not complete, killing: {e}")
            proc.kill()
        log_file.close()
        shutil.rmtree(tmpdir, ignore_errors=True)


# ---------------------------------------------------------------------------
#  ProtoForge 引擎 fixture（真实 Modbus 服务器）
# ---------------------------------------------------------------------------


async def _start_pf_engine_with_modbus(port: int, device: DeviceConfig):
    """启动 ProtoForge 引擎 + ModbusTcpServer，注册并启动设备。返回 (engine, device)。

    关键顺序：先 ``start_protocol``（让协议进入 RUNNING），再 ``create_device``。
    这样 ``create_device`` 内部检测到协议已运行，会自动调用 ``instance.start()``
    并向协议服务器注册点位。否则设备会停留在 STOP，永远无法进入 ONLINE。
    """
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

    # 先启动协议 → 再创建设备（确保 create_device 时协议已 RUNNING）
    await engine.start_protocol("modbus_tcp", {"host": "127.0.0.1", "port": port})
    await asyncio.sleep(0.5)  # 让服务器绑定
    await engine.create_device(device)

    # 显式 bring online：start() 推动 STOP→STARTING，tick() 推动 STARTING→RUN(ONLINE)
    # min_startup_time=0 时 tick 立即完成转换，不依赖引擎 1s 间隔的 _tick_loop
    instance = engine.get_device_instance(device.id)
    if instance is not None:
        instance.start()
        await instance.tick()
    await asyncio.sleep(0.2)
    return engine, device


async def _stop_pf_engine(engine):
    await engine.stop()
    await main_module._database.close()
    main_module._engine = None
    main_module._database = None
    main_module._log_bus = None
    _clear_registry()


def _make_modbus_device(
    device_id: str,
    port: int,
    edgelite_url: str = "",
    edgelite_pw: str = "",
    fixed_temp: float = 42.5,
) -> DeviceConfig:
    cfg: dict = {"host": "127.0.0.1", "port": port, "slave_id": 1, "unit_id": 1, "min_startup_time": 0}
    if edgelite_url:
        cfg["edgelite_url"] = edgelite_url
        cfg["edgelite_username"] = "admin"
        cfg["edgelite_password"] = edgelite_pw
    return DeviceConfig(
        id=device_id,
        name=f"Real-Machine {device_id}",
        protocol="modbus_tcp",
        protocol_config=cfg,
        points=[
            PointConfig(
                name="temperature",
                address="10",
                data_type=DataType.FLOAT32,
                generator_type=GeneratorType.FIXED,
                fixed_value=fixed_temp,
                access="rw",
            ),
        ],
    )


# ===========================================================================
#  真机验证 1：EdgeLite 真联调
# ===========================================================================


@pytest.mark.asyncio
async def test_1_edgelite_real_collects_protoforge_data(real_edgelite):
    """真 EdgeLite 通过 modbus_tcp 驱动真实采集 ProtoForge 仿真数据。

    断言要点（任一失败即说明联调不可用）：
    - push_device 经真实 convert_device_to_edgelite → 真 EdgeLite 接受并启动驱动采集
    - EdgeLite /points 返回的 temperature 值 = ProtoForge 当前仿真值 42.5
      （mock 测试返回硬编码 25.8，真机必须返回 42.5 才算真采集）
    - 改 ProtoForge 仿真值后，EdgeLite 下一次采集能看到新值（证明实时采集非缓存）
    """
    base, el_pw, el_log = real_edgelite

    device = _make_modbus_device(
        "real-edgelite-modbus", PF_MODBUS_PORT, edgelite_url=base, edgelite_pw=el_pw
    )
    engine, device = await _start_pf_engine_with_modbus(PF_MODBUS_PORT, device)
    try:
        from protoforge.integrations.integration.manager import IntegrationManager
        from protoforge.integrations.edgelite import convert_device_to_edgelite, get_edgelite_config_from_device

        # 先登录获取 token（IntegrationManager.start() 会自动改密码，原密码将失效）
        token = await _el_login(base, el_pw)

        # 调试：打印 convert_device_to_edgelite 产生的 payload
        el_cfg = get_edgelite_config_from_device(device)
        payload = convert_device_to_edgelite(device, el_config=el_cfg)
        print(f"\n[DEBUG] push payload: {payload}")
        print(f"[DEBUG] el_config: {el_cfg}")

        # 调试：用真实 pymodbus 客户端验证 ProtoForge Modbus 服务器可读
        dbg_client = _RealModbusClient(PF_MODBUS_PORT)
        dbg_ok = await dbg_client.connect()
        print(f"[DEBUG] direct modbus connect: {dbg_ok}")
        if dbg_ok:
            dbg_v = await _read_float32(dbg_client, 10)
            print(f"[DEBUG] direct modbus read holding[10]: {dbg_v}")
            await dbg_client.close()

        mgr = IntegrationManager(
            EventBus(), enabled=True, edgelite_url=base, username="admin", password=el_pw
        )
        await mgr.start()
        try:
            result = await mgr.push_device(device)
        finally:
            await mgr.stop()

        assert result.get("ok"), f"push_device failed: {result}"

        # collect_interval=5（默认），等待两轮采集确保有数据
        await asyncio.sleep(11)

        status, body = await _el_get(base, token, "/api/v1/devices/real-edgelite-modbus/points")
        # token 可能因密码修改而失效，失效则用新密码重新登录
        if status == 401:
            token = await _el_login(base, el_pw + "!1")
            status, body = await _el_get(base, token, "/api/v1/devices/real-edgelite-modbus/points")
        assert status == 200, f"points query failed {status}: {body}"
        points = body.get("data", body)
        temp = _extract_point_value(points, "temperature")
        assert temp is not None, f"temperature missing in EdgeLite points: {points}"
        assert abs(float(temp) - 42.5) < 0.5, (
            f"EdgeLite did NOT collect real data: expected 42.5, got {temp} "
            f"(if got 25.8 → still hitting mock; if None → point name mismatch)"
        )

        # 改 ProtoForge 仿真值，验证 EdgeLite 实时采集到新值（非缓存）
        await engine.write_device_point("real-edgelite-modbus", "temperature", 99.0)

        # 调试：直接读 Modbus 服务器，验证写入确实生效
        dbg2 = _RealModbusClient(PF_MODBUS_PORT)
        await dbg2.connect()
        dbg2_v = await _read_float32(dbg2, 10)
        print(f"\n[DEBUG] after write_device_point(99.0), direct modbus read holding[10]: {dbg2_v}")
        await dbg2.close()

        # 多轮查询 EdgeLite /points，观察值是否随采集更新
        for i in range(4):
            await asyncio.sleep(6)
            status, body = await _el_get(base, token, "/api/v1/devices/real-edgelite-modbus/points")
            if status == 401:
                token = await _el_login(base, el_pw + "!1")
                status, body = await _el_get(base, token, "/api/v1/devices/real-edgelite-modbus/points")
            temp_i = _extract_point_value(body.get("data", body), "temperature")
            print(f"[DEBUG] poll #{i+1} status={status} temp={temp_i} body={str(body)[:200]}")
            if temp_i is not None and abs(float(temp_i) - 99.0) < 0.5:
                break

        # 也尝试 debug read（绕过缓存，直接驱动读取）
        try:
            async with httpx.AsyncClient(timeout=30.0) as dc:
                dr = await dc.post(
                    f"{base}/api/v1/debug/read",
                    params={"protocol": "modbus_tcp", "device_id": "real-edgelite-modbus", "points": "temperature"},
                    headers={"Authorization": f"Bearer {token}"},
                )
                try:
                    dbg_body = dr.json()
                except Exception as e:
                    dbg_body = {"_raw": dr.text[:300], "_error": str(e)}
            print(f"[DEBUG] debug/read status={dr.status_code} body={str(dbg_body)[:300]}")
        except Exception as e:
            print(f"[DEBUG] debug/read error: {e}")

        # 打印 EdgeLite 日志尾部，查看采集循环状态
        try:
            with open(el_log, "r", encoding="utf-8", errors="replace") as f:
                log_tail = f.read()[-8000:]
            print(f"\n[EDGELOG-TAIL] {log_tail}")
        except Exception as e:
            print(f"[DEBUG] read edgelite log error: {e}")

        status, body = await _el_get(base, token, "/api/v1/devices/real-edgelite-modbus/points")
        if status == 401:
            token = await _el_login(base, el_pw + "!1")
            status, body = await _el_get(base, token, "/api/v1/devices/real-edgelite-modbus/points")
        temp = _extract_point_value(body.get("data", body), "temperature")
        assert temp is not None, f"temperature missing after update: {body}"
        assert abs(float(temp) - 99.0) < 0.5, (
            f"EdgeLite did NOT reflect live update: expected 99.0, got {temp} (stale cache?)"
        )
    finally:
        await _stop_pf_engine(engine)


# ===========================================================================
#  真机验证 2：回放数据真机贯通
# ===========================================================================


@pytest.mark.asyncio
async def test_2_replay_flows_to_real_modbus_client():
    """TimeSeriesReplay 回放帧经 on_write_point → Modbus 服务器 → 真客户端可读。

    场景：设备 temperature 初始 42.5，回放源为 [11.0, 22.0, 33.0]。
    每跑一帧 tick，用真 pymodbus 客户端读 holding[10]，值必须等于该帧回放值。
    这证明回放数据真的流到了协议响应层。
    """
    from protoforge.models.device import DeviceStatus
    from protoforge.models.scenario import Rule, RuleType, ScenarioConfig

    device = _make_modbus_device("replay-modbus", PF_MODBUS_PORT, fixed_temp=42.5)
    engine, device = await _start_pf_engine_with_modbus(PF_MODBUS_PORT, device)
    try:
        from protoforge.simulation.scenario import Scenario

        replay_source = [
            {"ts": 1, "device_id": "replay-modbus", "point": "temperature", "value": 11.0},
            {"ts": 2, "device_id": "replay-modbus", "point": "temperature", "value": 22.0},
            {"ts": 3, "device_id": "replay-modbus", "point": "temperature", "value": 33.0},
        ]
        sc_config = ScenarioConfig(
            id="replay-scenario",
            name="Replay Real Machine",
            devices=[],
            replay_config={
                "source": replay_source,
                "speed": 1.0,
                "loop": False,
                "time_field": "ts",
            },
            rules=[],
        )
        scenario = Scenario(sc_config, on_write_point=engine.write_device_point)
        instance = engine.get_device_instance("replay-modbus")
        assert instance is not None, "replay-modbus DeviceInstance not found in engine"
        scenario.add_device(instance)
        # 等待设备进入 ONLINE（min_startup_time=0，引擎 tick 一次即 RUN）
        for _ in range(30):
            await asyncio.sleep(0.1)
            if instance.status == DeviceStatus.ONLINE:
                break
        assert instance.status == DeviceStatus.ONLINE, "device did not reach ONLINE"
        scenario.start()
        try:
            client = _RealModbusClient(PF_MODBUS_PORT)
            assert await client.connect(), "real modbus client connect failed"
            try:
                # 基线：回放前设备固定值 42.5
                v0 = await _read_float32(client, 10)
                assert abs(v0 - 42.5) < 0.1, f"baseline should be 42.5, got {v0}"

                expected = [11.0, 22.0, 33.0]
                for i, want in enumerate(expected):
                    await scenario.tick()  # 推进一帧回放
                    await asyncio.sleep(0.15)  # 让协议服务器刷新
                    got = await _read_float32(client, 10)
                    assert abs(got - want) < 0.1, (
                        f"replay frame {i}: expected {want}, real client read {got} "
                        f"(replay data did NOT flow to protocol layer)"
                    )
            finally:
                await client.close()
        finally:
            scenario.stop()
    finally:
        await _stop_pf_engine(engine)


# ===========================================================================
#  真机验证 3：协同链式真机贯通
# ===========================================================================


@pytest.mark.asyncio
async def test_3_collaboration_flows_to_real_modbus_client():
    """COLLABORATION 规则链式写经 on_write_point → Modbus 服务器 → 真客户端可观测。

    场景：deviceA.trigger (coil[4]) 置 True 时，协同规则 set deviceB.temperature=77.7。
    触发后用真 pymodbus 客户端读 deviceB holding[10]，必须读到 77.7。
    这证明协同动作真的传播到了对外协议响应。
    """
    from protoforge.models.device import DeviceStatus
    from protoforge.models.scenario import Rule, RuleType, ScenarioConfig

    # 单服务器双设备：coil[4]=trigger，holding[10]=target，地址不冲突
    device_a = DeviceConfig(
        id="collab-source",
        name="Collab Source",
        protocol="modbus_tcp",
        protocol_config={"host": "127.0.0.1", "port": PF_MODBUS_PORT_C, "slave_id": 1, "unit_id": 1, "min_startup_time": 0},
        points=[
            PointConfig(
                name="trigger",
                address="4",
                data_type=DataType.BOOL,
                generator_type=GeneratorType.FIXED,
                fixed_value=False,
                access="rw",
            ),
        ],
    )
    device_b = _make_modbus_device("collab-target", PF_MODBUS_PORT_C, fixed_temp=12.0)

    # 启动单个 Modbus 服务器，注册两台设备（共享 slave_id=1，寄存器区不重叠）
    # 关键顺序：先 start_protocol → 再 create_device（确保 create_device 时协议已 RUNNING）
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
    await engine.start_protocol("modbus_tcp", {"host": "127.0.0.1", "port": PF_MODBUS_PORT_C})
    await asyncio.sleep(0.5)
    await engine.create_device(device_a)
    await engine.create_device(device_b)
    # 显式 bring online：min_startup_time=0 时 tick 立即 STARTING→RUN
    for _did in ("collab-source", "collab-target"):
        _inst = engine.get_device_instance(_did)
        if _inst is not None:
            _inst.start()
            await _inst.tick()
    await asyncio.sleep(0.2)
    try:
        from protoforge.simulation.scenario import Scenario

        rule = Rule(
            id="collab-rule",
            name="trigger sets target",
            rule_type=RuleType.COLLABORATION,
            source_device_id="collab-source",
            source_point="trigger",
            condition={"operator": "==", "value": True},
            actions=[
                {"target_device_id": "collab-target", "target_point": "temperature",
                 "action_type": "set", "value": 77.7}
            ],
            cooldown=0.0,
            enabled=True,
        )
        sc_config = ScenarioConfig(
            id="collab-scenario",
            name="Collab Real Machine",
            devices=[],
            rules=[rule],
        )
        scenario = Scenario(sc_config, on_write_point=engine.write_device_point)
        inst_a = engine.get_device_instance("collab-source")
        inst_b = engine.get_device_instance("collab-target")
        assert inst_a is not None and inst_b is not None, "device instances not found in engine"
        scenario.add_device(inst_a)
        scenario.add_device(inst_b)
        for _ in range(30):
            await asyncio.sleep(0.1)
            if inst_a.status == DeviceStatus.ONLINE and inst_b.status == DeviceStatus.ONLINE:
                break
        assert inst_a.status == DeviceStatus.ONLINE and inst_b.status == DeviceStatus.ONLINE, "devices did not reach ONLINE"
        scenario.start()
        try:
            client_b = _RealModbusClient(PF_MODBUS_PORT_C)
            assert await client_b.connect(), "connect to deviceB failed"
            try:
                # 基线：deviceB.temperature = 12.0
                v0 = await _read_float32(client_b, 10)
                assert abs(v0 - 12.0) < 0.1, f"baseline should be 12.0, got {v0}"

                # 触发协同：置 deviceA.trigger = True
                await engine.write_device_point("collab-source", "trigger", True)
                await scenario.tick()  # 评估规则 + 协同链触发
                await asyncio.sleep(0.2)

                got = await _read_float32(client_b, 10)
                assert abs(got - 77.7) < 0.1, (
                    f"collaboration did NOT propagate: expected 77.7, real client read {got} "
                    f"(chain write did not reach protocol layer)"
                )
            finally:
                await client_b.close()
        finally:
            scenario.stop()
    finally:
        await engine.stop()
        await main_module._database.close()
        main_module._engine = None
        main_module._database = None
        main_module._log_bus = None
        _clear_registry()
