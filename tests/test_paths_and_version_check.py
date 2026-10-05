"""v1.6.0 路径解析（core/paths）与版本检查（core/version_check）测试。"""

import sys

import pytest

from protoforge.core import paths
from protoforge.core.version_check import CachedReleaseChecker, is_newer


# ---------------------------------------------------------------------------
# paths（开发模式 = 真实仓库；冻结模式 = mock sys 属性）
# ---------------------------------------------------------------------------

def test_app_root_dev_mode_is_repo_root():
    root = paths.app_root()
    assert (root / "protoforge" / "__init__.py").exists()
    assert not paths.is_frozen()


def test_static_dir_dev_mode():
    d = paths.static_dir()
    assert (d / "index.html").exists(), f"仓库 web/dist 应存在: {d}"


def test_static_dir_env_override(tmp_path, monkeypatch):
    fake = tmp_path / "mydist"
    fake.mkdir()
    (fake / "index.html").write_text("<html></html>", encoding="utf-8")
    monkeypatch.setenv("PROTOFORGE_STATIC_DIR", str(fake))
    assert paths.static_dir() == fake


def test_static_dir_frozen_uses_bundle(tmp_path, monkeypatch):
    bundle = tmp_path / "_internal"
    dist = bundle / "web" / "dist"
    dist.mkdir(parents=True)
    (dist / "index.html").write_text("<html></html>", encoding="utf-8")
    monkeypatch.delenv("PROTOFORGE_STATIC_DIR", raising=False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(bundle), raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "ProtoForge.exe"), raising=False)
    assert paths.static_dir() == dist


def test_app_root_frozen_is_exe_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "_internal"), raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "ProtoForge.exe"), raising=False)
    assert paths.app_root() == tmp_path


# ---------------------------------------------------------------------------
# version_check
# ---------------------------------------------------------------------------

def test_is_newer_semantics():
    assert is_newer("v1.6.0", "1.5.0")
    assert is_newer("1.10.0", "1.9.9")
    assert is_newer("2.0", "1.99.99")
    assert not is_newer("1.5.0", "1.5.0")
    assert not is_newer("1.5", "1.5.0")      # 短位补零后相等
    assert not is_newer("v1.4.4", "1.5.0")


def test_fetch_release_info_success(monkeypatch):
    from protoforge.core import version_check as vc

    class FakeResp:
        def __init__(self, status_code, payload):
            self.status_code = status_code
            self._payload = payload

        def json(self):
            return self._payload

    class FakeClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, headers=None):
            if url.endswith("/releases/latest"):
                return FakeResp(200, {"tag_name": "v1.6.0",
                                      "html_url": "https://github.com/suoten/ProtoForge/releases/tag/v1.6.0",
                                      "body": "notes"})
            return FakeResp(404, {})

    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    import asyncio
    data = asyncio.run(vc.fetch_release_info("1.5.0"))
    assert data["update_available"] is True
    assert data["latest"] == "v1.6.0"
    assert not data["check_failed"]


def test_fetch_release_info_silent_failure(monkeypatch):
    from protoforge.core import version_check as vc

    class BoomClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            raise RuntimeError("offline")

        async def __aexit__(self, *a):
            return False

    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", BoomClient)
    import asyncio
    data = asyncio.run(vc.fetch_release_info("1.5.0"))
    assert data["check_failed"] is True
    assert data["update_available"] is False


def test_cached_checker_ttl(monkeypatch):
    from protoforge.core import version_check as vc

    calls = {"n": 0}

    async def fake_fetch(current, timeout=6.0):
        calls["n"] += 1
        return {"current": current, "latest": None, "update_available": False,
                "check_failed": True, "notes": "", "url": "", "upgrade_command": ""}

    monkeypatch.setattr(vc, "fetch_release_info", fake_fetch)
    checker = CachedReleaseChecker(ttl_seconds=600)
    import asyncio
    asyncio.run(checker.check("1.5.0"))
    asyncio.run(checker.check("1.5.0"))
    assert calls["n"] == 1  # 命中缓存
    checker.ttl = -1        # 强制过期
    asyncio.run(checker.check("1.5.0"))
    assert calls["n"] == 2
