"""v1.5.0 配置链路一致性测试：系统设置 → API 白名单 → 配置层 → .env 持久化 → 协议启动生效。

背景（v1.4.2 事故的通用化防线）：前端 PUT /settings 以 protocol_ports 字典提交，
config.update_settings 只接受 {proto}_port 形式的键 → 整个字典被静默丢弃，
界面提示"已保存"而实际未入库。此类"保存什么就必须生效什么"的断言必须覆盖：

  1. 每个 PROTOCOL_DEFAULTS 中带 port 的协议，在 Settings 中必须有对应的
     {proto}_port 字段（mewtocol 类"新协议漏设置项"事故的系统性防线）；
  2. protocol_ports 字典提交 → 逐协议入库 → get_protocol_defaults 读到新端口；
  3. 更新结果持久化到 .env 文件（重启后仍生效）；
  4. 非法值显式拒绝（ConfigValidationError），绝不静默忽略；
  5. Settings 所有非保留字段的更新要么生效要么显式报错，不允许静默丢弃。

注意：update_settings 操作全局单例并写 _ENV_FILE，测试用 monkeypatch 隔离。
"""

import pytest

import protoforge.config as config_mod
from protoforge.config import get_protocol_port_map, get_settings, update_settings
from protoforge.engine.defaults import PROTOCOL_DEFAULTS


@pytest.fixture()
def isolated_settings(tmp_path, monkeypatch):
    """隔离全局设置：临时 env 文件 + 保存/恢复 overrides 与字段原值。"""
    monkeypatch.setattr(config_mod, "_ENV_FILE", tmp_path / "settings.env")
    saved_overrides = dict(config_mod._settings_overrides)
    s = get_settings()
    saved_fields = {k: getattr(s, k) for k in list(saved_overrides) + ["modbus_tcp_port", "s7_port", "mewtocol_port", "opcua_port", "log_level", "host"]}
    yield s
    config_mod._settings_overrides.clear()
    config_mod._settings_overrides.update(saved_overrides)
    for k, v in saved_fields.items():
        setattr(s, k, v)


# ---------------------------------------------------------------------------
# 1. 协议默认端口 ↔ Settings 字段 双向存在性（mewtocol 事故防线）
# ---------------------------------------------------------------------------

def test_every_protocol_default_port_has_settings_field(isolated_settings):
    """PROTOCOL_DEFAULTS 里每个带 port 的协议，Settings 必须有 {proto}_port 字段。"""
    s = get_settings()
    missing = []
    for proto, defaults in PROTOCOL_DEFAULTS.items():
        if "port" not in defaults:
            continue
        field = f"{proto}_port"
        if not hasattr(s, field):
            missing.append(f"{proto} (expected Settings.{field})")
    assert not missing, f"协议默认端口缺少 Settings 设置项（静默回退 8000 类事故的根源）: {missing}"


def test_every_protocol_default_port_visible_in_port_map(isolated_settings):
    """get_protocol_port_map 必须覆盖 PROTOCOL_DEFAULTS 的全部带 port 协议。"""
    port_map = get_protocol_port_map()
    missing = [p for p, d in PROTOCOL_DEFAULTS.items()
               if "port" in d and p not in port_map]
    assert not missing, f"协议端口映射缺失（前端设置页不会显示该协议）: {missing}"


def test_port_map_values_match_settings(isolated_settings):
    """port_map 的端口值必须与 Settings 字段一致（两层不能各说各话）。"""
    s = get_settings()
    port_map = get_protocol_port_map()
    for proto, info in port_map.items():
        field = f"{proto}_port"
        assert hasattr(s, field), f"{proto} 在 port_map 中但 Settings 缺 {field}"
        assert info["port"] == getattr(s, field), \
            f"{proto}: port_map={info['port']} vs Settings.{field}={getattr(s, field)}"


# ---------------------------------------------------------------------------
# 2. protocol_ports 字典 → 全链路生效
# ---------------------------------------------------------------------------

def test_protocol_ports_full_chain(isolated_settings):
    """字典提交 → Settings 字段 → defaults → port_map 四层一致。"""
    update_settings({"protocol_ports": {"modbus_tcp": 15021, "opcua": 14841}})
    s = get_settings()
    assert s.modbus_tcp_port == 15021
    assert s.opcua_port == 14841
    assert get_protocol_port_map()["modbus_tcp"]["port"] == 15021
    from protoforge.engine.defaults import get_protocol_defaults
    assert get_protocol_defaults("modbus_tcp")["port"] == 15021


def test_protocol_ports_persisted_to_env_file(isolated_settings, tmp_path):
    """更新必须写入 .env（重启后仍生效），而不是只改内存。"""
    env_file = tmp_path / "settings.env"
    update_settings({"protocol_ports": {"s7": 11103}})
    content = env_file.read_text(encoding="utf-8")
    assert "PROTOFORGE_S7_PORT=11103" in content.upper().replace("_PORT=", "_PORT=") or \
        "S7_PORT=11103" in content.upper(), f".env 未持久化端口: {content!r}"


# ---------------------------------------------------------------------------
# 3. 显式拒绝，绝不静默
# ---------------------------------------------------------------------------

