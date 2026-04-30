import logging
from dataclasses import dataclass, field
from typing import Any

from protoforge.core.integration.protocol import DataTypeMapper, ProtocolMapper

logger = logging.getLogger(__name__)


@dataclass
class CompatibilityReport:
    device_id: str = ""
    compatible: bool = True
    protocol_result: dict[str, Any] = field(default_factory=dict)
    data_type_results: list[dict[str, Any]] = field(default_factory=list)
    driver_config_result: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class MappingValidator:
    def __init__(
        self,
        protocol_mapper: ProtocolMapper | None = None,
        data_type_mapper: DataTypeMapper | None = None,
    ):
        self._protocol_mapper = protocol_mapper or ProtocolMapper()
        self._data_type_mapper = data_type_mapper or DataTypeMapper()

    def validate(
        self,
        device_id: str,
        protocol: str,
        points: list[dict[str, Any]],
        driver_config: dict[str, Any],
    ) -> CompatibilityReport:
        report = CompatibilityReport(device_id=device_id)

        proto_result = self._protocol_mapper.map(protocol)
        report.protocol_result = {
            "status": proto_result.status,
            "protoforge_protocol": proto_result.protoforge_protocol,
            "edgelite_protocol": proto_result.edgelite_protocol,
            "warning": proto_result.warning,
        }
        if proto_result.status != "ok":
            report.compatible = False
            if proto_result.status in ("unsupported", "unknown"):
                report.errors.append(proto_result.warning)
            else:
                report.warnings.append(proto_result.warning)

        for p in points:
            dt = p.get("data_type", "float32")
            dt_result = self._data_type_mapper.map(dt)
            entry = {
                "point_name": p.get("name", ""),
                "status": dt_result.status,
                "source_type": dt_result.source_type,
                "target_type": dt_result.target_type,
                "degraded": dt_result.degraded,
                "warning": dt_result.warning,
            }
            report.data_type_results.append(entry)
            if dt_result.warning:
                report.warnings.append(f"Point '{p.get('name', '')}': {dt_result.warning}")

        if not driver_config:
            report.warnings.append("Driver config is empty")

        if report.warnings:
            logger.info("Compatibility report for %s: compatible=%s, warnings=%d",
                       device_id, report.compatible, len(report.warnings))

        return report
