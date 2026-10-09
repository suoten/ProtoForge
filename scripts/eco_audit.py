#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ProtoForge 生态审计脚本

全面扫描 GitHub / Gitee / Docker Hub，排查：
1. 全网同名仓库中是否有本项目（suoten/ProtoForge）的转载/衍生版
2. 官方仓库 fork 是否存在独立改动（ahead > 0）
3. 转载/衍生版是否保留 MIT LICENSE（未保留 = 可投诉下架的著作权侵权）
4. Docker Hub 第三方镜像是否为封装本项目代码的镜像

用法:
    python scripts/eco_audit.py            # 输出 Markdown 报告到 stdout
    python scripts/eco_audit.py -o report.md

无第三方依赖（仅 requests），可在任意装了 Python 3.9+ 的机器上运行。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone

import requests

OFFICIAL_GH = "suoten/ProtoForge"
OFFICIAL_GITEE = "suoten/ProtoForge"
OFFICIAL_DOCKER = "suoten/protoforge"
UA = {"User-Agent": "protoforge-eco-audit/1.0"}

# 已人工核实为合规的已知项（不告警），附原因备查
KNOWN_OK = {
    "lazycat-contrib/protoforge-lzcapp": "懒猫微服应用商店打包，manifest 引用官方镜像 suoten/protoforge，合规分发",
}

# 描述里出现这些关键词才算"与本项目相关"（撞名的无关项目直接忽略）
RELATED_HINTS = (
    "modbus", "opc", "plc", "工业", "协议仿真", "协议模拟", "网关通信",
    "上位机", "物联网协议", "s7", "bacnet", "iec", "fastapi", "测试上位机",
    "protoforge 工业协议", "工业协议仿真",
)


def related(text: str) -> bool:
    t = (text or "").lower()
    return any(k in t for k in RELATED_HINTS)


class RateLimited(Exception):
    pass


def gh_get(url: str, params: dict | None = None):
    headers = dict(UA)
    # 可选：设置 GITHUB_TOKEN 环境变量提升限流额度（匿名 60 次/小时，token 5000 次/小时）
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    r = requests.get(url, params=params or {}, headers=headers, timeout=30)
    if r.status_code == 403 and "rate limit" in r.text.lower():
        raise RateLimited("GitHub API 限流：设置 GITHUB_TOKEN 环境变量可提升额度，或稍后再跑")
    r.raise_for_status()
    return r.json()


def audit_github_namesakes() -> list[dict]:
    """GitHub 全网同名仓库（搜索默认排除 fork，正好筛独立仓库）"""
    print("== GitHub 全网同名仓库 ==", file=sys.stderr)
    out: list[dict] = []
    for page in (1, 2, 3):
        data = gh_get("https://api.github.com/search/repositories",
                      {"q": "protoforge in:name", "per_page": 100, "page": page})
        items = data.get("items", [])
        out.extend(items)
        if len(items) < 100:
            break
    risky = []
    for it in out:
        full = it.get("full_name", "")
        if full.lower() == OFFICIAL_GH.lower() or full in KNOWN_OK:
            continue
        desc = it.get("description") or ""
        lic = (it.get("license") or {}).get("spdx_id")
        if related(desc) or related(full):
            risky.append({
                "repo": full, "stars": it.get("stargazers_count", 0),
                "license": lic or "未标注", "pushed": (it.get("pushed_at") or "")[:10],
                "desc": desc[:80], "url": it.get("html_url"),
                "risk": "❌无LICENSE" if not lic or lic in ("NOASSERTION", "Other") else "✅",
            })
    print(f"  同名仓库 {len(out)} 个，其中与本项目领域相关 {len(risky)} 个", file=sys.stderr)
    return risky


