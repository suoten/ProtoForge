import logging
from typing import Any, Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

PROTOCOL_MAP_BASE: dict[str, Optional[str]] = {
    "modbus_tcp": "modbus_tcp",
    "modbus_rtu": "modbus_rtu",
    "opcua": "opcua",
    "mqtt": "mqtt",
    "http": "http",
    "s7": "s7",
    "mc": "mc",
    "fins": "fins",
    "ab": "ab",
    "bacnet": "bacnet",
    "fanuc": "fanuc",
    "mtconnect": "mtconnect",
    "toledo": "toledo",
    "opcda": "opc_da",
    "profinet": None,
    "ethercat": None,
    "gb28181": None,
    "onvif": None,
    "dlt645": None,
    "iec104": None,
    "kuka": None,
    "abb_robot": None,
    "sparkplug_b": None,
    "serial_port": "serial",
    "database_source": "database",
    "barcode_scanner": "barcode_scanner",
    "simulator": "simulator",
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
    edgelite_protocol: Optional[str] = None
    warning: str = ""


@dataclass
class DataTypeMappingResult:
    status: str
    source_type: str
    target_type: str
    degraded: bool = False
    warning: str = ""


class ProtocolMapper:
    def __init__(self, base_map: dict[str, Optional[str]] | None = None):
        self._map: dict[str, Optional[str]] = dict(base_map or PROTOCOL_MAP_BASE)
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
        logger.info("Updated EdgeLite supported protocols: %s", protocols)

    def get_supported_source_protocols(self) -> list[str]:
        return [k for k, v in self._map.items() if v is not None]

    def get_map(self) -> dict[str, Optional[str]]:
        return dict(self._map)

    def add_mapping(self, protoforge_protocol: str, edgelite_protocol: Optional[str]) -> None:
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
