"""ProtoForge 统一异常类型定义

所有 ProtoForge 内部异常都应该继承自 ProtoForgeError。
这有助于统一错误处理和日志记录。
"""

from typing import Any


class ProtoForgeError(Exception):
    """ProtoForge 基础异常类"""

    def __init__(self, message: str = "", detail: Any = None):
        super().__init__(message)
        self.message = message
        self.detail = detail

    def __str__(self) -> str:
        if self.detail:
            return f"{self.message}: {self.detail}"
        return self.message

    def to_dict(self) -> dict[str, Any]:
        return {
            "error_type": self.__class__.__name__,
            "message": self.message,
            "detail": self.detail,
        }


# ============ 设备相关异常 ============

class DeviceError(ProtoForgeError):
    """设备基础异常"""
    pass


class DeviceNotFoundError(DeviceError):
    """设备不存在"""

    def __init__(self, device_id: str):
        super().__init__(f"Device not found: {device_id}")
        self.device_id = device_id


class DeviceAlreadyExistsError(DeviceError):
    """设备已存在"""

    def __init__(self, device_id: str):
        super().__init__(f"Device already exists: {device_id}")
        self.device_id = device_id


class DeviceCreationError(DeviceError):
    """设备创建失败"""
    pass


class DevicePushError(DeviceError):
    """设备推送失败"""

    def __init__(self, device_id: str, reason: str, suggestion: str = ""):
        super().__init__(f"Failed to push device {device_id}: {reason}")
        self.device_id = device_id
        self.reason = reason
        self.suggestion = suggestion

    def to_dict(self) -> dict[str, Any]:
        base = super().to_dict()
        base.update({
            "device_id": self.device_id,
            "reason": self.reason,
            "suggestion": self.suggestion,
        })
        return base


# ============ 协议相关异常 ============

class ProtocolError(ProtoForgeError):
    """协议基础异常"""
    pass


class ProtocolNotFoundError(ProtocolError):
    """协议不存在"""

    def __init__(self, protocol_name: str):
        super().__init__(f"Protocol not found: {protocol_name}")
        self.protocol_name = protocol_name


class ProtocolNotRunningError(ProtocolError):
    """协议服务器未运行"""

    def __init__(self, protocol_name: str, status: str = ""):
        msg = f"Protocol {protocol_name} is not running"
        if status:
            msg += f" (status: {status})"
        super().__init__(msg)
        self.protocol_name = protocol_name
        self.status = status


class ProtocolStartError(ProtocolError):
    """协议启动失败"""

    def __init__(self, protocol_name: str, reason: str):
        super().__init__(f"Failed to start protocol {protocol_name}: {reason}")
        self.protocol_name = protocol_name
        self.reason = reason


class PortConflictError(ProtocolError):
    """端口冲突"""

    def __init__(self, protocol_name: str, port: int, suggestion: str = ""):
        super().__init__(
            f"Port {port} is already in use for protocol {protocol_name}",
            detail={"port": port, "protocol": protocol_name}
        )
        self.protocol_name = protocol_name
        self.port = port
        self.suggestion = suggestion or f"Try a different port or stop the service using port {port}"


# ============ 集成相关异常 ============

class IntegrationError(ProtoForgeError):
    """集成基础异常"""
    pass


class EdgeLiteConnectionError(IntegrationError):
    """EdgeLite 连接失败"""

    def __init__(self, url: str, reason: str = ""):
        msg = f"Cannot connect to EdgeLite at {url}"
        if reason:
            msg += f": {reason}"
        super().__init__(msg)
        self.url = url
        self.reason = reason


class EdgeLiteAuthError(IntegrationError):
    """EdgeLite 认证失败"""

    def __init__(self, reason: str = ""):
        super().__init__(f"EdgeLite authentication failed: {reason}" if reason else "EdgeLite authentication failed")
        self.reason = reason


class ChannelError(IntegrationError):
    """通信通道错误"""
    pass


# ============ 配置相关异常 ============

class ConfigurationError(ProtoForgeError):
    """配置错误"""

    def __init__(self, key: str, reason: str = ""):
        msg = f"Configuration error for '{key}'"
        if reason:
            msg += f": {reason}"
        super().__init__(msg)
        self.key = key
        self.reason = reason


class ValidationError(ProtoForgeError):
    """数据验证失败"""

    def __init__(self, field: str, reason: str = ""):
        msg = f"Validation failed for '{field}'"
        if reason:
            msg += f": {reason}"
        super().__init__(msg)
        self.field = field
        self.reason = reason


# ============ 数据库相关异常 ============

class DatabaseError(ProtoForgeError):
    """数据库操作失败"""
    pass


class PersistenceError(DatabaseError):
    """数据持久化失败"""
    pass


# ============ 场景相关异常 ============

class ScenarioError(ProtoForgeError):
    """场景基础异常"""
    pass


class ScenarioNotFoundError(ScenarioError):
    """场景不存在"""

    def __init__(self, scenario_id: str):
        super().__init__(f"Scenario not found: {scenario_id}")
        self.scenario_id = scenario_id


class ScenarioExecutionError(ScenarioError):
    """场景执行失败"""
    pass


# ============ 工具函数 ============

def is_protoforge_error(e: Exception) -> bool:
    """判断是否为 ProtoForge 异常"""
    return isinstance(e, ProtoForgeError)


def get_error_code(e: Exception) -> str:
    """获取错误的代码标识"""
    if isinstance(e, ProtoForgeError):
        return e.__class__.__name__
    return "UnknownError"
