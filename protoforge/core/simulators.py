"""
设备仿真器注册表

根据 template_id 返回对应的仿真器实例（callable，注册为 post_tick_hook）。
新增仿真器时只需在 _REGISTRY 中添加映射即可，无需修改 engine。
"""

from typing import Any, Callable, Optional


def _build_registry() -> dict[str, Callable[[], Any]]:
    registry: dict[str, Callable[[], Any]] = {}
    try:
        from protoforge.protocols.mtconnect.lathe_simulator import LatheSimulator
        registry["mtconnect_lathe"] = LatheSimulator
    except ImportError:
        pass
    return registry


_REGISTRY = _build_registry()


def get_device_simulator(template_id: Optional[str]) -> Optional[Any]:
    """
    根据 template_id 返回一个新的仿真器实例，未匹配则返回 None。
    """
    if template_id is None:
        return None
    factory = _REGISTRY.get(template_id)
    if factory is None:
        return None
    return factory()
