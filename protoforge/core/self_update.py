"""ProtoForge 一键升级（v1.17.0）。

三种安装形态三种升级路径（install_kind）：
- ``portable``（PyInstaller 便携包）：下载新便携 zip → 解压校验 → 生成
  update.ps1（放在程序目录外）→ 分离启动 → ps1 停旧进程 / 换目录 /
  保留 data/ → 重启新版本；
- ``pip``：后台执行 ``pip install -U protoforge-sim``，完成后提示重启服务；
- ``docker`` / ``source``：不提供一键升级，仅返回手动命令。

安全设计（对应"升级后不能用了"的担忧）：
- data/ 目录先移出再换包，换完立即移回；任何一步失败自动回滚到 .old；
- zip 先完整下载到本地并校验内部结构（必须含 ProtoForge/ProtoForge.exe），
  校验不过不动现有目录；
- 下载/解压全部发生在程序目录之外的暂存位置，中途断电不影响现有安装；
- 提示支持"跳过此版本"（data/update_prefs.json）——当前版本好用可以不升级，
  已跳过的版本不再弹横幅/托盘通知。

下载源优先级：Gitee 发行版附件（国内快）→ GitHub Release 资产 →
PROTOFORGE_UPDATE_MIRROR 环境变量配置的镜像前缀。
所有网络/文件异常一律静默降级为 failed 状态，绝不影响主服务。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import subprocess
import sys
import threading
import zipfile
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

GITEE_RELEASE_API = "https://gitee.com/api/v5/repos/suoten/ProtoForge/releases/latest"
ASSET_NAME_TEMPLATE = "ProtoForge-v{version}-win64-portable.zip"
ZIP_ROOT = "ProtoForge"  # build_desktop.py 打包根目录名
MIRROR_ENV = "PROTOFORGE_UPDATE_MIRROR"  # 例: https://ghproxy.cn/

_CREATE_DETACHED = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP


# ---------------------------------------------------------------------------
# 安装形态识别
# ---------------------------------------------------------------------------

def install_kind() -> str:
    """当前安装形态: portable / pip / docker / source。"""
    if os.environ.get("PF_DOCKER") == "1" or Path("/.dockerenv").exists():
        return "docker"
    if getattr(sys, "frozen", False):
        return "portable"
    try:
        pkg_dir = Path(__file__).resolve().parent.parent.parent
        if pkg_dir.parent.name == "site-packages":
            return "pip"
    except (OSError, ValueError):
        pass
    return "source"


def can_one_click() -> bool:
    return install_kind() in ("portable", "pip")


# ---------------------------------------------------------------------------
# "跳过此版本"偏好（当前版本好用可以不升级）
# ---------------------------------------------------------------------------

def _prefs_path() -> Path:
    from protoforge.core.paths import app_root
    return app_root() / "data" / "update_prefs.json"


def get_dismissed_version() -> str | None:
    try:
        return json.loads(_prefs_path().read_text(encoding="utf-8")).get("dismissed_version")
    except Exception:
        return None


def set_dismissed_version(version: str | None) -> None:
    """记录/清除跳过的版本（version=None 清除）。"""
    path = _prefs_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if version is None:
            path.unlink(missing_ok=True)
        else:
            path.write_text(json.dumps({"dismissed_version": str(version)}, ensure_ascii=False),
                            encoding="utf-8")
    except Exception as e:  # 偏好写失败不影响主流程
        logger.debug("set_dismissed_version ignored: %s", e)


# ---------------------------------------------------------------------------
# 升级状态机（模块级单例，路由层轮询读取）
# ---------------------------------------------------------------------------

_state: dict[str, Any] = {
    "state": "idle",            # idle/downloading/downloaded/applying/ready/failed
    "target_version": None,
    "progress": 0.0,            # 0-100
    "downloaded": 0,
    "total": None,
    "source": None,             # gitee/github/mirror
    "error": None,
    "message": "",
    "install_kind": install_kind(),
}
_lock = threading.Lock()
_download_task: asyncio.Task | None = None


def get_state() -> dict[str, Any]:
    with _lock:
        return dict(_state)


def _set_state(**kwargs: Any) -> None:
    with _lock:
        _state.update(kwargs)


# ---------------------------------------------------------------------------
# 下载源解析
# ---------------------------------------------------------------------------

def _mirror_prefix() -> str:
    return os.environ.get(MIRROR_ENV, "").strip().rstrip("/") + "/" \
        if os.environ.get(MIRROR_ENV, "").strip() else ""


async def find_portable_asset(version: str) -> tuple[str, str] | None:
    """返回 (下载 URL, 来源标签)；Gitee 附件优先 → GitHub 资产 → 镜像前缀。

    version 为不带 v 前缀的版本号。
    """
    import httpx

    asset_name = ASSET_NAME_TEMPLATE.format(version=version)
    headers = {"User-Agent": "protoforge-self-update"}

    # 1) Gitee 发行版附件（国内直连快）
    try:
        async with httpx.AsyncClient(trust_env=False, timeout=10) as client:
            resp = await client.get(GITEE_RELEASE_API, headers=headers)
            if resp.status_code == 200:
                tag = (resp.json().get("tag_name") or "").lstrip("vV")
                if tag == version:
                    for a in resp.json().get("assets") or []:
                        name = a.get("name") or ""
                        url = a.get("browser_download_url") or ""
                        if name == asset_name and url.startswith("http"):
                            return url, "gitee"
    except Exception as e:
        logger.debug("gitee release lookup ignored: %s", e)

    # 2) GitHub Release 资产
    from protoforge.core.version_check import RELEASES_API
    gh_url = f"https://github.com/suoten/ProtoForge/releases/download/v{version}/{asset_name}"
    try:
        async with httpx.AsyncClient(trust_env=False, timeout=10) as client:
            resp = await client.get(RELEASES_API, headers=headers)
            if resp.status_code == 200:
                release = resp.json()
                tag = (release.get("tag_name") or "").lstrip("vV")
                if tag == version:
                    for a in release.get("assets") or []:
                        if (a.get("name") or "") == asset_name:
                            url = a.get("browser_download_url") or gh_url
                            if _mirror_prefix():
                                return _mirror_prefix() + url, "mirror"
                            return url, "github"
    except Exception as e:
        logger.debug("github release lookup ignored: %s", e)

    # 3) 配置了镜像时按约定 URL 直下（未联网校验，交给下载阶段报错）
    if _mirror_prefix():
        return _mirror_prefix() + gh_url, "mirror"
    return None


# ---------------------------------------------------------------------------
# 下载 → 校验 → 解压 → 生成换目录脚本
# ---------------------------------------------------------------------------

def _work_dir() -> Path:
    from protoforge.core.paths import app_root
    return app_root().parent  # 程序目录的同级（换目录操作要求同卷）


def _zip_path() -> Path:
    return _work_dir() / f"{ZIP_ROOT}-update.zip"


def _staging_dir() -> Path:
    return _work_dir() / f"{ZIP_ROOT}.new"


def _verify_zip(zip_path: Path) -> bool:
    """校验 zip 结构：根目录下必须有 ProtoForge/ProtoForge.exe。"""
    try:
        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
            if f"{ZIP_ROOT}/ProtoForge.exe" not in names:
                return False
            # 防 zip-slip：所有条目不得逃出根目录
            for n in names:
                if n.startswith("/") or ".." in Path(n).parts or (n and n[1:3] == ":\\"):
                    return False
            return True
    except Exception as e:
        logger.warning("self update zip verify failed: %s", e)
        return False


async def download_and_stage(version: str) -> None:
    """后台任务：下载 → 校验 → 解压到 <app>.new → 生成换目录脚本 → ready。"""
    try:
        found = await find_portable_asset(version)
        if not found:
            raise RuntimeError(f"v{version} 的便携包资产未找到（发行版可能还没出包）")
        url, source = found
        _set_state(state="downloading", target_version=version, source=source,
                   progress=0.0, downloaded=0, total=None, error=None,
                   message=f"正在从 {source} 下载 v{version} 便携包")

        import httpx
        zip_path = _zip_path()
        zip_path.parent.mkdir(parents=True, exist_ok=True)
        got = 0
        async with httpx.AsyncClient(trust_env=False, timeout=30, follow_redirects=True) as client:
            async with client.stream("GET", url) as resp:
                if resp.status_code != 200:
                    raise RuntimeError(f"下载失败: HTTP {resp.status_code}")
                total = int(resp.headers.get("Content-Length") or 0) or None
                _set_state(total=total)
                with open(zip_path, "wb") as f:
                    async for chunk in resp.aiter_bytes(256 * 1024):
                        f.write(chunk)
                        got += len(chunk)
                        pct = (got / total * 100.0) if total else 0.0
                        _set_state(downloaded=got, total=total, progress=round(pct, 1))
        if not _verify_zip(zip_path):
            zip_path.unlink(missing_ok=True)
            raise RuntimeError("下载的包结构校验未通过（缺少 ProtoForge.exe 或包含可疑路径）")

        # 解压到暂存目录 <app>.new
        staging = _staging_dir()
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(staging)
        if not (staging / ZIP_ROOT / "ProtoForge.exe").exists():
            raise RuntimeError("解压后未找到 ProtoForge.exe")
        zip_path.unlink(missing_ok=True)

        # 生成换目录脚本（放在程序目录的同级，脚本自身不被换掉）
        ps1 = _write_update_ps1(version)
        _set_state(state="ready", progress=100.0, message="新版本已就绪，应用后将自动重启",
                   error=None, ps1=str(ps1))
    except Exception as e:
        logger.warning("self update download failed: %s", e)
        _set_state(state="failed", error=str(e), message="升级准备失败，当前版本未受影响")
        _cleanup_staging()


def _cleanup_staging() -> None:
    shutil.rmtree(_staging_dir(), ignore_errors=True)
    _zip_path().unlink(missing_ok=True)


def _write_update_ps1(version: str) -> Path:
    """生成换目录 PowerShell 脚本（UTF-8 BOM，中文路径安全）。"""
    from protoforge.core.paths import app_root
    app = app_root()
    ps1 = app.parent / f"{ZIP_ROOT.lower()}_update_v{version}.ps1"
    # 注意: data 目录在 exe 旁边（便携"配置随目录走"），换目录时必须保留
    script = f"""$ErrorActionPreference = 'Stop'
