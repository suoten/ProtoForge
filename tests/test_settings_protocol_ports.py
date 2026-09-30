"""v1.4.1 系统设置"协议端口"保存回归测试。

用户反馈：系统设置 → 协议端口 tab，修改端口保存后不生效。
根因：前端 PUT /settings 以 protocol_ports 字典提交（GET 也按字典返回），
config.update_settings 只接受 {proto}_port 形式的键 → 字典被静默丢弃，
界面提示保存成功但实际未入库。

修复：update_settings 将 protocol_ports 字典展开为逐协议 {proto}_port 键，
走统一校验/冲突检查/持久化。同时补齐 mewtocol 端口设置项（v1.4.0 新增协议
遗漏，此前未配置高级配置启动会回退到 8000 与 Web 端口冲突）。

注意：update_settings 操作全局单例并写 _ENV_FILE，测试用 monkeypatch
隔离（临时 env 文件 + 结束后恢复原值）。
"""

import pytest

import protoforge.config as config_mod
from protoforge.config import get_protocol_port_map, get_settings, update_settings
from protoforge.engine.defaults import get_protocol_defaults


@pytest.fixture()
def isolated_settings(tmp_path, monkeypatch):
    """隔离全局设置：临时 env 文件 + 保存/恢复 overrides 与字段原值。"""
    monkeypatch.setattr(config_mod, "_ENV_FILE", tmp_path / "settings.env")
    saved_overrides = dict(config_mod._settings_overrides)
    s = get_settings()
    saved_fields = {k: getattr(s, k) for k in list(saved_overrides) + ["modbus_tcp_port", "s7_port", "mewtocol_port"]}
    yield s
    config_mod._settings_overrides.clear()
    config_mod._settings_overrides.update(saved_overrides)
    for k, v in saved_fields.items():
        setattr(s, k, v)


def test_protocol_ports_dict_persists(isolated_settings):
    """协议端口字典提交 → 逐协议入库（回归用户反馈场景）。"""
    changed = update_settings({"protocol_ports": {"modbus_tcp": 15020, "s7": 11102}})
    assert changed["modbus_tcp_port"]["new"] == 15020
    assert changed["s7_port"]["new"] == 11102
    s = get_settings()
    assert s.modbus_tcp_port == 15020
    assert s.s7_port == 11102


def test_protocol_ports_take_effect_on_next_start(isolated_settings):
    """保存后 get_protocol_defaults 读到新端口（协议服务下次启动即用新端口）。"""
    update_settings({"protocol_ports": {"custom_tcp": 38222}})
    assert get_protocol_defaults("custom_tcp")["port"] == 38222
    assert get_protocol_port_map()["custom_tcp"]["port"] == 38222


def test_protocol_ports_conflict_rejected(isolated_settings):
    """端口冲突（与其他协议相同）→ ConfigValidationError，且不部分生效。"""
    from protoforge.config import ConfigValidationError

    with pytest.raises(ConfigValidationError):
        update_settings({"protocol_ports": {"modbus_tcp": 38000}})  # 38000 = custom_tcp 默认
    assert get_settings().modbus_tcp_port != 38000


def test_protocol_ports_invalid_value_rejected(isolated_settings):
    """非数字/越界端口 → ConfigValidationError。"""
    from protoforge.config import ConfigValidationError

    with pytest.raises(ConfigValidationError):
        update_settings({"protocol_ports": {"modbus_tcp": "abc"}})
    with pytest.raises(ConfigValidationError):
        update_settings({"protocol_ports": {"modbus_tcp": 99999}})


def test_protocol_ports_unknown_protocol_ignored(isolated_settings):
    """未知协议名不报错（如前端缓存了已下线的协议项），已知项仍生效。"""
    changed = update_settings({"protocol_ports": {"not_a_protocol": 12345, "opcua": 14840}})
    assert "not_a_protocol_port" not in changed
    assert get_settings().opcua_port == 14840


def test_mewtocol_port_settings_entry(isolated_settings):
    """mewtocol（v1.4.0 新增协议）在 Settings/defaults 中有端口条目，默认 2049。"""
    assert get_protocol_port_map()["mewtocol"]["port"] == 2049
    assert get_protocol_defaults("mewtocol")["port"] == 2049
    update_settings({"protocol_ports": {"mewtocol": 12049}})
    assert get_protocol_defaults("mewtocol")["port"] == 12049
