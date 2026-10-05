"""ProtoForge 路径解析（开发 / PyInstaller 冻结 双模式）。

v1.6.0 桌面版的基础设施：
  - 冻结模式（PyInstaller onedir/onefile）：静态资源在 bundle 内
    （sys._MEIPASS，onedir 下即 _internal/），数据目录放在 exe 旁边
    ——"配置随目录走"，便携包解压即用；
  - 开发模式：一切相对仓库根，与既有行为完全一致。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def is_frozen() -> bool:
    """是否运行在 PyInstaller 打包环境。"""
    return getattr(sys, "frozen", False)


def bundle_dir() -> Path | None:
    """PyInstaller 解包目录（onedir 下为 _internal/，onefile 为临时目录）。

    只用于只读资源（前端静态文件等）；可写数据一律放 app_root()。
    """
    meipass = getattr(sys, "_MEIPASS", None)
    return Path(meipass) if meipass else None


def app_root() -> Path:
    """应用根目录：可写数据（data/、logs/、.env）的落点。

    冻结模式 = exe 所在目录（便携：配置随目录走）；
    开发模式 = 仓库根（protoforge/core/paths.py 上三级）。
    """
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent.parent


def static_dir() -> Path:
    """前端静态资源目录（web/dist）。

    解析顺序：PROTOFORGE_STATIC_DIR 环境变量 > bundle 内 web/dist >
    仓库根 web/dist（开发模式）。
    """
    env = os.environ.get("PROTOFORGE_STATIC_DIR", "")
    if env:
        return Path(env)
    candidates: list[Path] = []
    bundle = bundle_dir()
    if bundle is not None:
        candidates.append(bundle / "web" / "dist")
    if not is_frozen():
        candidates.append(app_root() / "web" / "dist")
    for c in candidates:
        if (c / "index.html").exists():
            return c
    # 都不存在时返回第一个候选（保持既有"目录缺失→警告降级"行为）
    return candidates[-1]