def test_invalid_values_rejected_not_dropped(isolated_settings):
    """非法值必须显式抛 ConfigValidationError，且不得部分生效。"""
    from protoforge.config import ConfigValidationError
    with pytest.raises(ConfigValidationError):
        update_settings({"protocol_ports": {"modbus_tcp": "not_a_number"}})
    with pytest.raises(ConfigValidationError):
        update_settings({"protocol_ports": {"modbus_tcp": 99999}})
    with pytest.raises(ConfigValidationError):
        update_settings({"protocol_ports": {"modbus_tcp": 38000}})  # 与 custom_tcp 冲突
    assert get_settings().modbus_tcp_port != 38000


# ---------------------------------------------------------------------------
# 4. Settings 全字段"保存什么就必须生效什么"
# ---------------------------------------------------------------------------

SAFE_SAMPLE_VALUES = {
    "host": "127.0.0.1",
    "log_level": "warning",
    "cors_origins": ["http://localhost:3000"],
}


def _sample_value(field_name: str, current):
    """为字段生成一个与当前值不同的合法样本值。"""
    if field_name in SAFE_SAMPLE_VALUES:
        return SAFE_SAMPLE_VALUES[field_name]
    if isinstance(current, bool):
        return not current
    if isinstance(current, int) and not isinstance(current, bool):
        return current + 1 if field_name != "port" else current
    if isinstance(current, float):
        return current + 0.5
    if isinstance(current, str):
        return current + "_v15" if len(current) < 64 else current
    return None  # 复杂类型跳过（有专项覆盖）


def test_every_settings_field_round_trip(isolated_settings):
    """每个"运行时可更新"字段：update_settings 后必须生效（显式拒绝也行，静默丢弃不行）。

    端口字段有冲突校验语义（专项覆盖），此处只要求"成功更新必生效"。
    """
    s = get_settings()
    silently_dropped = []
    for field_name, field_info in type(s).model_fields.items():
        if field_name.endswith("_port") or field_name in KNOWN_IMMUTABLE_FIELDS:
            continue
        if field_info.deprecated or field_name.startswith("_"):
            continue
        current = getattr(s, field_name)
        new_value = _sample_value(field_name, current)
        if new_value is None or new_value == current:
            continue
        changed = update_settings({field_name: new_value})
        now = getattr(get_settings(), field_name)
        if now != new_value:
            silently_dropped.append(f"{field_name}: submitted {new_value!r}, got {now!r}")
    assert not silently_dropped, \
        "以下设置字段被静默丢弃（v1.4.2 协议端口事故的同类问题）:\n" + "\n".join(silently_dropped)


# Settings 中明确"不可运行时更新"的字段：启动期/安全敏感/一次性标志，
# 只能通过环境变量在进程启动时设置。此处显式列出而非默认忽略——
# 新增 Settings 字段若既不在 update_settings 白名单也不在此列表，
# test_settings_fields_all_classified 会立即失败，防止静默丢弃层再次出现。
KNOWN_IMMUTABLE_FIELDS = {
    # 安全敏感：仅环境变量（运行时可写接口不暴露）
    "jwt_secret", "admin_password", "no_auth", "reset_admin_password",
    # 认证/限流策略（进程启动时读取）
    "access_token_expires", "refresh_token_expires",
    "max_login_attempts", "lockout_duration", "min_password_length",
    "rate_limit_max_requests", "rate_limit_window_seconds",
    "rate_limit_auth_max_requests", "rate_limit_auth_window_seconds",
    # 故障切换子系统（启动期决定角色与对端）
    "failover_role", "failover_primary", "failover_standby",
    "failover_interval", "failover_max_failures",
    # 引擎/总线内部缓冲与限额（启动期初始化）
    "tick_interval", "audit_max_entries", "log_bus_max_entries",
    "log_bus_subscriber_queue", "event_bus_max_history", "event_bus_subscriber_queue",
    "forward_batch_size", "forward_flush_interval", "forward_queue_size",
    "forward_retry_count", "webhook_auto_disable_threshold", "webhook_queue_size",
    "webhook_rate_limit_seconds", "recorder_max_message_size",
    "recorder_max_messages", "recorder_queue_size", "test_max_reports",
    # 生成器沙箱限额（启动期写入沙箱配置）
    "generator_max_call_args", "generator_max_complexity", "generator_max_list_size",
    "generator_max_memory_kb", "generator_max_range_size", "generator_max_string_length",
    # HTTP 客户端超时与 RTU 串口路径（启动期）
    "http_timeout", "http_timeout_long", "http_timeout_short", "modbus_rtu_host",
}


def test_settings_fields_all_classified():
    """Settings 的每个字段必须落在：协议端口(_port) / 可更新白名单 / 已知不可更新。

    这是对 update_settings 白名单的"完备性"断言：任何新字段两边都不挂，
    就意味着它会走静默丢弃路径（v1.4.2 事故的根因模式）。
    v1.6.0: 白名单提升为 config.UPDATABLE_SETTINGS_KEYS 模块级常量，直接
    import 对比（不再从函数源码反解——inspect 方式在全量测试中会被模块
    状态污染，出现过假阳性）。
    """
    from protoforge.config import UPDATABLE_SETTINGS_KEYS

    s = get_settings()
    unclassified = []
    for field_name in type(s).model_fields:
        if field_name.endswith("_port"):
            continue
        if field_name in UPDATABLE_SETTINGS_KEYS or field_name in KNOWN_IMMUTABLE_FIELDS:
            continue
        unclassified.append(field_name)
    assert not unclassified, (
        "以下 Settings 字段既不在 UPDATABLE_SETTINGS_KEYS 也不在 KNOWN_IMMUTABLE_FIELDS，"
        f"提交后会被静默丢弃，请显式分类: {sorted(unclassified)}")
