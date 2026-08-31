"""Core foundation package: authentication and backward-compatible re-exports.

The former ``protoforge.core`` "catch-all" namespace has been split into
domain packages:

- ``protoforge.engine``        — simulation engine, devices, runtime services
- ``protoforge.simulation``    — scenarios, fault injection, behavior models
- ``protoforge.integrations``  — EdgeLite / forward / webhook integrations
- ``protoforge.observability`` — logging, metrics, audit, error monitoring

The imports below keep the historical public API working.
"""

from protoforge.engine.device import DeviceInstance
from protoforge.engine.engine import SimulationEngine
from protoforge.engine.registry import (
    get_database,
    get_engine,
    get_integration_manager,
    get_log_bus,
    get_template_manager,
)
from protoforge.protocols.base import DeviceBehavior, ProtocolServer
from protoforge.simulation.scenario import Scenario

__all__ = [
    "ProtocolServer",
    "DeviceBehavior",
    "SimulationEngine",
    "Scenario",
    "DeviceInstance",
    "get_engine",
    "get_database",
    "get_integration_manager",
    "get_log_bus",
    "get_template_manager",
]
