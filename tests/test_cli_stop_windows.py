"""FIXED(Issue#12): Windows 后台启动（start /B）后 'protoforge stop' 失效回归测试。

根因：
1. PID 文件仅在 Unix daemon 分支写入 —— Windows 'start /B' 启动永远没有
   data/protoforge.pid，stop 提示"No background daemon found"
2. 旧代码用 os.kill(pid, 0) 探测进程存活，Windows 上 os.kill 对非 CTRL_*
   信号一律 TerminateProcess —— "探测"直接把目标进程杀掉

修复后：
- 所有启动方式（前台 / start /B 后台 / Unix daemon）都写 PID 文件
- _process_alive() 跨平台安全探测（Windows 用 tasklist）
- stop 在 Windows 用 taskkill /T /F（杀进程树）；无 PID 文件时按端口兜底
  查找 python 进程（netstat -ano），避免残留服务无法停止
"""

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from protoforge.cli import _find_pid_by_port, _get_pid_file, _process_alive, _write_pid_file


def _spawn_sleeper() -> subprocess.Popen:
    """启动一个存活数分钟的 python 子进程，用于存活/停止测试。"""
    return subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(300)"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


class TestProcessAlive:
    def test_alive_process_detected(self):
        """存活进程 → True（且不会被 os.kill(pid,0) 的 Windows 语义误杀）."""
        proc = _spawn_sleeper()
        try:
            time.sleep(0.3)
            assert _process_alive(proc.pid) is True
            # 旧实现在 Windows 上此处已把进程杀死（TerminateProcess exit code 0）
            assert _process_alive(proc.pid) is True
        finally:
            proc.kill()
            proc.wait(timeout=10)

    def test_dead_process_detected(self):
        proc = _spawn_sleeper()
        proc.kill()
        proc.wait(timeout=10)
        time.sleep(0.3)
        assert _process_alive(proc.pid) is False

    def test_invalid_pid(self):
        assert _process_alive(0) is False
        assert _process_alive(-1) is False


class TestWritePidFile:
    def test_write_and_cleanup(self, tmp_path: Path, monkeypatch):
        """_write_pid_file 写入当前 PID；atexit 清理."""
        monkeypatch.chdir(tmp_path)
        _write_pid_file()
        pid_file = tmp_path / "data" / "protoforge.pid"
        assert pid_file.exists()
        assert int(pid_file.read_text().strip()) == os.getpid()


class TestStopCommand:
    def test_stop_kills_pid_file_process(self, tmp_path: Path, monkeypatch, capsys):
        """PID 文件指向存活进程 → stop 后进程终止、PID 文件清理."""
        from protoforge.cli import _stop_command
        monkeypatch.chdir(tmp_path)
        proc = _spawn_sleeper()
        try:
            time.sleep(0.3)
            pid_file = tmp_path / "data" / "protoforge.pid"
            pid_file.parent.mkdir(parents=True, exist_ok=True)
            pid_file.write_text(str(proc.pid))
            _stop_command(port=59999)
            proc.wait(timeout=15)
            assert not pid_file.exists()
            out = capsys.readouterr().out
            assert "stopped" in out
        finally:
            if proc.poll() is None:
                proc.kill()

    def test_stop_stale_pid_file(self, tmp_path: Path, monkeypatch, capsys):
        """PID 文件指向已退出进程 → 提示已停止并清理文件."""
        from protoforge.cli import _stop_command
        monkeypatch.chdir(tmp_path)
        proc = _spawn_sleeper()
        proc.kill()
        proc.wait(timeout=10)
        pid_file = tmp_path / "data" / "protoforge.pid"
        pid_file.parent.mkdir(parents=True, exist_ok=True)
        pid_file.write_text(str(proc.pid))
        _stop_command(port=59999)
        assert not pid_file.exists()
        assert "not found" in capsys.readouterr().out or "already stopped" in capsys.readouterr().out

    def test_stop_without_pid_file_no_target(self, tmp_path: Path, monkeypatch, capsys):
        """无 PID 文件且端口无 python 监听 → 明确提示，不误杀."""
        from protoforge.cli import _stop_command
        monkeypatch.chdir(tmp_path)
        _stop_command(port=59998)
        out = capsys.readouterr().out
        assert "No background daemon found" in out


@pytest.mark.skipif(sys.platform != "win32", reason="port fallback is Windows-only")
class TestFindPidByPort:
    def test_finds_python_listener(self, tmp_path: Path):
        """真实启动一个监听端口的 python 进程 → 按端口找到其 PID."""
        import socket

        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.bind(("127.0.0.1", 0))
        port = srv.getsockname()[1]
        srv.close()
        proc = subprocess.Popen(
            [sys.executable, "-c",
             f"import socket,time;s=socket.socket();s.bind(('127.0.0.1',{port}));"
             f"s.listen(1);time.sleep(120)"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        try:
            time.sleep(1.0)
            found = _find_pid_by_port(port)
            assert found == proc.pid
        finally:
            proc.kill()
            proc.wait(timeout=10)

    def test_no_listener_returns_none(self):
        assert _find_pid_by_port(59997) is None
