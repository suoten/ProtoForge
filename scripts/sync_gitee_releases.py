"""GitHub Releases → Gitee 发行版 同步工具。

Gitee 的发行版（带附件与说明）不是 git 对象，git 推送/tag 不会带过去，
必须走 Gitee API 单独创建。本脚本做三件事：
  1. 按 tag 在 Gitee 查找/创建对应发行版（说明取自 GitHub Release 正文）；
  2. 检查附件是否已存在（幂等，重跑不重复上传）；
  3. 上传便携包 zip 附件。

用法（需要环境变量 GITEE_TOKEN，私人令牌，scope: projects）::
    python scripts/sync_gitee_releases.py --tag v1.17.0 \
        --asset dist/ProtoForge-v1.17.0-win64-portable.zip
    python scripts/sync_gitee_releases.py --all     # 回填全部历史 Release

CI 集成：desktop-release.yml 在 GitHub Release 发布后自动调用本脚本
（--tag + --asset），未配置 GITEE_TOKEN secret 时优雅跳过。
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

import httpx

GITHUB_REPO_DEFAULT = "suoten/ProtoForge"
GITEE_API = "https://gitee.com/api/v5"
GITHUB_API = "https://api.github.com"
ASSET_SUFFIX = "win64-portable.zip"


def _repo() -> str:
    return os.environ.get("GITHUB_REPOSITORY") or GITHUB_REPO_DEFAULT


def _token() -> str:
    tok = os.environ.get("GITEE_TOKEN", "").strip()
    if not tok:
        print("! 未配置 GITEE_TOKEN 环境变量，跳过 Gitee 同步")
        print("  创建私人令牌: https://gitee.com/profile/personal_access_tokens (scope: projects)")
        print("  配置位置: GitHub 仓库 Settings → Secrets and variables → Actions → New repository secret")
        sys.exit(0)
    return tok


def _headers_gh() -> dict:
    return {"Accept": "application/vnd.github+json", "User-Agent": "protoforge-sync"}


def find_gitee_release(client: httpx.Client, repo: str, tag: str, token: str):
    """按 tag 查找 Gitee 发行版；返回 release dict 或 None。"""
    resp = client.get(f"{GITEE_API}/repos/{repo}/releases/tags/{tag}",
                      params={"access_token": token})
    if resp.status_code != 200:
        return None
    data = resp.json()
    if isinstance(data, list):  # Gitee 对部分接口返回列表
        return data[0] if data else None
    return data


def create_gitee_release(client: httpx.Client, repo: str, tag: str,
                         name: str, body: str, token: str) -> dict:
    resp = client.post(f"{GITEE_API}/repos/{repo}/releases", json={
        "access_token": token,
        "tag_name": tag,
        "target_commitish": "master",  # Gitee 必填：发行版基于的分支
        "name": name or tag,
        "body": body or "",
        "prerelease": False,
    })
    resp.raise_for_status()
    data = resp.json()
    # 部分 Gitee 响应不含 id，回查一次
    if not data.get("id"):
        found = find_gitee_release(client, repo, tag, token)
        if found:
            return found
    return data


def existing_attachment_names(client: httpx.Client, repo: str,
                              release_id: int | str, token: str) -> set[str]:
    try:
        resp = client.get(f"{GITEE_API}/repos/{repo}/releases/{release_id}/attach_files",
                          params={"access_token": token})
        if resp.status_code == 200:
            return {a.get("name") or "" for a in resp.json()}
    except Exception as e:
        print(f"  ! 附件列表查询失败（继续上传）: {e}")
    return set()


def upload_attachment(client: httpx.Client, repo: str, release_id: int | str,
                      token: str, file_path: Path) -> None:
    with open(file_path, "rb") as f:
        resp = client.post(
            f"{GITEE_API}/repos/{repo}/releases/{release_id}/attach_files",
            data={"access_token": token},
            files={"file": (file_path.name, f, "application/zip")},
        )
    if resp.status_code == 400 and "配额" in resp.text:
        raise RuntimeError("Gitee 仓库附件总配额（免费版 1 GB）已用满，"
                           "请删除不再需要的旧版本附件后重试")
    resp.raise_for_status()


def ensure_gitee_release(client: httpx.Client, repo: str, tag: str, name: str,
                         body: str, asset_path: Path, token: str) -> str:
    """确保 Gitee 发行版存在且附件已上传；返回动作结果描述。"""
    release = find_gitee_release(client, repo, tag, token)
    if not release:
        print(f"+ Gitee 创建发行版 {tag} ...")
        release = create_gitee_release(client, repo, tag, name, body, token)
    else:
        print(f"+ Gitee 发行版 {tag} 已存在")
    rid = release.get("id")
    if not rid:
        return "! 未能取得 Gitee 发行版 id，附件未上传"

    names = existing_attachment_names(client, repo, rid, token)
    if asset_path.name in names:
        return f"= 附件 {asset_path.name} 已存在，跳过上传"
    upload_attachment(client, repo, rid, token, asset_path)
    return f"+ 附件 {asset_path.name} 上传完成"


def _mirror_prefix() -> str:
    """GitHub 附件下载镜像前缀（PROTOFORGE_UPDATE_MIRROR，如 ghproxy 类服务）。

    仅作用于"从 GitHub 下载资产"这一步（国内直连常慢到不可用）；
    上传到 Gitee 不受影响。
    """
    m = os.environ.get("PROTOFORGE_UPDATE_MIRROR", "").strip().rstrip("/")
    return m + "/" if m else ""


def sync_one(client: httpx.Client, gh_repo: str, gh_release: dict, token: str) -> None:
    tag = gh_release.get("tag_name") or ""
    if not tag.startswith("v"):
        print(f"- 跳过非 v 前缀发行版: {tag or '(空)'}")
        return
    asset = next((a for a in gh_release.get("assets") or []
                  if (a.get("name") or "").endswith(ASSET_SUFFIX)), None)
    if not asset:
        print(f"- {tag}: GitHub 发行版没有便携包附件，跳过")
        return

    print(f"=== 同步 {tag} ===")
    # 下载 GitHub 附件到临时目录（镜像前缀可选，国内直连常慢到不可用）
    url = asset["browser_download_url"]
    mirror = _mirror_prefix()
    if mirror:
        url = mirror + url
        print(f"+ 下载（经镜像 {mirror}）")
    else:
        print(f"+ 下载 {url}")
    tmp = Path(tempfile.gettempdir()) / asset["name"]
    # 缓存复用：上次运行已完整下载（大小一致）则跳过下载
    expected_size = asset.get("size") or 0
    if tmp.exists() and expected_size and tmp.stat().st_size == expected_size:
        print(f"  复用已下载缓存 {tmp.name} ({expected_size / 1024 / 1024:.1f} MB)")
    else:
        with httpx.stream("GET", url, headers=_headers_gh(), timeout=60,
                          follow_redirects=True) as resp:
            resp.raise_for_status()
            with open(tmp, "wb") as f:
                for chunk in resp.iter_bytes(1024 * 1024):
                    f.write(chunk)
    size_mb = tmp.stat().st_size / 1024 / 1024
    print(f"  已就绪 {size_mb:.1f} MB")

    result = ensure_gitee_release(client, _repo(), tag,
                                  gh_release.get("name") or tag,
                                  gh_release.get("body") or "",
                                  tmp, token)
    print(f"  {result}")
    tmp.unlink(missing_ok=True)


def version_key(tag: str) -> list[int]:
    parts: list[int] = []
    for seg in tag.strip().lstrip("vV").split("."):
        digits = ""
        for ch in seg:
            if ch.isdigit():
                digits += ch
            else:
                break
        parts.append(int(digits) if digits else 0)
    return parts


def download_with_retry(url: str, dest: Path, expected_size: int = 0,
                        attempts: int = 3) -> None:
    """下载文件，带整包重试与大小校验（Gitee 大附件偶发中断连接）。"""
    import time as _time
    for attempt in range(1, attempts + 1):
        try:
            with httpx.stream("GET", url, timeout=120, follow_redirects=True) as r:
                r.raise_for_status()
                with open(dest, "wb") as f:
                    for chunk in r.iter_bytes(1024 * 1024):
                        f.write(chunk)
            if expected_size and dest.stat().st_size != expected_size:
                raise RuntimeError(
                    f"size mismatch: got {dest.stat().st_size}, expect {expected_size}")
            return
        except Exception as e:
            if attempt == attempts:
                raise
            print(f"    下载中断（{type(e).__name__}: {str(e)[:80]}），重试 {attempt}/{attempts-1}")
            _time.sleep(3)


def list_gitee_releases(client: httpx.Client, repo: str, token: str) -> list[dict]:
    out: list[dict] = []
    page = 1
    while True:
        resp = client.get(f"{GITEE_API}/repos/{repo}/releases",
                          params={"access_token": token, "per_page": 100, "page": page})
        resp.raise_for_status()
        batch = resp.json()
        out += batch
        if len(batch) < 100:
            return out
        page += 1


def reorder_gitee_releases(client: httpx.Client, repo: str, token: str) -> None:
    """重建全部发行版为版本升序。

    Gitee 发行版列表按创建时间倒序排（最后创建的显示为最新）。
    若回填时未按版本升序创建，"最新发行版"会指向最老的版本——
    一键升级查询 Gitee releases/latest 也会拿错。此命令缓存全部
    附件（Gitee 国内直连，快）→ 删除全部发行版 → 按版本升序重建。
    """
    releases = list_gitee_releases(client, repo, token)
    print(f"+ Gitee 共 {len(releases)} 个发行版，开始重建（升序）...")

    # 1. 缓存全部附件到本地（Gitee 下载国内直连，快）
    stash: list[tuple[str, str, str, list[Path]]] = []
    stash_dir = Path(tempfile.gettempdir()) / "gitee_release_stash"
    stash_dir.mkdir(parents=True, exist_ok=True)
    for rel in releases:
        tag = rel.get("tag_name") or ""
        rid = rel.get("id")
        atts = client.get(f"{GITEE_API}/repos/{repo}/releases/{rid}/attach_files",
                          params={"access_token": token}).json()
        files: list[Path] = []
        for a in atts:
            url = a.get("browser_download_url") or ""
            dest = stash_dir / (a.get("name") or f"{tag}_{a.get('id')}.bin")
            if not (dest.exists() and a.get("size") and dest.stat().st_size == a["size"]):
                download_with_retry(url, dest, a.get("size") or 0)
            files.append(dest)
        stash.append((tag, rel.get("name") or tag, rel.get("body") or "", files))
        print(f"  已缓存 {tag}（{len(files)} 个附件）")

    # 2. 删除全部发行版
    for rel in releases:
        r = client.delete(f"{GITEE_API}/repos/{repo}/releases/{rel.get('id')}",
                          params={"access_token": token})
        print(f"  删除 {rel.get('tag_name')}: HTTP {r.status_code}")

    # 3. 按版本升序重建（最后创建 = 列表第一 = "最新发行版"）
    stash.sort(key=lambda x: version_key(x[0]))
    for tag, name, body, files in stash:
        rel = create_gitee_release(client, repo, tag, name, body, token)
        rid = rel.get("id")
        if not rid:
            found = find_gitee_release(client, repo, tag, token)
            rid = (found or {}).get("id")
        if not rid:
            print(f"  ! {tag}: 重建后未取得 id，附件未上传")
            continue
        for f in files:
            upload_attachment(client, repo, rid, token, f)
        print(f"+ 重建 {tag} 完成（{len(files)} 个附件）")


def main() -> int:
    ap = argparse.ArgumentParser(description="同步 GitHub Releases 到 Gitee 发行版")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--tag", help="只同步指定 tag（配合 --asset 本地文件）")
    g.add_argument("--all", action="store_true", help="回填：同步全部带便携包附件的 GitHub Release")
    g.add_argument("--reorder", action="store_true",
                   help="重建全部 Gitee 发行版为版本升序（修复'最新发行版'指向错误）")
    ap.add_argument("--asset", help="本地便携包 zip 路径（--tag 模式可选，省去下载）")
    args = ap.parse_args()

    token = _token()
    gh_repo = _repo()

    with httpx.Client(timeout=120) as client:
        if args.reorder:
            reorder_gitee_releases(client, _repo(), token)
            return 0

        if args.tag:
            tag = args.tag.lstrip("v")
            gh_url = f"{GITHUB_API}/repos/{gh_repo}/releases/tags/v{tag}"
            resp = client.get(gh_url, headers=_headers_gh())
            if resp.status_code != 200:
                print(f"! GitHub Release {args.tag} 不存在（HTTP {resp.status_code}）")
                return 1
            gh_release = resp.json()
            body = gh_release.get("body") or ""
            if args.asset:
                # 本地已有 zip：跳过下载
                asset_path = Path(args.asset)
                if not asset_path.exists():
                    print(f"! 本地文件不存在: {asset_path}")
                    return 1
                print(f"=== 同步 {args.tag}（本地资产 {asset_path.name}）===")
                release = find_gitee_release(client, _repo(), args.tag, token)
                if not release:
                    print(f"+ Gitee 创建发行版 {args.tag} ...")
                    release = create_gitee_release(client, _repo(), args.tag,
                                                   gh_release.get("name") or args.tag,
                                                   body, token)
                rid = release.get("id")
                if not rid:
                    print("! 未能取得 Gitee 发行版 id，附件未上传")
                    return 1
                names = existing_attachment_names(client, _repo(), rid, token)
                if asset_path.name in names:
                    print(f"= 附件 {asset_path.name} 已存在，跳过上传")
                else:
                    upload_attachment(client, _repo(), rid, token, asset_path)
                    print(f"+ 附件 {asset_path.name} 上传完成")
                return 0
            sync_one(client, gh_repo, gh_release, token)
            return 0

        # --all 回填
        resp = client.get(f"{GITHUB_API}/repos/{gh_repo}/releases?per_page=30",
                          headers=_headers_gh())
        resp.raise_for_status()
        releases = resp.json()
        print(f"+ GitHub 共 {len(releases)} 个 Release，逐个同步...")
        failed = 0
        for rel in releases:
            try:
                sync_one(client, gh_repo, rel, token)
            except Exception as e:
                failed += 1
                print(f"  ! {rel.get('tag_name')} 同步失败: {e}")
        print(f"完成，失败 {failed} 个")
        return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
