"""Reproduce issue: cannot change custom_tcp port (user report 2026-09-20).

Checks:
1. GET /api/v1/protocols -> custom_tcp entry contains config_schema with port?
2. POST /api/v1/protocols/custom_tcp/start {port: 38123} -> actually listening on 38123?
3. GET /api/v1/protocols/{name}/config -> schema has port?
"""
import asyncio
import os
import sys

os.environ["PROTOFORGE_NO_AUTH"] = "1"
os.environ.setdefault("PROTOFORGE_ADMIN_PASSWORD", "diag-pw")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


async def main() -> None:
    from httpx import AsyncClient, ASGITransport
    from protoforge.main import app

    try:
        from asgi_lifespan import LifespanManager
        mgr = LifespanManager(app)
        await mgr.startup()
    except ImportError:
        mgr = None
        await app.router.startup()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        # 1. protocol list carries schema?
        r = await c.get("/api/v1/protocols")
        entries = {p["name"]: p for p in r.json()["protocols"]}
        ct = entries.get("custom_tcp")
        print("1) custom_tcp in list:", bool(ct))
        schema = (ct or {}).get("config_schema") or {}
        print("   config_schema keys:", list((schema.get("properties") or schema).keys())[:8])

        # 2. start with custom port
        r = await c.post("/api/v1/protocols/custom_tcp/start", json={"port": 38123, "host": "0.0.0.0"})
        print("2) start with port 38123 ->", r.status_code, r.json())

        await asyncio.sleep(1.0)
        # is it listening?
        reader = asyncio.open_connection
        try:
            _, w = await asyncio.wait_for(asyncio.open_connection("127.0.0.1", 38123), timeout=3)
            print("   TCP connect to 38123: OK")
            w.close()
        except Exception as e:
            print(f"   TCP connect to 38123 FAILED: {e}")
            # check actual port
            try:
                _, w = await asyncio.wait_for(asyncio.open_connection("127.0.0.1", 38000), timeout=3)
                print("   but 38000 IS listening -> port config ignored!")
                w.close()
            except Exception as e2:
                print(f"   38000 also closed: {e2}")

        # 3. per-protocol config endpoint
        r = await c.get("/api/v1/protocols/custom_tcp/config")
        s2 = r.json()
        props = s2.get("properties") or s2
        print("3) /config endpoint keys:", list(props.keys())[:8])

        await c.post("/api/v1/protocols/custom_tcp/stop")

    if mgr is not None:
        await mgr.shutdown()
    else:
        await app.router.shutdown()

    sys.stdout.flush()
    os._exit(0)


if __name__ == "__main__":
    asyncio.run(main())
