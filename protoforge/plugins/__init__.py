"""ProtoForge 插件系统（v1.15.0）：协议插件 + 行业包的标准加载机制。

设计原则：
  - 容器开源：SDK、加载机制、manifest 格式全部开源（MIT），第三方可写；
  - 零侵入：插件通过既有注册管道注入（PROTOCOL_REGISTRY / PROTOCOL_DEFAULTS /
    TemplateManager），核心代码只加"加载"一个动作；
  - 两个来源：`data/plugins/<id>/plugin.json` 目录放置（用户/运维拷贝即用）
    与 setuptools entry_points `protoforge.plugins`（pip install 分发）；
  - 隔离失败：单个插件加载失败只记 warning 并在 /plugins API 中如实暴露，
    绝不拖垮主进程。

manifest（plugin.json）::

    {
      "id": "power-pack",
      "name": "电力行业包（基础）",
      "version": "1.0.0",
      "kind": "industry-pack",          // protocol | industry-pack
      "author": "...",
      "description": "电力行业设备模板与场景（免费基础版）",
      "protocols": [                     // 可选：插件自带协议
        {"name": "myproto",
         "server": "my_plugin.server:MyServer",   // module:Class，懒加载
         "defaults": {"host": "0.0.0.0", "port": 21000}}
      ],
      "templates": ["templates"],        // 可选：相对插件根的模板目录（子目录=协议分组）
      "scenarios": ["scenarios"]         // 可选：相对插件根的场景 JSON 目录（预留）
    }
"""

import json
import logging
from importlib.metadata import entry_points
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

MANIFEST_NAME = "plugin.json"
VALID_KINDS = {"protocol", "industry-pack", "template-pack"}

# data/plugins 相对 app_root；惰性解析避免 import 期副作用
_loaded_plugins: list[dict[str, Any]] = []
_load_errors: list[dict[str, str]] = []
_plugins_loaded = False


def _plugins_root() -> Path:
    try:
        from protoforge.core.paths import app_root
        # 与数据落点同源：<app_root>/data/plugins/<plugin-id>/plugin.json
        return Path(app_root()) / "data" / "plugins"
    except Exception:
        return Path("data") / "plugins"


def _parse_manifest(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        logger.warning("Plugin manifest unreadable: %s (%s)", path, e)
        return None
    pid = str(data.get("id", "")).strip()
    if not pid or str(data.get("kind", "")) not in VALID_KINDS:
        logger.warning("Plugin manifest missing id/kind: %s", path)
        return None
    data["_root"] = str(path.parent)
    return data


def _register_plugin(manifest: dict[str, Any]) -> dict[str, Any]:
    """把插件内容注入既有注册管道。失败抛异常由调用方隔离。"""
    root = Path(manifest["_root"])
    registered_protocols: list[str] = []

    # 1) 协议：塞进懒加载映射（module:Class 字符串，与内置协议同一条管道）
    from protoforge.protocols import _PROTOCOL_CLASSES, PROTOCOL_REGISTRY
    for spec in manifest.get("protocols") or []:
        name = str(spec.get("name", "")).strip()
        qual = str(spec.get("server", "")).strip()
        if not name or ":" not in qual:
            raise ValueError(f"protocol spec invalid: {spec!r}")
        if name in PROTOCOL_REGISTRY or name in _PROTOCOL_CLASSES:
            logger.warning("Plugin protocol %s shadows built-in/other plugin — skipped", name)
            continue
        _PROTOCOL_CLASSES[name] = qual
        registered_protocols.append(name)
        # 默认端口等配置并入 PROTOCOL_DEFAULTS（不覆盖内置条目）
        defaults = spec.get("defaults")
        if isinstance(defaults, dict):
            from protoforge.engine.defaults import PROTOCOL_DEFAULTS
            if name not in PROTOCOL_DEFAULTS:
                PROTOCOL_DEFAULTS[name] = defaults

    # 2) 模板目录：交给 TemplateManager 的额外目录加载（main.py 装配时调用）
    template_dirs = [str(root / d) for d in (manifest.get("templates") or [])]

    return {
        "id": manifest["id"],
        "name": manifest.get("name", manifest["id"]),
        "version": manifest.get("version", "0.0.0"),
        "kind": manifest.get("kind"),
        "description": manifest.get("description", ""),
        "author": manifest.get("author", ""),
        "source": manifest.get("_source", "dir"),
        "protocols": registered_protocols,
        "template_dirs": template_dirs,
    }


def _iter_dir_manifests(root: Path):
    if not root.is_dir():
        return
    for child in sorted(root.iterdir()):
        manifest_path = child / MANIFEST_NAME
        if manifest_path.is_file():
            manifest = _parse_manifest(manifest_path)
            if manifest:
                manifest["_source"] = "dir"
                yield manifest


def _iter_entrypoint_manifests():
    try:
        eps = entry_points(group="protoforge.plugins")
    except TypeError:  # Python <3.10 兼容签名
        eps = entry_points().get("protoforge.plugins", [])
    for ep in eps:
        try:
            obj = ep.load()
            manifest = dict(obj) if isinstance(obj, dict) else dict(obj.manifest())
            manifest.setdefault("id", ep.name)
            manifest["_source"] = "entry_point"
            yield manifest
        except Exception as e:  # 单个 entry_point 失败不拖垮其余
            _record_error(ep.name, "entry_point", f"{type(e).__name__}: {e}")


def _record_error(pid: str, source: str, error: str) -> None:
    _load_errors.append({"id": pid, "source": source, "error": error})
    logger.warning("Plugin %s (%s) failed to load: %s", pid, source, error)


def load_plugins() -> list[dict[str, Any]]:
    """发现并注册全部插件；幂等（重复调用直接返回缓存）。

    :return: 已成功加载的插件信息列表（供 /plugins API 与 CLI 展示）
    """
    global _plugins_loaded
    if _plugins_loaded:
        return list(_loaded_plugins)

    manifests: list[dict[str, Any]] = []
    manifests.extend(_iter_dir_manifests(_plugins_root()))
    manifests.extend(_iter_entrypoint_manifests())

    for manifest in manifests:
        pid = manifest.get("id", "?")
        try:
            info = _register_plugin(manifest)
            _loaded_plugins.append(info)
            logger.info("Plugin loaded: %s v%s (%s, protocols=%s)",
                        info["id"], info["version"], info["source"], info["protocols"])
        except Exception as e:
            _record_error(pid, manifest.get("_source", "?"), f"{type(e).__name__}: {e}")

    _plugins_loaded = True
    return list(_loaded_plugins)


def load_plugin_templates(template_manager: Any) -> int:
    """把已加载插件的模板目录交给 TemplateManager。返回加载的模板数。"""
    count = 0
    for plugin in load_plugins():
        for dir_path in plugin.get("template_dirs") or []:
            try:
                count += template_manager.load_extra_dir(Path(dir_path))
            except Exception as e:
                _record_error(plugin["id"], "templates", f"{type(e).__name__}: {e}")
    return count


def get_plugin_status() -> dict[str, Any]:
    """插件系统状态（/plugins API）。"""
    return {"plugins": load_plugins(), "errors": list(_load_errors)}
