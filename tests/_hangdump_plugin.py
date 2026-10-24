"""诊断插件（仅排障用）：测试超 45s 转储协程级栈（含 await 链）。"""
import asyncio
import gc
import sys
import threading
import time
import traceback

_state = {"nodeid": None, "start": 0.0, "dumped": set()}


def pytest_runtest_logstart(nodeid):
    _state["nodeid"] = nodeid
    _state["start"] = time.monotonic()


def pytest_runtest_logfinish(nodeid):
    if _state["nodeid"] == nodeid:
        _state["nodeid"] = None


def _dump():
    out = sys.__stderr__
    loops = [o for o in gc.get_objects()
             if isinstance(o, asyncio.AbstractEventLoop) and o.is_running()]
    for loop in loops:
        try:
            tasks = asyncio.all_tasks(loop)
        except RuntimeError:
            continue
        for t in tasks:
            print(f"--- TASK {t.get_name()} done={t.done()} ---", file=out)
            stack = t.get_stack(limit=12)
            for f in stack:
                print(f"    {f.f_code.co_filename}:{f.f_lineno} {f.f_code.co_name}", file=out)
    out.flush()


def _watcher():
    while True:
        time.sleep(5)
        nodeid = _state["nodeid"]
        if not nodeid:
            continue
        elapsed = time.monotonic() - _state["start"]
        if elapsed < 45:
            continue
        key = (nodeid, int(elapsed // 45))
        if key in _state["dumped"]:
            continue
        _state["dumped"].add(key)
        out = sys.__stderr__
        print(f"\n=== HANGDUMP {nodeid} (running {elapsed:.0f}s) ===", file=out)
        _dump()
        out.flush()


threading.Thread(target=_watcher, daemon=True).start()
