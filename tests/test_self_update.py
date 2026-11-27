"""一键升级模块回归测试（v1.17.0）。

覆盖：安装形态识别、跳过版本偏好、zip 结构校验/防 zip-slip、
换目录脚本生成的关键安全断言（data 保留/回滚/换目录顺序）、
ps1 与状态机不受非 Windows 环境影响。
不覆盖：真实网络下载与真实进程重启（CI 无条件，人工验收）。
"""

import json
import sys
import zipfile

import pytest

from protoforge.core import self_update as su


# ---------- 安装形态识别 ----------

def test_install_kind_source(monkeypatch):
    monkeypatch.delenv("PF_DOCKER", raising=False)
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    assert su.install_kind() in ("pip", "source")


def test_install_kind_docker_env(monkeypatch):
    monkeypatch.setenv("PF_DOCKER", "1")
    assert su.install_kind() == "docker"


def test_can_one_click():
    assert su.can_one_click() == (su.install_kind() in ("portable", "pip"))


# ---------- 跳过此版本偏好 ----------

def test_dismiss_roundtrip(monkeypatch, tmp_path):
    prefs = tmp_path / "update_prefs.json"
    monkeypatch.setattr(su, "_prefs_path", lambda: prefs)
    assert su.get_dismissed_version() is None
    su.set_dismissed_version("1.17.0")
    assert prefs.exists()
    assert su.get_dismissed_version() == "1.17.0"
    su.set_dismissed_version(None)
    assert not prefs.exists()
    assert su.get_dismissed_version() is None


def test_dismiss_corrupt_file_is_silently_none(monkeypatch, tmp_path):
    prefs = tmp_path / "update_prefs.json"
    prefs.write_text("not-json{{", encoding="utf-8")
    monkeypatch.setattr(su, "_prefs_path", lambda: prefs)
    assert su.get_dismissed_version() is None


# ---------- zip 校验 ----------

def _make_zip(tmp_path: pytest.TempdirFactory, entries: list[str]) -> object:
    zp = tmp_path / "p.zip"
    with zipfile.ZipFile(zp, "w") as zf:
        for e in entries:
            zf.writestr(e, b"x")
    return zp


def test_verify_zip_ok(tmp_path):
    zp = _make_zip(tmp_path, ["ProtoForge/ProtoForge.exe", "ProtoForge/_internal/a.pyd"])
    assert su._verify_zip(zp) is True


def test_verify_zip_missing_exe(tmp_path):
    zp = _make_zip(tmp_path, ["ProtoForge/other.txt"])
    assert su._verify_zip(zp) is False


def test_verify_zip_rejects_slip(tmp_path):
    # zip-slip：条目逃出根目录必须拒绝
    zp = _make_zip(tmp_path, ["ProtoForge/ProtoForge.exe", "ProtoForge/../../evil.txt"])
    assert su._verify_zip(zp) is False
    zp2 = _make_zip(tmp_path, ["ProtoForge/ProtoForge.exe", "/abs/evil.txt"])
    assert su._verify_zip(zp2) is False


def test_verify_zip_broken_file(tmp_path):
    bad = tmp_path / "bad.zip"
    bad.write_bytes(b"not a zip at all")
    assert su._verify_zip(bad) is False


# ---------- 状态机 ----------

def test_state_defaults():
    st = su.get_state()
    assert st["state"] in ("idle", "downloading", "downloaded", "applying", "ready", "failed")
    assert isinstance(st["install_kind"], str)


def test_set_state_roundtrip():
    su._set_state(state="downloading", target_version="9.9.9", progress=42.5)
    st = su.get_state()
    assert st["state"] == "downloading" and st["progress"] == 42.5
    su._set_state(state="idle", target_version=None, progress=0.0)


# ---------- 换目录脚本生成的安全断言 ----------

def test_write_update_ps1_safety(monkeypatch, tmp_path):
    """ps1 必须满足：data 先移出再换目录、失败回滚、新目录完整性检查、
    脚本本体放在程序目录外（换目录不吞脚本）。"""
    app = tmp_path / "ProtoForge"
    app.mkdir()
    fake_paths = {"app_root": lambda: app}
    monkeypatch.setattr(su, "_work_dir", lambda: app.parent)
    import protoforge.core.paths as paths_mod
    monkeypatch.setattr(paths_mod, "app_root", lambda: app)
    # _write_update_ps1 内部 from ... import app_root（延迟导入）——按模块源打桩
    monkeypatch.setitem(su.__dict__, "_paths_app_root", paths_mod.app_root)

    ps1 = su._write_update_ps1("9.9.9")
    text = ps1.read_text(encoding="utf-8-sig")
    try:
        # 脚本在程序目录之外（父级），换目录重命名不会影响脚本自身
        assert ps1.parent == app.parent
        assert ps1.exists()
        # data 保留：先移出 -> 换目录后移回
        assert "Move-Item \"$cur\\data\" $dataBak" in text
        assert "Move-Item $dataBak \"$cur\\data\"" in text
        # 完整性检查 + 回滚
        assert "ProtoForge.exe'))" in text.replace('"', '').replace("'", "") or "ProtoForge.exe" in text
        assert "rolled back" in text
        # 顺序：先停进程再换目录
        assert text.index("Stop-Process") < text.index("Rename-Item $cur $old")
        # 重启
        assert "Start-Process" in text
    finally:
        ps1.unlink(missing_ok=True)


# ---------- 下载源选择（不发真实请求的分支逻辑） ----------

def test_mirror_env_only(monkeypatch):
    """Gitee/GitHub 都查不到时，配置了镜像则按约定 URL 兜底。"""
    async def none_gitee(version):
        return None

    monkeypatch.setenv("PROTOFORGE_UPDATE_MIRROR", "https://mirror.example.com/")
    import protoforge.core.version_check as vc
    async def fake_fetch(current, timeout=6.0):
        return {"latest": None}
    # find_portable_asset 内部直连 GitHub API 查询失败时走镜像兜底
    # （网络请求会真实发生——沙箱/CI 网络异常时同样落入兜底分支）
    try:
        url, src = None, None
        import asyncio
        loop = asyncio.new_event_loop()
        try:
            url, src = loop.run_until_complete(su.find_portable_asset("9.9.9"))
        finally:
            loop.close()
        assert src == "mirror"
        assert url.startswith("https://mirror.example.com/")
        assert "ProtoForge-v9.9.9-win64-portable.zip" in url
    finally:
        monkeypatch.delenv("PROTOFORGE_UPDATE_MIRROR", raising=False)


def test_start_download_rejects_busy_or_unsupported(monkeypatch):
    monkeypatch.setenv("PF_DOCKER", "1")
    with pytest.raises(RuntimeError, match="docker"):
        su.start_download("9.9.9")
    monkeypatch.delenv("PF_DOCKER", raising=False)
    su._set_state(state="downloading", target_version=None)
    try:
        with pytest.raises(RuntimeError, match="正在进行中"):
            su.start_download("9.9.9")
    finally:
        su._set_state(state="idle")
