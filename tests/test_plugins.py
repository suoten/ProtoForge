"""插件系统单元测试（v1.15.0）——不依赖真实 data/plugins 目录。"""

import json

import pytest

from protoforge import plugins as pf_plugins


@pytest.fixture
def fresh_state(monkeypatch):
    """每个测试重置插件系统缓存，并快照/还原插件注入的全局注册表。

    插件测试会把假协议写进 _PROTOCOL_CLASSES 与 PROTOCOL_DEFAULTS（真全局
    单例）——不还原会泄漏到其他测试文件（settings_chain 一致性门禁会要求
    Settings.plugin_test_proto_port 而误报）。
    """
    from protoforge.engine.defaults import PROTOCOL_DEFAULTS
    from protoforge.protocols import PROTOCOL_REGISTRY, _PROTOCOL_CLASSES

    monkeypatch.setattr(pf_plugins, "_loaded_plugins", [])
    monkeypatch.setattr(pf_plugins, "_load_errors", [])
    monkeypatch.setattr(pf_plugins, "_plugins_loaded", False)
    saved_classes = dict(_PROTOCOL_CLASSES)
    saved_defaults = {k: dict(v) if isinstance(v, dict) else v for k, v in PROTOCOL_DEFAULTS.items()}
    yield pf_plugins
    _PROTOCOL_CLASSES.clear()
    _PROTOCOL_CLASSES.update(saved_classes)
    for k in list(PROTOCOL_DEFAULTS.keys()):
        if k not in saved_defaults:
            PROTOCOL_DEFAULTS.pop(k, None)
    for k, v in saved_defaults.items():
        if k in PROTOCOL_DEFAULTS:
            PROTOCOL_DEFAULTS[k] = v
    # 惰性加载过的类也清出 PROTOCOL_REGISTRY（load_plugins 测试可能触发）
    for name in list(PROTOCOL_REGISTRY):
        if name not in saved_classes:
            PROTOCOL_REGISTRY.pop(name, None)


def _write_plugin(root, pid="test-pack", protocols=None):
    root.mkdir(parents=True, exist_ok=True)
    manifest = {"id": pid, "name": pid, "version": "1.0.0", "kind": "industry-pack",
                "templates": ["templates"], "protocols": protocols or []}
    (root / "plugin.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    tpl_dir = root / "templates" / "modbus_tcp"
    tpl_dir.mkdir(parents=True, exist_ok=True)
    (tpl_dir / "t1.json").write_text(json.dumps({
        "id": "plugin-test-tpl", "name": "插件测试模板", "protocol": "modbus_tcp",
        "points": [{"name": "v", "address": "0", "data_type": "float32"}],
    }, ensure_ascii=False), encoding="utf-8")
    return root


def test_dir_plugin_full_pipeline(fresh_state, tmp_path, monkeypatch):
    """目录插件全链路：manifest → 协议注册 → 模板装载。"""
    root = _write_plugin(tmp_path / "plugins" / "test-pack",
                         protocols=[{"name": "plugin_test_proto",
                                     "server": "protoforge.plugins.dummy:DummyServer",
                                     "defaults": {"host": "0.0.0.0", "port": 21001}}])
    monkeypatch.setattr(pf_plugins, "_plugins_root", lambda: tmp_path / "plugins")

    loaded = fresh_state.load_plugins()
    assert len(loaded) == 1
    info = loaded[0]
    assert info["id"] == "test-pack"
    assert info["protocols"] == ["plugin_test_proto"]

    # 协议进入懒加载映射（与内置协议同一管道）
    from protoforge.protocols import _PROTOCOL_CLASSES
    assert _PROTOCOL_CLASSES["plugin_test_proto"] == "protoforge.plugins.dummy:DummyServer"
    from protoforge.engine.defaults import PROTOCOL_DEFAULTS
    assert PROTOCOL_DEFAULTS["plugin_test_proto"]["port"] == 21001

    # 幂等
    assert fresh_state.load_plugins() == loaded

    # 模板装载
    from protoforge.engine.template import TemplateManager
    tm = TemplateManager()
    count = fresh_state.load_plugin_templates(tm)
    assert count >= 1
    assert tm.get_template("plugin-test-tpl").name == "插件测试模板"


def test_manifest_validation(fresh_state, tmp_path, monkeypatch):
    """缺 id/kind 的 manifest 被拒绝且不进错误列表（仅 warning）。"""
    root = tmp_path / "plugins" / "bad"
    root.mkdir(parents=True)
    (root / "plugin.json").write_text(json.dumps({"name": "no-id"}), encoding="utf-8")
    monkeypatch.setattr(pf_plugins, "_plugins_root", lambda: tmp_path / "plugins")
    assert fresh_state.load_plugins() == []
    assert fresh_state.get_plugin_status()["errors"] == []


def test_load_failure_isolated(fresh_state, tmp_path, monkeypatch):
    """协议 server 字符串非法 → 插件进 errors 列表，主进程不炸。"""
    root = _write_plugin(tmp_path / "plugins" / "broken", pid="broken",
                         protocols=[{"name": "bad_proto", "server": "no-colon"}])
    monkeypatch.setattr(pf_plugins, "_plugins_root", lambda: tmp_path / "plugins")
    loaded = fresh_state.load_plugins()
    assert loaded == []
    errs = fresh_state.get_plugin_status()["errors"]
    assert len(errs) == 1 and errs[0]["id"] == "broken"


def test_protocol_shadowing_protected(fresh_state, tmp_path, monkeypatch):
    """插件协议名与内置协议冲突 → 跳过该协议但插件其余内容照常加载。"""
    root = _write_plugin(tmp_path / "plugins" / "shadow",
                         protocols=[{"name": "modbus_tcp",
                                     "server": "protoforge.plugins.dummy:DummyServer"}])
    monkeypatch.setattr(pf_plugins, "_plugins_root", lambda: tmp_path / "plugins")
    loaded = fresh_state.load_plugins()
    assert len(loaded) == 1
    assert loaded[0]["protocols"] == []  # modbus_tcp 被保护，插件协议列表为空
    from protoforge.protocols import PROTOCOL_REGISTRY
    assert PROTOCOL_REGISTRY["modbus_tcp"].__module__.startswith("protoforge.protocols")


def test_load_extra_dir_grouped(fresh_state, tmp_path):
    """load_extra_dir 支持子目录分组布局。"""
    from pathlib import Path

    from protoforge.engine.template import TemplateManager
    root = _write_plugin(tmp_path / "p")
    tm = TemplateManager()
    count = tm.load_extra_dir(Path(root / "templates"))
    assert count == 1
    # 重复加载：id 相同只覆盖不新增 → 返回 0（新增数为 0 是合理语义）
    assert tm.load_extra_dir(Path(root / "templates")) == 0
    assert tm.get_template("plugin-test-tpl").name == "插件测试模板"  # 覆盖后仍可用