$log  = '{app.parent / (ZIP_ROOT.lower() + "_update.log")}'
$cur  = '{app}'
$new  = '{app}.new'
$old  = '{app}.old'
$dataBak = '{app}.data.bak'
function Log($m) {{ Add-Content -Path $log -Value ("[" + (Get-Date -Format 'HH:mm:ss') + '] ' + $m) }}
try {{
    Log "=== self update to v{version} start ==="
    if (-not (Test-Path "$new\\ProtoForge.exe")) {{ throw "staging incomplete: ProtoForge.exe missing" }}
    # 1. data 目录先移出（任何失败都不碰旧安装）
    if (Test-Path "$cur\\data") {{ Move-Item "$cur\\data" $dataBak -Force }}
    # 2. 停止当前进程（本脚本已与响应解耦）
    Get-Process '{ZIP_ROOT}' -ErrorAction SilentlyContinue | Stop-Process -Force
    Start-Sleep -Seconds 1
    # 3. 换目录
    if (Test-Path $old) {{ Remove-Item $old -Recurse -Force }}
    Rename-Item $cur $old
    Rename-Item $new $cur
    # 4. data 移回
    if (Test-Path $dataBak) {{ Move-Item $dataBak "$cur\\data" }}
    if (-not (Test-Path "$cur\\ProtoForge.exe")) {{ throw "swap failed: exe missing after swap" }}
    # 5. 重启
    Start-Process -FilePath "$cur\\ProtoForge.exe" -WorkingDirectory $cur
    Log "update finished OK"
}} catch {{
    Log ("FAILED: " + $_.Exception.Message)
    # 回滚：新目录已顶上则换回旧的
    if ((Test-Path $old) -and (-not (Test-Path "$cur\\ProtoForge.exe"))) {{
        if (Test-Path $cur) {{ Remove-Item $cur -Recurse -Force -ErrorAction SilentlyContinue }}
        Rename-Item $old $cur
    }}
    if ((Test-Path $dataBak) -and (-not (Test-Path "$cur\\data"))) {{
        Move-Item $dataBak "$cur\\data" -Force -ErrorAction SilentlyContinue
    }}
    if (Test-Path $new) {{ Remove-Item $new -Recurse -Force -ErrorAction SilentlyContinue }}
    try {{ Start-Process -FilePath "$cur\\ProtoForge.exe" -WorkingDirectory $cur }} catch {{}}
    Log "rolled back to previous version"
}}
"""
    ps1.write_text(script, encoding="utf-8-sig")
    return ps1


def apply_portable_update() -> dict[str, Any]:
    """分离启动换目录脚本；2 秒后脚本停进程换包重启（响应已先行返回）。"""
    if sys.platform != "win32":
        raise RuntimeError("便携包一键升级仅支持 Windows")
    st = get_state()
    if st["state"] != "ready":
        raise RuntimeError(f"当前状态不可应用升级: {st['state']}")
    ps1 = Path(st["ps1"])
    if not ps1.exists():
        raise RuntimeError("升级脚本不存在，请重新下载")
    _set_state(state="applying", message="正在切换到新版本，服务将自动重启")
    subprocess.Popen(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ps1)],
        creationflags=_CREATE_DETACHED, close_fds=True,
        cwd=str(ps1.parent),
    )
    return {"ok": True, "message": "升级脚本已启动，服务将在数秒内自动重启"}


# ---------------------------------------------------------------------------
# pip 安装形态
# ---------------------------------------------------------------------------

async def pip_upgrade() -> None:
    """后台 pip 升级 protoforge-sim（仅 pip 形态）。"""
    try:
        _set_state(state="downloading", message="正在通过 pip 升级 protoforge-sim",
                   progress=0.0, error=None)
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "pip", "install", "-U", "protoforge-sim",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=600)
        if proc.returncode == 0:
            _set_state(state="ready", progress=100.0,
                       message="pip 升级完成，请重启 ProtoForge 服务生效",
                       error=None, ps1=None)
        else:
            raise RuntimeError(f"pip 退出码 {proc.returncode}: {(out or b'')[-500:].decode(errors='replace')}")
    except Exception as e:
        logger.warning("pip upgrade failed: %s", e)
        _set_state(state="failed", error=str(e), message="pip 升级失败，当前版本未受影响")


def start_download(version: str) -> dict[str, Any]:
    """入口：按安装形态启动后台升级准备任务。"""
    global _download_task
    with _lock:
        if _state["state"] in ("downloading", "applying"):
            raise RuntimeError(f"升级正在进行中（{_state['state']}），请稍候")
    kind = install_kind()
    if kind == "docker":
        raise RuntimeError("Docker 部署请使用 docker pull suoten/protoforge:latest 升级")
    if kind == "source":
        raise RuntimeError("源码运行请 git pull 后重启升级")
    _set_state(state="downloading", target_version=version, error=None, message="")
    if kind == "portable":
        _download_task = asyncio.create_task(download_and_stage(version))
    else:
        _download_task = asyncio.create_task(pip_upgrade())
    return {"ok": True, "kind": kind, "version": version}