def audit_github_forks() -> dict:
    """官方仓库 fork：找出有独立改动的（ahead > 0）"""
    print("== GitHub 官方仓库 fork ==", file=sys.stderr)
    forks: list[dict] = []
    for page in (1, 2, 3):
        data = gh_get(f"https://api.github.com/repos/{OFFICIAL_GH}/forks",
                      {"per_page": 100, "page": page, "sort": "stargazers"})
        forks.extend(data)
        if len(data) < 100:
            break
    divergent = []
    recent_cut = (datetime.now(timezone.utc) - timedelta(days=45)).strftime("%Y-%m-%d")
    active = [f for f in forks if (f.get("pushed_at") or "") >= recent_cut]
    for f in active:
        owner = f["full_name"]
        branch = f.get("default_branch", "master")
        try:
            cmp = gh_get(f"https://api.github.com/repos/{OFFICIAL_GH}/compare/master...{owner}:{branch}")
            if cmp.get("ahead_by", 0) > 0:
                divergent.append({"repo": owner, "ahead": cmp["ahead_by"],
                                  "url": f["html_url"]})
        except Exception as e:  # noqa: BLE001
            print(f"  比对 {owner} 失败: {e}", file=sys.stderr)
    print(f"  fork 总数 {len(forks)}，近期活跃 {len(active)}，有独立改动 {len(divergent)}", file=sys.stderr)
    return {"total": len(forks), "divergent": divergent}


def audit_gitee() -> list[dict]:
    """Gitee 同名仓库（搜索 API 需要令牌，改抓搜索页 HTML）"""
    print("== Gitee ==", file=sys.stderr)
    r = requests.get("https://gitee.com/search", params={"type": "repository", "q": "protoforge"},
                     headers=UA, timeout=30)
    r.raise_for_status()
    names = sorted(set(re.findall(r'href="https://gitee\.com/([^"/]+/[^"/]+)"', r.text)))
    names = [n for n in names if not n.startswith(("explore", "search", "login", "signup", "oauth",
                                                    "help", "about", "terms", "api", "static",
                                                    "assets", "gists", "enterprises", "topics",
                                                    "events", "organizations", "notifications"))]
    risky = []
    for name in names:
        if name.lower() == OFFICIAL_GITEE.lower():
            continue
        try:
            info = requests.get(f"https://gitee.com/api/v5/repos/{name}", headers=UA,
                                timeout=30).json()
            desc = info.get("description") or ""
            if not related(desc) and not related(name):
                continue
            risky.append({
                "repo": name, "stars": info.get("stargazers_count", 0),
                "is_fork": info.get("fork"), "license": info.get("license") or "未标注",
                "updated": (info.get("updated_at") or "")[:10], "desc": desc[:80],
                "url": f"https://gitee.com/{name}",
                "risk": "⚠️衍生版保留MIT" if info.get("license") else "❌无LICENSE标注",
            })
        except Exception as e:  # noqa: BLE001
            print(f"  查询 {name} 失败: {e}", file=sys.stderr)
    print(f"  同名仓库 {len(names)} 个，相关 {len(risky)} 个", file=sys.stderr)
    return risky


def _docker_token(scope: str) -> str:
    r = requests.get("https://auth.docker.io/token",
                     params={"service": "registry.docker.io", "scope": scope},
                     timeout=30)
    r.raise_for_status()
    return r.json()["token"]


def _inspect_image(repo: str, tag: str) -> dict | None:
    """读镜像 config blob，判断是否封装了本项目代码"""
    try:
        tok = _docker_token(f"repository:{repo}:pull")
        h = {"Authorization": f"Bearer {tok}"}
        m = requests.get(f"https://registry-1.docker.io/v2/{repo}/manifests/{tag}",
                         headers={**h, "Accept": "application/vnd.docker.distribution.manifest.v2+json"},
                         timeout=30).json()
        cfg = requests.get(f"https://registry-1.docker.io/v2/{repo}/blobs/{m['config']['digest']}",
                           headers=h, timeout=30).json()
        env = " ".join(cfg.get("config", {}).get("Env") or [])
        cmd = " ".join(cfg.get("config", {}).get("Cmd") or [])
        entry = " ".join(cfg.get("config", {}).get("Entrypoint") or [])
        hist = " ".join(x.get("created_by", "") for x in cfg.get("history", []))
        blob = f"{env} {cmd} {entry} {hist}".lower()
        # 启发式必须足够具体：只要命中本项目独有的运行特征才算封装镜像
        # （避免 CTF 题目里 flag{xxx_protoforge_xxx} 之类的撞名误报）
        markers = ("protoforge.cli", "protoforge/protocols", "protoforge -m",
                   "python -m protoforge", "uvicorn protoforge",
                   "protoforge_admin_password", "protoforge_jwt_secret",
                   "protoforge_db_path")
        return {
            "is_ours": any(k in blob for k in markers),
            "created": (cfg.get("created") or "")[:10], "cmd": cmd[:60],
        }
    except Exception as e:  # noqa: BLE001
        print(f"  检查镜像 {repo}:{tag} 失败: {e}", file=sys.stderr)
        return None


