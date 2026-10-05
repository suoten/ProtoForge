# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the ProtoForge Windows desktop build (v1.6.0).

Build (from repo root, with the project venv active):
    pyinstaller protoforge.spec

Output: dist/ProtoForge/  (onedir — fast startup; zip it for the portable
package via scripts/build_desktop.py)

Layout decisions:
  - onedir over onefile: 2-second start vs ~30s one-file extraction, and far
    fewer antivirus false positives; the portable zip keeps "double-click" UX.
  - datas:
      web/dist            -> web/dist           (frontend, resolved via core.paths)
      protoforge/templates-> protoforge/templates (device templates, JSON)
  - hiddenimports: protocol extras + uvicorn dynamic pieces that static
    analysis cannot see.
"""

import os
from pathlib import Path

block_cipher = None
ROOT = os.path.abspath(".")

# FIXED(v1.6.0): 协议注册表按字符串动态 import 协议模块，静态分析收不全
# （首跑只有 modbus 进包，其余 27 个协议 "No module named"）。
# 不用 collect_submodules（其枚举在 spec 环境不完整），直接文件系统枚举
# protoforge/protocols 与其余含动态导入的子包，确定性列出全部子模块。
def _pkg_submodules(pkg_dir: str) -> list[str]:
    """pkg_dir 下所有 .py 与子包 → 'protoforge.xxx.yyy' 模块名列表。"""
    names = []
    base = Path(ROOT) / "protoforge" / pkg_dir
    for entry in sorted(base.iterdir()):
        if entry.is_file() and entry.suffix == ".py" and entry.stem != "__init__":
            names.append(f"protoforge.{pkg_dir}.{entry.stem}")
        elif entry.is_dir() and (entry / "__init__.py").exists():
            pkg = f"protoforge.{pkg_dir}.{entry.name}"
            names.append(pkg)
            for f in sorted(entry.glob("*.py")):
                if f.stem != "__init__":
                    names.append(f"{pkg}.{f.stem}")
    return names


protoforge_dynamic = (
    _pkg_submodules("protocols")
    + _pkg_submodules("integrations")
    + _pkg_submodules("api")
    + _pkg_submodules("core")
    + _pkg_submodules("engine")
    + _pkg_submodules("testing")
    + _pkg_submodules("audit")
    + _pkg_submodules("observability")
    + _pkg_submodules("simulation")
)


def _collect_templates():
    """Collect protoforge/templates/<proto>/*.json preserving the layout
    engine/template.py expects (package_dir/templates)."""
    out = []
    tpl_root = Path(ROOT) / "protoforge" / "templates"
    out.append((str(tpl_root), "protoforge/templates"))
    return out


def _collect_web_dist():
    dist = Path(ROOT) / "web" / "dist"
    if not (dist / "index.html").exists():
        raise SystemExit(
            "web/dist not found - build the frontend first: cd web && npm install && npm run build"
        )
    return [(str(dist), "web/dist")]


datas = _collect_templates() + _collect_web_dist()

hiddenimports = [
    # --- uvicorn dynamic pieces ---
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.loops.asyncio",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.protocols.websockets.websockets_impl",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    "websockets",
    # --- DB / migrations ---
    "aiosqlite",
    "sqlalchemy",
    "sqlalchemy.dialects.sqlite",
    "sqlalchemy.ext.asyncio",
    "greenlet",
    "alembic",
    "mako",
    # --- HTTP client (update check / forwarders) ---
    "httpx",
    "httpcore",
    "anyio._backends._asyncio",
    # --- protocol extras (match [all]) ---
    "pymodbus",
    "asyncua",
    "amqtt",
    "amqtt.broker",
    "amqtt.client",
    # --- desktop shell (optional extras, present in the build venv) ---
    "pystray",
    "PIL",
    "PIL.ImageDraw",
    # --- CLI entry ---
    "protoforge.cli",
] + protoforge_dynamic

a = Analysis(
    [os.path.join(ROOT, "scripts", "desktop_entry.py")],
    pathex=[ROOT],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "matplotlib",
        "numpy",
        "pandas",
        "pytest",
        "PyQt5",
        "PyQt6",
        "PySide2",
        "PySide6",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ProtoForge",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,  # keep a console window: first-run admin password is printed there
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name="ProtoForge",
)
