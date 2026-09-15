"""Regression: banner/env admin password must always work after restart (was 401)."""
import asyncio, os, sys
sys.path.insert(0, r"E:\硕腾网络\PyGBSentry\ProtoForge")

# 必须在导入 protoforge 模块之前设置环境变量（get_settings 会缓存）
os.environ["PROTOFORGE_ADMIN_PASSWORD"] = "pw-one-111"
from protoforge.core.auth import UserManager, verify_password
import protoforge.config as config_module


def _reset_settings_cache():
    config_module._settings = None
    config_module._settings_overrides.clear()


class FakeDB:
    def __init__(self):
        self.users = {}          # username -> dict
    async def load_all_users(self):
        return list(self.users.values())
    async def save_user(self, u):
        self.users[u["username"]] = dict(u)


async def main():
    # ---- Boot 1: env password P1, fresh DB ----
    _reset_settings_cache()
    um1 = UserManager()
    db = FakeDB()
    um1.set_database(db)
    await um1.restore_from_db()
    ok1, _ = await um1.authenticate("admin", "pw-one-111")
    assert ok1, "boot1: env password P1 must work"
    print("boot1 login P1: OK")

    # simulate DB persist of boot1 admin (bcrypt hash of P1)
    admin_row = dict(db.users["admin"])
    assert verify_password("pw-one-111", admin_row["password_hash"])

    # ---- Boot 2 (restart): NEW banner password P2 against DB that still holds P1 ----
    os.environ["PROTOFORGE_ADMIN_PASSWORD"] = "pw-two-222"
    _reset_settings_cache()
    um2 = UserManager()
    db2 = FakeDB()
    db2.users["admin"] = admin_row          # DB 仍是旧密码哈希（首次启动的 P1）
    um2.set_database(db2)
    await um2.restore_from_db()             # 修复点：启动同步
    ok2, _ = await um2.authenticate("admin", "pw-two-222")
    stale, _ = await um2.authenticate("admin", "pw-one-111")
    wrong, _ = await um2.authenticate("admin", "admin")
    assert ok2, "REPRO: banner password must work after restart (was 401)"
    assert not stale, "old password must be rejected after sync"
    assert not wrong, "admin/admin must stay rejected unless explicitly configured"
    print("boot2 login P2 (banner):  OK")
    print("boot2 old P1 rejected:    OK")
    print("boot2 admin/admin rejected: OK (README 已修正该描述)")
    print("ALL AUTH SYNC REGRESSION PASSED")


asyncio.run(main())