def audit_dockerhub() -> list[dict]:
    """Docker Hub 第三方镜像：只有确认封装了本项目代码的才算风险"""
    print("== Docker Hub ==", file=sys.stderr)
    r = requests.get("https://hub.docker.com/v2/search/repositories",
                     params={"query": "protoforge", "page_size": 50}, timeout=30)
    results = r.json().get("results", [])
    risky = []
    for it in results:
        repo = it.get("repo_name", "")
        if repo.lower() == OFFICIAL_DOCKER.lower():
            continue
        try:
            tags = requests.get(f"https://hub.docker.com/v2/repositories/{repo}/tags?page_size=5",
                                timeout=30).json().get("results", [])
            tag = (tags[0]["name"] if tags else "latest")
            info = _inspect_image(repo, tag)
            pull = it.get("pull_count", 0)
            if info and info["is_ours"]:
                risky.append({"repo": repo, "tag": tag, "pulls": pull,
                              "created": info["created"], "url": f"https://hub.docker.com/r/{repo}",
                              "risk": "❌疑似封装本项目代码的镜像"})
            else:
                print(f"  {repo}:{tag} -> 非本项目（cmd={info['cmd'] if info else '?'}），忽略", file=sys.stderr)
        except Exception as e:  # noqa: BLE001
            print(f"  检查 {repo} 失败: {e}", file=sys.stderr)
    print(f"  第三方镜像 {len(results) - 1} 个，疑似封装本项目的 {len(risky)} 个", file=sys.stderr)
    return risky


def main() -> None:
    ap = argparse.ArgumentParser(description="ProtoForge 生态审计")
    ap.add_argument("-o", "--output", help="报告输出到文件（默认 stdout）")
    args = ap.parse_args()

    namesakes: list[dict] = []
    forks: dict = {"total": "?", "divergent": []}
    try:
        namesakes = audit_github_namesakes()
    except RateLimited as e:
        print(f"  跳过: {e}", file=sys.stderr)
    try:
        forks = audit_github_forks()
    except RateLimited as e:
        print(f"  跳过: {e}", file=sys.stderr)
    gitee = audit_gitee()
    docker = audit_dockerhub()

    lines = [
        f"# ProtoForge 生态审计报告",
        f"",
        f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
        "## 结论",
        "",
    ]
    problems = [x for x in namesakes if x["risk"].startswith("❌")] + \
               [x for x in gitee if x["risk"].startswith("❌")] + docker
    if not problems:
        lines.append("✅ 未发现需要维权的目标（无删 LICENSE 的转载、无封装本项目代码的镜像）。")
    else:
        lines.append(f"⚠️ 发现 {len(problems)} 个疑似侵权目标，见下表，建议核实 LICENSE 去向并准备 DMCA/平台投诉。")
    lines += [
        "",
        f"## GitHub 官方仓库 fork",
        "",
        f"总数 {forks['total']}，其中**有独立改动**（ahead > 0，需人工核查）{len(forks['divergent'])} 个：",
        "",
    ]
    if forks["divergent"]:
        for d in forks["divergent"]:
            lines.append(f"- [{d['repo']}]({d['url']}) ahead={d['ahead']}")
    else:
        lines.append("- 无（全部为纯 fork，无独立改动）")
    for title, items in (("GitHub 同名/相关仓库", namesakes), ("Gitee 相关仓库", gitee),
                         ("Docker Hub 第三方镜像", docker)):
        lines += ["", f"## {title}", ""]
        if not items:
            lines.append("无相关项。")
            continue
        lines.append("| 仓库 | 风险标记 | License | Star | 更新 | 说明 |")
        lines.append("|------|---------|---------|------|------|------|")
        for x in items:
            lines.append(f"| [{x['repo']}]({x['url']}) | {x['risk']} | {x.get('license','-')} "
                         f"| {x.get('stars','-')} | {x.get('pushed') or x.get('updated') or x.get('created','-')} "
                         f"| {(x.get('desc') or '-')[:60]} |")
    report = "\n".join(lines) + "\n"

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"报告已写入 {args.output}", file=sys.stderr)
    else:
        print(report)


if __name__ == "__main__":
    main()
