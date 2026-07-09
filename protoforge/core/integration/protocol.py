"""Module: protocol."""

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

PROTOCOL_MAP_BASE: dict[str, str | None] = {
    "modbus_tcp": "modbus_tcp",
    "modbus_rtu": "modbus_rtu",
    "opcua": "opcua",
    # FIXED-P0: 使用 EdgeLite plugin_name 而非别名，确保新旧版本 EdgeLite 都能接受
    # EdgeLite 旧版 _validate_push_device 只认 plugin_name（如 siemens_s7），不认别名（如 s7）
    # EdgeLite 新版 get_all_protocol_keys() 同时支持别名和 plugin_name
    # 所以使用 plugin_name 是最安全的选择
    "mqtt": "mqtt_client",
    "http": "http_webhook",
    "s7": "siemens_s7",
    "mc": "mitsubishi_mc",
    "fins": "omron_fins",
    "ab": "allen_bradley",
    "bacnet": None,
    "fanuc": None,        # EdgeLite 无 fanuc 驱动
    "mtconnect": None,    # EdgeLite 无 mtconnect 驱动
    "toledo": None,       # EdgeLite 无 toledo 驱动
    "opcda": "opc_da",
    "profinet": None,
    "ethercat": None,
    "gb28181": None,
    "onvif": "onvif",
    "dlt645": "dlt645",
    "iec104": "iec104",
    "kuka": "kuka",
    "abb_robot": "abb_robot",
    "sparkplug_b": "sparkplug_b",
    "serial_port": "serial",
    "database_source": "database",
    "barcode_scanner": "barcode_scanner",
    "simulator": "simulator",
}

# FIXED-P0: 别名→plugin_name 反向映射表
# 当 EdgeLite 使用旧版 API（get_supported_protocols 只返回 plugin_name 不含别名）时，
# ProtoForge 需要将别名（s7/mqtt/mc/http/fins/ab）转换为 plugin_name（siemens_s7/mqtt_client/...）
_ALIAS_TO_PLUGIN_NAME: dict[str, str] = {
    "s7": "siemens_s7",
    "mqtt": "mqtt_client",
    "mc": "mitsubishi_mc",
    "http": "http_webhook",
    "fins": "omron_fins",
    "ab": "allen_bradley",
}

DATA_TYPE_MAP: dict[str, str] = {
    "bool": "bool",
    "int16": "int16",
    "int32": "int32",
    "uint16": "uint16",
    "uint32": "uint32",
    "float32": "float32",
    "float64": "float64",
    "string": "string",
}

DATA_TYPE_MAP_FALLBACK: dict[str, str] = {
    "float64": "float32",
    "int32": "int16",
    "uint32": "uint16",
}

ACCESS_MODE_MAP: dict[str, str] = {
    "r": "r", "w": "w", "rw": "rw", "ro": "r", "wo": "w",
}


@dataclass
class ProtocolMappingResult:
    status: str
    protoforge_protocol: str
    edgelite_protocol: str | None = None
    warning: str = ""


@dataclass
class DataTypeMappingResult:
    status: str
    source_type: str
    target_type: str
    degraded: bool = False
    warning: str = ""


