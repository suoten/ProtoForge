"""v1.6.0 Windows 服务管理（protoforge.win_service）测试。

命令构建是纯函数（跨平台可测）；执行层用假 runner 验证顺序与失败中止；
非 Windows 平台验证 CLI 入口的拒绝语义。
"""

import sys

import pytest

from protoforge import win_service
from protoforge.win_service import (
    ServicePlan,
    build_plan,
    execute,
    execute_uninstall,
    find_nssm,
    SERVICE_NAME,
)


# ---------------------------------------------------------------------------
# 计划与命令序列
# ---------------------------------------------------------------------------

def _plan(tmp_path, **kw) -> ServicePlan:
    return build_plan(
        nssm_exe=str(tmp_path / "tools" / "nssm.exe"),
        python_exe=str(tmp_path / "venv" / "Scripts" / "python.exe"),
        app_dir=str(tmp_path),
        log_dir=str(tmp_path / "logs"),
        **kw,
    )


def test_build_plan_defaults(tmp_path):
    plan = _plan(tmp_path)
    assert plan.service_name == SERVICE_NAME
    assert plan.port == 18080
    assert plan.python_exe.endswith("python.exe")
    assert plan.log_dir.endswith("logs")


def test_build_plan_custom_port_and_name(tmp_path):
    plan = _plan(tmp_path, port=19090, service_name="ProtoForge-Test")
    assert plan.port == 19090
    assert plan.service_name == "ProtoForge-Test"
    cmds = plan.commands()
    assert ["--port", "19090"] == cmds[0][-2:]


def test_service_plan_install_command_sequence(tmp_path):
    plan = _plan(tmp_path)
    cmds = [list(c) for c in plan.commands()]
    # install 是第一条，start 是最后一条
    assert cmds[0][1:3] == ["install", plan.service_name]
    assert cmds[-1][1:3] == ["start", plan.service_name]
    sets = [c for c in cmds if c[1:3] == ["set", plan.service_name]]
    keys = {c[3] for c in sets}
    # 崩溃拉起 + 自动启动 + 日志轮转语义齐备
    assert {"AppExit", "AppRestartDelay", "AppRotateFiles", "AppRotateBytes",
            "AppStdout", "AppStderr", "AppDirectory", "Start", "DisplayName"} <= keys
    assert any(c[3] == "Start" and c[4] == "SERVICE_AUTO_START" for c in sets)
    assert any(c[3] == "AppExit" and c[4] == "Default" and c[5] == "Restart" for c in sets)


def test_service_plan_uninstall_commands(tmp_path):
    plan = _plan(tmp_path)
    cmds = plan.uninstall_commands()
    assert cmds[0][1:3] == ["stop", plan.service_name]
    assert cmds[1][1:3] == ["remove", plan.service_name]
    assert cmds[1][-1] == "confirm"


# ---------------------------------------------------------------------------
# NSSM 定位
# ---------------------------------------------------------------------------

def test_find_nssm_from_tools_dir(tmp_path, monkeypatch):
    tools = tmp_path / "tools"
    tools.mkdir()
    (tools / "nssm.exe").write_bytes(b"fake")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(win_service.shutil, "which", lambda name: None)
    found = find_nssm()
    assert found is not None and found.endswith("nssm.exe")


def test_find_nssm_none_when_missing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(win_service.shutil, "which", lambda name: None)
    assert find_nssm(project_root=tmp_path / "nope") is None


def test_find_nssm_prefers_path(tmp_path, monkeypatch):
    monkeypatch.setattr(win_service.shutil, "which", lambda name: "C:\\bin\\nssm.exe")
    assert find_nssm(project_root=tmp_path) == "C:\\bin\\nssm.exe"


# ---------------------------------------------------------------------------
# 执行层
# ---------------------------------------------------------------------------

def test_execute_runs_all_commands(tmp_path):
    plan = _plan(tmp_path)
    ran = []
    code = execute(plan, runner=lambda cmd: ran.append(cmd) or 0)
    assert code == 0
    assert len(ran) == len(plan.commands())


def test_execute_aborts_on_failure(tmp_path):
    plan = _plan(tmp_path)
    ran = []

    def runner(cmd):
        ran.append(cmd)
        return 3 if "install" in cmd else 0  # 第一步即失败

    code = execute(plan, runner=runner)
    assert code == 3
    assert len(ran) == 1  # 失败后不继续


def test_execute_uninstall_tolerates_failures(tmp_path):
    plan = _plan(tmp_path)
    ran = []
    code = execute_uninstall(plan, runner=lambda cmd: ran.append(cmd) or 1)
    assert code == 0
    assert len(ran) == 2  # stop/remove 都尝试（服务可能不存在）


# ---------------------------------------------------------------------------
# CLI 入口语义
# ---------------------------------------------------------------------------

def test_cmd_install_service_rejects_non_windows(monkeypatch):
    if sys.platform == "win32":
        pytest.skip("非 Windows 语义测试")
    assert win_service.cmd_install_service(port=18080) == 1


def test_cmd_install_service_requires_admin(monkeypatch, tmp_path):
    if sys.platform != "win32":
        pytest.skip("Windows 专属")
    monkeypatch.setattr(win_service, "is_admin", lambda: False)
    assert win_service.cmd_install_service(port=18080) == 1


def test_cmd_install_service_missing_nssm(tmp_path, monkeypatch):
    if sys.platform != "win32":
        pytest.skip("Windows 专属")
    monkeypatch.setattr(win_service, "is_admin", lambda: True)
    monkeypatch.setattr(win_service, "find_nssm", lambda: None)
    assert win_service.cmd_install_service(port=18080) == 1


def test_cmd_install_service_happy_path(tmp_path, monkeypatch):
    if sys.platform != "win32":
        pytest.skip("Windows 专属")
    monkeypatch.setattr(win_service, "is_admin", lambda: True)
    monkeypatch.setattr(win_service, "find_nssm", lambda: "nssm.exe")

    executed = {}

    def fake_execute(plan, runner=None):
        executed["port"] = plan.port
        return 0

    monkeypatch.setattr(win_service, "execute", fake_execute)
    assert win_service.cmd_install_service(port=18080) == 0
    assert executed["port"] == 18080
