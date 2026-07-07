"""故障注入引擎包。

本包提供完整的工业设备故障注入系统，支持九种故障类型、
四种故障严重级别、故障传播链和通信故障检测。

模块结构:
  - ``models``:       故障数据模型 (Fault, FaultType, FaultSeverity)
  - ``injector``:     故障注入器 (FaultInjector)
  - ``propagation``:  故障传播链 (FaultPropagation)

向后兼容:
  本包同时 re-export 旧模块 ``protoforge.core.fault_injection`` 中的
  ``FaultConfig``、``TriggerMode``、``DeviceFailureException``、``FaultScenario``
  等，确保已有代码无需修改即可运行。

典型用法::

    from protoforge.core.fault import Fault, FaultType, FaultSeverity, FaultInjector

    injector = FaultInjector()
    injector.add_fault(Fault(
        fault_id="f1",
        fault_type=FaultType.SENSOR_STUCK,
        target="temperature",
        severity=FaultSeverity.HIGH,
        parameters={"stuck_value": 42.5},
    ))
    value, quality = injector.apply("temperature", 25.0)
    # value=42.5, quality="uncertain"
"""

from protoforge.core.fault.injector import FaultInjector
from protoforge.core.fault.models import Fault, FaultSeverity, FaultType
from protoforge.core.fault.propagation import FaultPropagation

# 向后兼容：re-export 旧模块的关键类型
from protoforge.core.fault_injection import (
    DeviceFailureException,
    FaultConfig,
    FaultScenario,
    TriggerMode,
)

__all__ = [
    # 新模型
    "Fault",
    "FaultType",
    "FaultSeverity",
    "FaultInjector",
    "FaultPropagation",
    # 向后兼容
    "FaultConfig",
    "TriggerMode",
    "DeviceFailureException",
    "FaultScenario",
]
