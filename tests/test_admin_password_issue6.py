"""Issue #6 回归：admin 密码来源语义（无 env 沿用旧密码文件，不再每次重随机）。"""

import asyncio
from pathlib import Path

import pytest


def _fresh_user_manager(tmp_path: Path, monkeypatch, env_pw: str | None):
    """构造隔离的 UserManager（密码文件落在 tmp_path/data）。

    彻底隔离配置链：repo 根的 .env（可能含 PROTOFORGE_ADMIN_PASSWORD）
    必须被屏蔽，否则 pydantic-settings 读到它，env 分支抢先生效。
    """
    import importlib

    import protoforge.core.auth as auth_mod

    # ① 屏蔽 .env：Settings.model_config 的 env_file 在类定义时已固化为
    # repo/.env 字符串——改模块级 _ENV_FILE 无效，必须改类配置本身。
    import protoforge.config as config_mod
    monkeypatch.setattr(
        config_mod.Settings, "model_config",
        {**config_mod.Settings.model_config, "env_file": str(tmp_path / "no-such.env")})
    # ② 环境变量：env_pw 给值，否则删键（不设空串——空串语义因 loader 而异）
    if env_pw is None:
        monkeypatch.delenv("PROTOFORGE_ADMIN_PASSWORD", raising=False)
    else:
        monkeypatch.setenv("PROTOFORGE_ADMIN_PASSWORD", env_pw)
    # ③ 配置缓存清掉，让 admin_password 重新求值
    monkeypatch.setattr(config_mod, "_settings", None, raising=False)
    config_mod._settings_overrides.clear()
    # ④ paths.app_root → tmp_path（密码文件落点）
    import protoforge.core.paths as paths_mod
    monkeypatch.setattr(paths_mod, "app_root", lambda: tmp_path)
    # ⑤ 重建模块级单例（reload 重执行 user_manager = UserManager()）
    monkeypatch.setattr(auth_mod, "_user_manager", None, raising=False)
    importlib.reload(auth_mod)
    return auth_mod


@pytest.fixture
def isolated_auth(tmp_path, monkeypatch):
    auth_mod = _fresh_user_manager(tmp_path, monkeypatch, None)
    yield auth_mod, tmp_path
    monkeypatch.setattr(auth_mod, "_user_manager", None, raising=False)


def test_no_env_first_start_generates_and_persists(isolated_auth):
    auth_mod, tmp_path = isolated_auth
    um = auth_mod.user_manager
    pw_file = Path(um._admin_password_file)
    assert pw_file.exists()
    first = pw_file.read_text(encoding="utf-8").strip()
    assert first and um._admin_password_generated is True
    # 内存里的 admin 用户能用文件里的密码通过验证
    user = um.get_user_by_username("admin")
    assert auth_mod.verify_password(first, user.password_hash)


def test_no_env_restart_reuses_password_file(isolated_auth):
    """核心修复：重启（重建 UserManager）不换密码——沿用已有文件。"""
    auth_mod, tmp_path = isolated_auth
    um1 = auth_mod.user_manager
    pw_file = Path(um1._admin_password_file)
    first = pw_file.read_text(encoding="utf-8").strip()

    # 模拟重启：重新实例化 UserManager（同 app_root）
    um2 = auth_mod.UserManager()
    second = pw_file.read_text(encoding="utf-8").strip()
    assert second == first, "重启后密码文件不得被重新随机覆盖"
    assert um2._admin_password_generated is False  # 沿用，非新生成
    user = um2.get_user_by_username("admin")
    assert auth_mod.verify_password(first, user.password_hash)


def test_env_password_overrides_file(tmp_path, monkeypatch):
    """显式设置 PROTOFORGE_ADMIN_PASSWORD → 以 env 为准（并同步 DB）。"""
    auth_mod = _fresh_user_manager(tmp_path, monkeypatch, "mypw123")
    um = auth_mod.user_manager
    user = um.get_user_by_username("admin")
    assert auth_mod.verify_password("mypw123", user.password_hash)
    # admin/admin 不再可用
    assert not auth_mod.verify_password("admin", user.password_hash)


def test_password_file_reuse_syncs_db_hash(isolated_auth):
    """沿用旧密码文件时，restore_from_db 后 DB 哈希与文件密码一致。"""
    auth_mod, tmp_path = isolated_auth
    um = auth_mod.user_manager
    pw = Path(um._admin_password_file).read_text(encoding="utf-8").strip()

    class FakeDB:
        def __init__(self, rows):
            self._rows = rows
            self.saved = []

        async def load_all_users(self):
            return self._rows

        async def save_user(self, u):
            self.saved.append(u)

    # DB 里放一个"旧密码"哈希（模拟首次启动后的持久化）
    old_hash = auth_mod.hash_password("old-password")
    db = FakeDB([{"id": "admin", "username": "admin",
                  "password_hash": old_hash, "role": "admin"}])
    asyncio.run(_sync(um, db))
    # 同步后：文件密码（本次生效密码）可用
    user = um.get_user_by_username("admin")
    assert auth_mod.verify_password(pw, user.password_hash)
    assert not auth_mod.verify_password("old-password", user.password_hash)


async def _sync(um, db):
    um.set_database(db)
    await um.restore_from_db()
