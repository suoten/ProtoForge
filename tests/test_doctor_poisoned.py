"""doctor 假包污染检测回归测试（v1.13.3，GitHub issue #37）。

背景：PyPI 上的 `protoforge` 0.1.0（无关项目，"AI 硬件原型 CLI"）与本项目
共用顶层 `protoforge/` 模块路径——用户 `pip install protoforge` 装到假包后
"啥也不是"（issue #37 的真实投诉），即便再装 `protoforge-sim` 也会互相覆盖。
doctor 现在检测该污染状态并给出修复命令。
"""

from types import SimpleNamespace

from protoforge import doctor


class _FakeDist(SimpleNamespace):
    """importlib.metadata.Distribution 最小桩：只需 metadata['Name'] 与 version。"""


def _dist(name: str, version: str):
    return _FakeDist(metadata={"Name": name}, version=version)


def test_poisoned_install_detected(monkeypatch):
    monkeypatch.setattr("importlib.metadata.distributions",
                        lambda: iter([_dist("protoforge", "0.1.0"),
                                      _dist("protoforge-sim", "1.13.3")]))
    results = doctor.check_poisoned_install()
    hit = next(r for r in results if r.check_id == "install.poisoned")
    assert hit.severity == "error"
    assert "0.1.0" in hit.title
    assert any("uninstall -y protoforge" in f for f in hit.fixes)


def test_clean_environment_ok(monkeypatch):
    monkeypatch.setattr("importlib.metadata.distributions",
                        lambda: iter([_dist("protoforge-sim", "1.13.3"),
                                      _dist("httpx", "0.27.0")]))
    results = doctor.check_poisoned_install()
    hit = next(r for r in results if r.check_id == "install.poisoned")
    assert hit.severity == "ok"


def test_poisoned_check_never_raises(monkeypatch):
    def _boom():
        raise RuntimeError("metadata scan exploded")

    monkeypatch.setattr("importlib.metadata.distributions", _boom)
    assert doctor.check_poisoned_install() == []  # 静默跳过，不阻断其他检查
