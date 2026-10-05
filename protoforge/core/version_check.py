"""ProtoForge 版本检查（GitHub Releases）。

v1.4.0 在 system_routes 里以内嵌方式实现了更新检查；v1.6.0 桌面模式也需要
同一逻辑（启动时托盘/控制台提示新版本），故提取为独立核心模块复用：
  - system_routes 的 /system/version-check 端点（带 10 分钟缓存 + 鉴权）
  - desktop 模式启动时的一次性检查（无鉴权、无缓存）

检查失败一律静默降级（check_failed=True），绝不影响主流程。
"""

from __future__ import annotations

import time
from typing import Any

# 与 Docker 部署文档一致的默认引导
RELEASES_URL = "https://github.com/suoten/ProtoForge/releases"
RELEASES_API = "https://api.github.com/repos/suoten/ProtoForge/releases/latest"
TAGS_API = "https://api.github.com/repos/suoten/ProtoForge/tags?per_page=1"


def is_newer(latest: str, current: str) -> bool:
    """宽松 semver 比较：逐段数值比较（v 前缀/多余后缀忽略），任何一段更大即更新。"""

    def parts(v: str) -> list[int]:
        out: list[int] = []
        for seg in v.strip().lstrip("vV").split("."):
            digits = ""
            for ch in seg:
                if ch.isdigit():
                    digits += ch
                else:
                    break
            out.append(int(digits) if digits else 0)
        return out

    a, b = parts(latest), parts(current)
    width = max(len(a), len(b))
    a += [0] * (width - len(a))
    b += [0] * (width - len(b))
    return a > b


async def fetch_release_info(current: str, timeout: float = 6.0) -> dict[str, Any]:
    """查询 GitHub 最新 Release，返回与 /system/version-check 相同结构的数据。

    无任何缓存与鉴权语义——调用方（API 端点 / 桌面模式）自行决定缓存策略。
    """
    import httpx

    data: dict[str, Any] = {
        "current": current,
        "latest": None,
        "update_available": False,
        "check_failed": False,
        "notes": "",
        "url": RELEASES_URL,
        "upgrade_command": "docker pull suoten/protoforge:latest",
    }
    try:
        async with httpx.AsyncClient(trust_env=False, timeout=timeout) as client:
            headers = {"Accept": "application/vnd.github+json", "User-Agent": "protoforge-update-check"}
            resp = await client.get(RELEASES_API, headers=headers)
            if resp.status_code == 200:
                release = resp.json()
                tag = release.get("tag_name") or ""
                latest = tag.lstrip("vV")
                data["latest"] = tag or None
                data["update_available"] = bool(latest) and is_newer(latest, current)
                data["notes"] = (release.get("body") or "")[:2000]
                data["url"] = release.get("html_url") or data["url"]
            elif resp.status_code == 404:
                # 仓库没有正式 Release：退化为取最新 tag
                tags_resp = await client.get(TAGS_API, headers=headers)
                if tags_resp.status_code == 200:
                    tags = tags_resp.json()
                    if tags:
                        tag = tags[0].get("name", "")
                        latest = tag.lstrip("vV")
                        data["latest"] = tag or None
                        data["update_available"] = bool(latest) and is_newer(latest, current)
                    else:
                        data["check_failed"] = True
                else:
                    data["check_failed"] = True
            else:
                data["check_failed"] = True
    except Exception:
        data["check_failed"] = True
    return data


class CachedReleaseChecker:
    """带 TTL 缓存的版本检查器（API 端点用，保持 v1.4.0 行为：10 分钟窗口）。"""

    def __init__(self, ttl_seconds: float = 600.0):
        self.ttl = ttl_seconds
        self._ts = 0.0
        self._data: dict[str, Any] | None = None

    async def check(self, current: str) -> dict[str, Any]:
        now = time.monotonic()
        if self._data is not None and now - self._ts < self.ttl:
            return self._data
        data = await fetch_release_info(current)
        self._ts = now
        self._data = data
        return data
