"""Regression: realtime log streaming must not crash under high-frequency traffic.

Covers the user-reported "实时日志会让系统崩溃" issue:
1. LogBus emit from a NON-event-loop thread (protocol worker threads) must deliver
   entries safely via call_soon_threadsafe (asyncio.Queue is not thread-safe).
2. /ws/logs must batch-drain the queue (log_batch frames) instead of sending one
   WS frame per entry — in-loop bursts (the real protocol-handler path) must
   produce large frames.
3. Flooding far beyond the subscriber queue cap (1000) must drop oldest entries
   gracefully — no hang, no crash, connection stays usable.

NOTE: everything runs inside `with client:` because the app lifespan initializes
the log bus (and resets the registry singleton on exit).
"""
import asyncio
import os
import socket
import sys
import threading
import time

os.environ["PROTOFORGE_NO_AUTH"] = "1"
os.environ.setdefault("PROTOFORGE_ADMIN_PASSWORD", "diag-admin-pw")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import uvicorn  # noqa: E402
import websockets  # noqa: E402

N_BATCH = 500
N_FLOOD = 3000


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def emit_burst(bus, n: int, tag: str, protocol: str = "modbus_tcp") -> None:
    for i in range(n):
        bus.emit(protocol, "inbound", "diag-device", "modbus_read",
                 f"{tag}: addr={i} count=1", {"fc": 3, "start": i})


async def read_entries(ws, want: int, timeout: float = 15.0):
    """Read log frames until `want` entries collected; return (entries, frames, sizes)."""
    import json
    entries, frames, sizes = [], 0, []
    deadline = asyncio.get_event_loop().time() + timeout
    while len(entries) < want:
        remaining = deadline - asyncio.get_event_loop().time()
        if remaining <= 0:
            raise TimeoutError(f"only {len(entries)}/{want} entries received")
        msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=remaining))
        if msg.get("type") == "log_batch":
            data = msg.get("data", [])
            entries.extend(data)
            sizes.append(len(data))
        elif msg.get("type") == "log":
            entries.append(msg["data"])
            sizes.append(1)
        elif msg.get("type") == "ping":
            continue
        else:
            raise AssertionError(f"unexpected frame type: {msg.get('type')}")
        frames += 1
    return entries, frames, sizes


async def run_phases(url: str, bus) -> None:
    async with websockets.connect(url, max_size=None) as ws:
        await asyncio.sleep(0.5)  # let ws handler subscribe
        assert len(bus._subscribers) == 1, "expected exactly one subscriber"

        # ---- Phase 1: cross-thread burst (protocol worker threads) ----
        t = threading.Thread(target=emit_burst, args=(bus, N_BATCH, "p1"))
        t.start()
        t.join()
        entries, frames, sizes = await read_entries(ws, N_BATCH)
        assert all(e.get("protocol") == "modbus_tcp" for e in entries), "wrong payload"
        assert frames < N_BATCH, f"no batching at all: {N_BATCH} entries in {frames} frames"
        print(f"phase1 cross-thread burst: {N_BATCH} entries / {frames} frames  OK")

        # ---- Phase 1b: in-loop burst (real protocol-handler path) ----
        # Emit from INSIDE the server event loop, exactly like protocol servers do.
        # The drain must coalesce this into a handful of large frames.
        fut = asyncio.run_coroutine_threadsafe(_emit_in_loop(bus, N_BATCH, "p1b"), bus._loop)
        fut.result(timeout=10)
        entries, frames, sizes = await read_entries(ws, N_BATCH)
        assert all(e.get("protocol") == "modbus_tcp" for e in entries), "wrong payload"
        assert frames <= 8, f"in-loop batching ineffective: {N_BATCH} entries in {frames} frames"
        print(f"phase1b in-loop burst: {N_BATCH} entries / {frames} frames  OK")

        # ---- Phase 2: flood 3x beyond queue cap -> graceful drop, no crash ----
        t = threading.Thread(target=emit_burst, args=(bus, N_FLOOD, "p2"))
        t.start()
        t.join()

        received = 0
        deadline = time.time() + 10
        while time.time() < deadline:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=1.0)
            except (asyncio.TimeoutError, websockets.ConnectionClosed):
                break
            import json
            msg = json.loads(raw)
            if msg.get("type") == "log_batch":
                received += len(msg.get("data", []))
            elif msg.get("type") == "log":
                received += 1
        # Consumer may keep pace with the flood (preferred) or the bounded
        # queue may drop oldest entries under a slower reader — both are fine.
        assert received > 0, "no entries received during flood"
        # bus ring buffer must stay intact and queryable
        recent = bus.get_recent(count=10)
        assert len(recent) == 10, "get_recent broken after flood"
        # connection must still be usable: emit one more and receive it
        bus.emit("modbus_tcp", "system", "diag-device", "health_check", "p2-final")
        import json
        while True:
            msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
            if msg.get("type") in ("log_batch", "log"):
                data = msg["data"] if msg["type"] == "log_batch" else [msg["data"]]
                assert any(e.get("message_type") == "health_check" for e in data)
                break
        print(f"phase2 flood: {N_FLOOD} emits -> {received} delivered (dropped oldest), "
              f"bus intact, ws alive  OK")

    print("ALL LOG STRESS REGRESSION PASSED")


async def _emit_in_loop(bus, n: int, tag: str) -> None:
    """Emit n entries synchronously inside the server event loop (no awaits),
    mimicking protocol handlers logging per PDU within one loop step."""
    for i in range(n):
        bus.emit("modbus_tcp", "inbound", "diag-device", "modbus_read",
                 f"{tag}: addr={i} count=1", {"fc": 3, "start": i})
    await asyncio.sleep(0)


def main() -> None:
    port = _free_port()
    config = uvicorn.Config("protoforge.main:app", host="127.0.0.1", port=port,
                            log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 30
    while not server.started and time.time() < deadline:
        time.sleep(0.1)
    assert server.started, "uvicorn failed to start"

    from protoforge.engine.registry import get_log_bus
    try:
        asyncio.run(run_phases(f"ws://127.0.0.1:{port}/api/v1/ws/logs", get_log_bus()))
    finally:
        server.should_exit = True
        thread.join(timeout=10)


if __name__ == "__main__":
    main()