class ProtocolMapper:
    def __init__(self, base_map: dict[str, str | None] | None = None):
        self._map: dict[str, str | None] = dict(base_map or PROTOCOL_MAP_BASE)
        self._edgelite_protocols: set[str] = set()

    def map(self, protoforge_protocol: str) -> ProtocolMappingResult:
        mapped = self._map.get(protoforge_protocol)
        if mapped is None:
            if protoforge_protocol in self._map:
                return ProtocolMappingResult(
                    status="unsupported",
                    protoforge_protocol=protoforge_protocol,
                    warning=f"Protocol {protoforge_protocol} cannot be pushed to EdgeLite",
                )
            return ProtocolMappingResult(
                status="unknown",
                protoforge_protocol=protoforge_protocol,
                warning=f"Protocol {protoforge_protocol} not in mapping table",
            )

        if self._edgelite_protocols and mapped not in self._edgelite_protocols:
            return ProtocolMappingResult(
                status="target_unavailable",
                protoforge_protocol=protoforge_protocol,
                edgelite_protocol=mapped,
                warning=f"EdgeLite does not support protocol: {mapped}",
            )

        return ProtocolMappingResult(
            status="ok",
            protoforge_protocol=protoforge_protocol,
            edgelite_protocol=mapped,
        )

    def update_edgelite_protocols(self, protocols: list[str]) -> None:
        self._edgelite_protocols: set[str] = set(protocols)
        logger.info("EdgeLite reported supported protocols: %s", protocols)

        # FIXED-P0: 自动检测 EdgeLite 版本并适配别名映射
        # EdgeLite 旧版 get_supported_protocols() 只返回 plugin_name（如 siemens_s7），
        # 不含别名（如 s7）。新版 get_all_protocol_keys() 包含别名。
        # 当检测到 EdgeLite 返回的是 plugin_name 列表（无别名）时，
        # 自动将 PROTOCOL_MAP_BASE 中的别名映射改为 plugin_name 映射。
        self._adapt_alias_mapping_for_edgelite(protocols)

    def _adapt_alias_mapping_for_edgelite(self, protocols: list[str]) -> None:
        """根据 EdgeLite 返回的协议列表自动适配别名→plugin_name 映射。

        检测逻辑：如果 EdgeLite 返回了 plugin_name（如 siemens_s7）但没返回别名（如 s7），
        则将 PROTOCOL_MAP_BASE 中 s7→s7 改为 s7→siemens_s7，使推送时使用 plugin_name。
        """
        protocol_set = set(protocols)
        adapted = False

        for alias, plugin_name in _ALIAS_TO_PLUGIN_NAME.items():
            # EdgeLite 有 plugin_name 但没有别名 → 旧版 API
            if plugin_name in protocol_set and alias not in protocol_set:
                # 查找 PROTOCOL_MAP_BASE 中哪些键映射到了这个别名
                for pf_proto, el_mapped in list(self._map.items()):
                    if el_mapped == alias:
                        self._map[pf_proto] = plugin_name
                        logger.info(
                            "Adapted protocol mapping: %s → %s (EdgeLite uses plugin_name, alias '%s' not available)",
                            pf_proto, plugin_name, alias,
                        )
                        adapted = True
            # EdgeLite 有别名也有 plugin_name → 新版 API，使用别名（更短更直观）
            elif alias in protocol_set and plugin_name in protocol_set:
                # 确保映射使用别名（如果之前被适配过，恢复为别名）
                for pf_proto, el_mapped in list(self._map.items()):
                    if el_mapped == plugin_name and pf_proto in _ALIAS_TO_PLUGIN_NAME and _ALIAS_TO_PLUGIN_NAME[pf_proto] == plugin_name:
                        self._map[pf_proto] = pf_proto if pf_proto in protocol_set else alias
                        if self._map[pf_proto] != el_mapped:
                            logger.info(
                                "Restored protocol mapping: %s → %s (EdgeLite supports alias)",
                                pf_proto, self._map[pf_proto],
                            )

        if adapted:
            logger.info("Protocol mapping adapted for EdgeLite (plugin_name mode): %s", {
                k: v for k, v in self._map.items() if v is not None and k in _ALIAS_TO_PLUGIN_NAME or v in _ALIAS_TO_PLUGIN_NAME
            })

    def adapt_for_unknown_edgelite(self) -> None:
        """当无法获取 EdgeLite 协议列表时，保守地使用 plugin_name 格式。

        EdgeLite 旧版只认 plugin_name（如 siemens_s7），不认别名（如 s7）。
        当协议列表获取失败时，使用 plugin_name 格式是最安全的选择，
        因为 EdgeLite 新旧版本都支持 plugin_name。
        """
        for alias, plugin_name in _ALIAS_TO_PLUGIN_NAME.items():
            for pf_proto, el_mapped in list(self._map.items()):
                if el_mapped == alias:
                    self._map[pf_proto] = plugin_name
                    logger.info(
                        "Conservative protocol mapping: %s → %s (EdgeLite protocol list unavailable, using plugin_name)",
                        pf_proto, plugin_name,
                    )

    def get_supported_source_protocols(self) -> list[str]:
        return [k for k, v in self._map.items() if v is not None]

    def get_map(self) -> dict[str, str | None]:
        return dict(self._map)

    def add_mapping(self, protoforge_protocol: str, edgelite_protocol: str | None) -> None:
        self._map[protoforge_protocol] = edgelite_protocol


class DataTypeMapper:
    def __init__(
        self,
        primary_map: dict[str, str] | None = None,
        fallback_map: dict[str, str] | None = None,
        edgelite_supported: set[str] | None = None,
    ):
        self._primary = primary_map or DATA_TYPE_MAP
        self._fallback = fallback_map or DATA_TYPE_MAP_FALLBACK
        self._edgelite_supported = edgelite_supported

    def map(self, source_type: str) -> DataTypeMappingResult:
        primary = self._primary.get(source_type)
        if primary is None:
            return DataTypeMappingResult(
                status="unknown",
                source_type=source_type,
                target_type="float32",
                warning=f"Data type {source_type} not in mapping table, using float32",
            )

        if self._edgelite_supported and primary not in self._edgelite_supported:
            fallback = self._fallback.get(source_type)
            if fallback and fallback in self._edgelite_supported:
                return DataTypeMappingResult(
                    status="degraded",
                    source_type=source_type,
                    target_type=fallback,
                    degraded=True,
                    warning=f"EdgeLite does not support {primary}, degraded to {fallback}",
                )
            return DataTypeMappingResult(
                status="ok",
                source_type=source_type,
                target_type=primary,
                warning=f"EdgeLite may not support {primary}",
            )

        return DataTypeMappingResult(
            status="ok",
            source_type=source_type,
            target_type=primary,
        )

    def update_edgelite_supported(self, supported: set[str]) -> None:
        self._edgelite_supported = supported
