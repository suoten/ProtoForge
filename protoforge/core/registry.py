"""服务注册中心 — 轻量级服务定位器，消除模块间循环依赖。

传统模式中，子模块通过 ``from protoforge.main import get_engine`` 获取
全局单例，导致 ``main`` → ``core`` → ``main`` 的循环引用。

本模块提供了一个线程安全的注册中心：
- ``main.py`` 在启动时调用 ``register_engine(engine)`` 等注册服务
- 其他模块通过 ``get_engine()`` 等获取已注册的服务实例
- 注册中心不导入任何上层模块，彻底打破循环依赖链

使用示例::

    # main.py（应用入口）
    from protoforge.core.registry import register_engine
    register_engine(my_engine)

    # core/integration/manager.py（子模块）
    from protoforge.core.registry import get_engine
    engine = get_engine()  # 返回已注册的引擎，无循环依赖
"""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from protoforge.core.engine import SimulationEngine
    from protoforge.core.integration.manager import IntegrationManager
    from protoforge.core.log_bus import LogBus
    from protoforge.core.template import TemplateManager
    from protoforge.db.database import Database

logger = logging.getLogger(__name__)

_lock = threading.Lock()

_engine: SimulationEngine | None = None
_database: Database | None = None
_integration_manager: IntegrationManager | None = None
_log_bus: LogBus | None = None
_template_manager: TemplateManager | None = None


def register_engine(engine: SimulationEngine | None) -> None:
    """注册或注销仿真引擎实例。

    :param engine: 引擎实例，传入 ``None`` 表示注销
    """
    global _engine
    with _lock:
        _engine = engine
        if engine is not None:
            logger.debug("SimulationEngine registered in ServiceRegistry")


def register_database(database: Database | None) -> None:
    """注册或注销数据库实例。"""
    global _database
    with _lock:
        _database = database


def register_integration_manager(manager: IntegrationManager | None) -> None:
    """注册或注销集成管理器实例。"""
    global _integration_manager
    with _lock:
        _integration_manager = manager


def register_log_bus(log_bus: LogBus | None) -> None:
    """注册或注销日志总线实例。"""
    global _log_bus
    with _lock:
        _log_bus = log_bus


def register_template_manager(manager: TemplateManager | None) -> None:
    """注册或注销模板管理器实例。"""
    global _template_manager
    with _lock:
        _template_manager = manager


def get_engine() -> SimulationEngine:
    """获取已注册的仿真引擎实例。

    :return: 引擎实例
    :raises RuntimeError: 引擎未注册时抛出
    """
    if _engine is None:
        raise RuntimeError("Engine not initialized")
    return _engine


def get_database() -> Database:
    """获取已注册的数据库实例。

    :raises RuntimeError: 数据库未注册时抛出
    """
    if _database is None:
        raise RuntimeError("Database not initialized")
    return _database


def get_integration_manager() -> IntegrationManager:
    """获取已注册的集成管理器实例。

    :raises RuntimeError: 集成管理器未注册时抛出
    """
    if _integration_manager is None:
        raise RuntimeError("Integration manager not initialized")
    return _integration_manager


def get_log_bus() -> LogBus:
    """获取已注册的日志总线实例。

    :raises RuntimeError: 日志总线未注册时抛出
    """
    if _log_bus is None:
        raise RuntimeError("Log bus not initialized")
    return _log_bus


def get_template_manager() -> TemplateManager:
    """获取已注册的模板管理器实例。

    :raises RuntimeError: 模板管理器未注册时抛出
    """
    if _template_manager is None:
        raise RuntimeError("Template manager not initialized")
    return _template_manager


def clear_all() -> None:
    """注销所有已注册的服务（主要用于测试和关闭流程）。"""
    global _engine, _database, _integration_manager, _log_bus, _template_manager
    with _lock:
        _engine = None
        _database = None
        _integration_manager = None
        _log_bus = None
        _template_manager = None


__all__ = [
    "register_engine",
    "register_database",
    "register_integration_manager",
    "register_log_bus",
    "register_template_manager",
    "get_engine",
    "get_database",
    "get_integration_manager",
    "get_log_bus",
    "get_template_manager",
    "clear_all",
]
