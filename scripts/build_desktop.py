"""ProtoForge 桌面便携包构建脚本（v1.6.0）。

用法（仓库根目录，建议用项目 venv 的 python）::

    python scripts/build_desktop.py            # PyInstaller 构建 + 打 zip
    python scripts/build_desktop.py --no-zip   # 只构建不打包
    python scripts/build_desktop.py --skip-build --zip  # 只把已有 dist/ProtoForge 打 zip

前置条件：
  1. venv 里已安装 pyinstaller（pip install pyinstaller pystray pillow）
  2. web/dist 已构建（cd web && npm install && npm run build）

产物：
  dist/ProtoForge/                              # onedir，双击 ProtoForge.exe 即用
  dist/ProtoForge-v<版本>-win64-portable.zip    # 便携包（解压即用，配置随目录走）

验收（规划 v1.6.0）：便携 zip 体积 ≤ 300MB；全新 Windows 机器双击
ProtoForge.exe ≤ 2 分钟进入界面（无 Python/Node/Docker 依赖）。
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))  # 脚本可直接运行（scripts/ 不在包路径上）
DIST = ROOT / "dist"
APP_DIR = DIST / "ProtoForge"
MAX_ZIP_MB = 300  # 规划验收线


def run(cmd: list[str]) -> int:
    print("+", " ".join(str(c) for c in cmd))
    return subprocess.run([str(c) for c in cmd], cwd=str(ROOT)).returncode


def get_version() -> str:
    # 源码内 __version__ 是单一事实源（installed dist-info 可能是陈旧的
    # editable 元数据，如 0.1.0）；元数据仅作兜底
    import protoforge
    v = getattr(protoforge, "__version__", None)
    if v and v != "0.1.0":
        return v
    try:
        from importlib.metadata import version
        return version("protoforge")
    except Exception:
        return v or "0.0.0"


def _force_clean_dir(path: Path) -> None:
    """强制删除目录：处理只读属性与杀软扫描锁，删除后校验，最多重试 3 次。

    FIXED(v1.6.0): 此前 rmtree(ignore_errors=True) 静默吞掉删除失败——
    Defender 锁定 MSVCP140.dll 等运行时 DLL 时目录删不干净，COLLECT 再往
    被锁定的现存文件里写就必现 PermissionError。
    """
    import stat
    import time

    def _onerror(func, p, _exc):
        try:
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except Exception:
            pass

    for attempt in range(1, 4):
        if not path.exists():
            return
        shutil.rmtree(path, onerror=_onerror)
        if not path.exists():
            return
        print(f"! 清理 {path} 未成功（第 {attempt}/3 次），1 秒后重试…")
        time.sleep(1)
    if path.exists():
        raise RuntimeError(f"无法清理 {path}——请手动删除后重试（可能有进程占用）")


def _find_pyinstaller() -> Path | None:
    """定位 pyinstaller 可执行文件。

    FIXED(v1.6.0): GitHub Actions hostedtoolcache 的 Python 不把 Scripts/
    加进 PATH，shutil.which 找不到 pip 装的 pyinstaller（本地 venv 布局
    不同所以从未暴露）。按 which > Scripts/ > 同目录 顺序探测。
    """
    which = shutil.which("pyinstaller")
    if which:
        return Path(which)
    exe_name = "pyinstaller.exe" if sys.platform == "win32" else "pyinstaller"
    py_dir = Path(sys.executable).parent
    candidates = [
        py_dir / "Scripts" / exe_name,          # venv / hostedtoolcache 标准布局
        py_dir.parent / "Scripts" / exe_name,   # hostedtoolcache 变体
        py_dir / exe_name,
    ]
    for c in candidates:
        if c.is_file():
            return c
    return None


def do_build() -> int:
    pyinstaller = _find_pyinstaller()
    if not pyinstaller:
        print("! pyinstaller 不可用：pip install pyinstaller pystray pillow")
        print(f"  (python: {sys.executable})")
        return 1
    # 清理旧产物，避免 COLLECT 残留旧文件混淆体积
    if APP_DIR.exists():
        print(f"+ 清理旧产物 {APP_DIR}")
        _force_clean_dir(APP_DIR)
    # FIXED(v1.6.0): Windows 上杀软实时扫描/句柄释放竞态会让 COLLECT 复制
    # 运行时 DLL（如 MSVCP140.dll）偶发 PermissionError，重试即可通过
    last_code = 1
    for attempt in range(1, 4):
        print(f"+ PyInstaller 构建（第 {attempt}/3 次）")
        last_code = run([pyinstaller, "protoforge.spec", "--noconfirm", "--distpath", str(DIST)])
        if last_code == 0 and (APP_DIR / "ProtoForge.exe").exists():
            return 0
        print(f"! 构建未成功（exit={last_code}），2 秒后重试…")
        import time
        time.sleep(2)
        if APP_DIR.exists():
            _force_clean_dir(APP_DIR)
    return last_code


def do_zip() -> tuple[Path | None, int]:
    if not (APP_DIR / "ProtoForge.exe").exists():
        print(f"! 未找到 {APP_DIR / 'ProtoForge.exe'}，请先构建")
        return None, 1
    version = get_version()
    zip_path = DIST / f"ProtoForge-v{version}-win64-portable.zip"
    if zip_path.exists():
        zip_path.unlink()
    print(f"+ 打包 {zip_path.name} ...")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for p in APP_DIR.rglob("*"):
            if p.is_file():
                zf.write(p, p.relative_to(APP_DIR.parent))
    size_mb = zip_path.stat().st_size / 1024 / 1024
    print(f"+ 便携包: {zip_path}  ({size_mb:.1f} MB)")
    if size_mb > MAX_ZIP_MB:
        print(f"! 超出规划验收线 {MAX_ZIP_MB}MB —— 检查是否混入了不必要的依赖")
    else:
        print(f"+ 体积验收通过（≤ {MAX_ZIP_MB}MB）")
    return zip_path, 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Build the ProtoForge Windows portable package")
    ap.add_argument("--no-zip", action="store_true", help="build only, skip the portable zip")
    ap.add_argument("--skip-build", action="store_true", help="skip PyInstaller, zip existing dist/ProtoForge")
    args = ap.parse_args()

    if not args.skip_build:
        code = do_build()
        if code != 0:
            return code
    if not args.no_zip:
        _, code = do_zip()
        return code
    return 0


if __name__ == "__main__":
    sys.exit(main())
