# -*- coding: utf-8 -*-
"""v1.6.29 Docker 环境检测与诊断警示项测试"""

from protoforge.core.netutils import in_docker


def test_in_docker_false_on_windows_host(monkeypatch):
    """Windows 宿主机（无容器标记文件）应返回 False。"""
    monkeypatch.delenv("PROTOFORGE_IN_CONTAINER", raising=False)
    assert in_docker() is False


def test_in_docker_env_override(monkeypatch):
    """环境变量显式声明容器内运行时应返回 True。"""
    monkeypatch.setenv("PROTOFORGE_IN_CONTAINER", "1")
    assert in_docker() is True
    monkeypatch.setenv("PROTOFORGE_IN_CONTAINER", "true")
    assert in_docker() is True


def test_in_docker_env_invalid_value(monkeypatch):
    monkeypatch.setenv("PROTOFORGE_IN_CONTAINER", "0")
    assert in_docker() is False


def test_diagnose_check_item_shape():
    """诊断项统一携带 warn 字段（前端渲染依赖）。"""
    import inspect
    from protoforge.api.v1 import diagnostics_routes
    src = inspect.getsource(diagnostics_routes.diagnose_protocol)
    assert "docker_port_map" in src
    assert "diag_s_docker" in src
    assert "has_warn" in src
