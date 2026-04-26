"""联调集成数据模型"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class MessageType(str, Enum):
    HANDSHAKE = "handshake"
    HANDSHAKE_ACK = "handshake_ack"
    HEARTBEAT = "heartbeat"
    HEARTBEAT_ACK = "heartbeat_ack"
    PUSH_DEVICE = "push_device"
    PUSH_DEVICE_ACK = "push_device_ack"
    DEVICE_CONTROL = "device_control"
    DELETE_DEVICE = "delete_device"
    DEVICE_STATUS_CHANGED = "device_status_changed"
    DEVICE_FAULT = "device_fault"
    POINT_DATA = "point_data"
    ALARM_FIRED = "alarm_fired"
    ALARM_RECOVERED = "alarm_recovered"
    BATCH_PUSH = "batch_push"
    BATCH_PUSH_ACK = "batch_push_ack"
    ERROR = "error"


class IntegrationMessage(BaseModel):
    version: str = "1.0"
    type: str
    id: str = Field(default_factory=lambda: __import__("uuid").uuid4().hex[:16])
    timestamp: float = Field(default_factory=lambda: __import__("time").time())
    source: str = "protoforge"
    payload: dict[str, Any] = {}


class HandshakeRequest(BaseModel):
    version: str = "1.0"
    protocols: list[str] = []
    capabilities: list[str] = []
    heartbeat_interval: float = 30.0


class HandshakeResponse(BaseModel):
    version: str = "1.0"
    protocols: list[str] = []
    capabilities: list[str] = []
    session_id: str = ""


class BackhaulConfig(BaseModel):
    enabled: bool = False
    device_filter: list[str] = Field(default_factory=list)
    point_filter: list[str] = Field(default_factory=list)
    change_threshold: float = 0.0
    rate_limit: float = 10.0
    buffer_size: int = 1000


class ChannelConfig(BaseModel):
    type: Literal["http", "websocket"] = "http"
    url: str = ""
    heartbeat_interval: float = 30.0
    reconnect_delay: float = 5.0
    max_reconnect_delay: float = 60.0


class IntegrationConfig(BaseModel):
    enabled: bool = False
    edgelite_url: str = ""
    username: str = "admin"
    password: str = ""
    channel: ChannelConfig = Field(default_factory=ChannelConfig)
    backhaul: BackhaulConfig = Field(default_factory=BackhaulConfig)


class ProtocolMappingResultModel(BaseModel):
    status: str
    protoforge_protocol: str
    edgelite_protocol: str | None = None
    warning: str = ""


class DataTypeMappingResultModel(BaseModel):
    status: str
    source_type: str
    target_type: str
    degraded: bool = False
    warning: str = ""


class CompatibilityReportModel(BaseModel):
    device_id: str = ""
    compatible: bool = True
    protocol_result: ProtocolMappingResultModel = Field(default_factory=ProtocolMappingResultModel)
    data_type_results: list[DataTypeMappingResultModel] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class BatchPushRequest(BaseModel):
    device_ids: list[str] = []
    protocol: str = ""
    concurrency: int = Field(default=10, ge=1, le=50)


class BatchPushResult(BaseModel):
    total: int = 0
    success: int = 0
    failure: int = 0
    ok: bool = False
    details: list[dict[str, Any]] = Field(default_factory=list)


class AlarmReactionRule(BaseModel):
    id: str = Field(default_factory=lambda: __import__("uuid").uuid4().hex[:12])
    source_device_id: str = ""
    alarm_severity: str = ""
    action: Literal["inject_fault", "adjust_generator", "stop_device"] = "stop_device"
    target_device_id: str = ""
    action_params: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True
