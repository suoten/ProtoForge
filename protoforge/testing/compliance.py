"""Protocol compliance checking module.

Provides compliance checking for industrial protocol communications,
verifying that recorded protocol messages conform to protocol specifications.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class Severity(str, Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass
class ComplianceRule:
    """A single compliance check rule."""
    id: str
    name: str
    description: str
    severity: Severity = Severity.ERROR


@dataclass
class ComplianceViolation:
    """A compliance violation found during checking."""
    rule_id: str
    rule_name: str
    severity: str
    message: str
    message_index: int = 0
    raw_data: str = ""


@dataclass
class ComplianceReport:
    """Result of a compliance check."""
    id: str = ""
    protocol: str = ""
    total_messages: int = 0
    total_rules: int = 0
    violations: list[dict[str, Any]] = field(default_factory=list)
    compliance_score: float = 100.0
    passed: bool = True
    created_at: float = 0.0

    def __post_init__(self):
        if not self.id:
            self.id = uuid.uuid4().hex[:12]
        import time
        if not self.created_at:
            self.created_at = time.time()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "protocol": self.protocol,
            "total_messages": self.total_messages,
            "total_rules": self.total_rules,
            "violations": self.violations,
            "compliance_score": self.compliance_score,
            "passed": self.passed,
            "created_at": self.created_at,
        }


class BaseComplianceChecker:
    """Base class for protocol compliance checkers."""

    protocol_name: str = "base"
    rules: list[ComplianceRule] = []

    def check_messages(self, messages: list[dict[str, Any]]) -> ComplianceReport:
        """Check a list of recorded messages for compliance violations.

        Args:
            messages: List of recorded protocol messages, each with at least
                      'direction', 'message_type', 'summary', 'detail' fields.

        Returns:
            ComplianceReport with violations and score.
        """
        violations: list[ComplianceViolation] = []

        for idx, msg in enumerate(messages):
            for rule in self.rules:
                try:
                    violation = self._check_rule(rule, msg, idx, messages)
                    if violation:
                        violations.append(violation)
                except Exception as e:
                    logger.debug("Rule %s check error on msg %d: %s", rule.id, idx, e)

        # Calculate score: start at 100, subtract per violation
        error_count = sum(1 for v in violations if v.severity == Severity.ERROR.value)
        warning_count = sum(1 for v in violations if v.severity == Severity.WARNING.value)
        score = max(0.0, 100.0 - error_count * 10 - warning_count * 2)

        return ComplianceReport(
            protocol=self.protocol_name,
            total_messages=len(messages),
            total_rules=len(self.rules),
            violations=[{
                "rule_id": v.rule_id,
                "rule_name": v.rule_name,
                "severity": v.severity,
                "message": v.message,
                "message_index": v.message_index,
            } for v in violations],
            compliance_score=round(score, 1),
            passed=len(violations) == 0,
        )

    def _check_rule(
        self, rule: ComplianceRule, msg: dict[str, Any],
        idx: int, all_messages: list[dict[str, Any]]
    ) -> ComplianceViolation | None:
        """Override in subclass. Return violation or None."""
        return None

    def _make_violation(
        self, rule: ComplianceRule, msg: str, idx: int = 0
    ) -> ComplianceViolation:
        return ComplianceViolation(
            rule_id=rule.id,
            rule_name=rule.name,
            severity=rule.severity.value,
            message=msg,
            message_index=idx,
        )


class ModbusComplianceChecker(BaseComplianceChecker):
    """Modbus TCP protocol compliance checker."""

    protocol_name = "modbus_tcp"

    rules = [
        ComplianceRule("MB-001", "Function Code Validity",
                       "Function code must be 1-6, 15-16, 23, or 246-255", Severity.ERROR),
        ComplianceRule("MB-002", "Register Address Range",
                       "Register address must be within valid range", Severity.WARNING),
        ComplianceRule("MB-003", "Data Length Limit",
                       "Data payload must not exceed 253 bytes", Severity.ERROR),
        ComplianceRule("MB-004", "Exception Code Validity",
                       "Exception codes must be 1-4", Severity.ERROR),
    ]

    VALID_FC = {1, 2, 3, 4, 5, 6, 15, 16, 23} | set(range(246, 256))
    VALID_EXCEPTION_CODES = {1, 2, 3, 4}

    def _check_rule(self, rule, msg, idx, all_messages):
        detail = msg.get("detail", {})
        msg.get("summary", "")
        msg.get("message_type", "")

        if rule.id == "MB-001":
            fc = detail.get("function_code")
            if fc is not None:
                try:
                    fc_int = int(fc)
                    if fc_int not in self.VALID_FC:
                        return self._make_violation(rule, f"Invalid function code: {fc_int}", idx)
                except (ValueError, TypeError):
                    pass

        elif rule.id == "MB-002":
            addr = detail.get("start_address") or detail.get("address")
            if addr is not None:
                try:
                    addr_int = int(addr)
                    if addr_int < 0 or addr_int > 65535:
                        return self._make_violation(rule, f"Register address out of range: {addr_int}", idx)
                except (ValueError, TypeError):
                    pass

        elif rule.id == "MB-003":
            data = detail.get("data") or detail.get("values")
            if data and isinstance(data, (list, bytes, str)):
                length = len(data) if isinstance(data, list) else len(str(data))
                if length > 253:
                    return self._make_violation(rule, f"Data length {length} exceeds 253 bytes limit", idx)

        elif rule.id == "MB-004":
            exc_code = detail.get("exception_code")
            if exc_code is not None:
                try:
                    exc_int = int(exc_code)
                    if exc_int not in self.VALID_EXCEPTION_CODES:
                        return self._make_violation(rule, f"Invalid exception code: {exc_int}", idx)
                except (ValueError, TypeError):
                    pass

        return None


class S7ComplianceChecker(BaseComplianceChecker):
    """Siemens S7 protocol compliance checker."""

    protocol_name = "s7"

    rules = [
        ComplianceRule("S7-001", "TPKT Version",
                       "TPKT version must be 0x03", Severity.ERROR),
        ComplianceRule("S7-002", "Protocol ID",
                       "S7 protocol ID must be 0x32", Severity.ERROR),
        ComplianceRule("S7-003", "ROSCTR Validity",
                       "ROSCTR must be 1 (Job), 2 (Ack), 3 (Ack-Data), or 7 (Userdata)", Severity.ERROR),
    ]

    def _check_rule(self, rule, msg, idx, all_messages):
        detail = msg.get("detail", {})

        if rule.id == "S7-001":
            tpkt_ver = detail.get("tpkt_version")
            if tpkt_ver is not None and int(tpkt_ver) != 3:
                return self._make_violation(rule, f"Invalid TPKT version: {tpkt_ver}, expected 3", idx)

        elif rule.id == "S7-002":
            proto_id = detail.get("protocol_id")
            if proto_id is not None and int(proto_id) != 0x32:
                return self._make_violation(rule, f"Invalid protocol ID: 0x{proto_id:02X}, expected 0x32", idx)

        elif rule.id == "S7-003":
            rosctr = detail.get("rosctr")
            if rosctr is not None:
                try:
                    rosctr_int = int(rosctr)
                    if rosctr_int not in {1, 2, 3, 7}:
                        return self._make_violation(rule, f"Invalid ROSCTR: {rosctr_int}", idx)
                except (ValueError, TypeError):
                    pass

        return None


class OpcUaComplianceChecker(BaseComplianceChecker):
    """OPC-UA protocol compliance checker."""

    protocol_name = "opcua"

    rules = [
        ComplianceRule("OU-001", "Hello/Acknowledge Handshake",
                       "Session must start with Hello/Acknowledge", Severity.WARNING),
        ComplianceRule("OU-002", "SecureChannel Before Session",
                       "OpenSecureChannel must precede CreateSession", Severity.WARNING),
        ComplianceRule("OU-003", "ActivateSession After CreateSession",
                       "ActivateSession must follow CreateSession", Severity.ERROR),
    ]

    def _check_rule(self, rule, msg, idx, all_messages):
        msg_type = msg.get("message_type", "").lower()
        summary = msg.get("summary", "").lower()

        if rule.id == "OU-001":
            if idx == 0 and "hello" not in msg_type and "hello" not in summary:
                # First message should be Hello
                has_hello = any(
                    "hello" in m.get("message_type", "").lower() or "hello" in m.get("summary", "").lower()
                    for m in all_messages[:5]
                )
                if not has_hello:
                    return self._make_violation(rule, "No Hello message found at session start", idx)

        elif rule.id == "OU-002":
            if "createsession" in msg_type or "createsession" in summary:
                has_channel = any(
                    "opensecurechannel" in m.get("message_type", "").lower()
                    or "opensecurechannel" in m.get("summary", "").lower()
                    for m in all_messages[:idx]
                )
                if not has_channel and idx > 0:
                    return self._make_violation(rule, "CreateSession without prior OpenSecureChannel", idx)

        elif rule.id == "OU-003":
            if "activatesession" in msg_type or "activatesession" in summary:
                has_create = any(
                    "createsession" in m.get("message_type", "").lower()
                    or "createsession" in m.get("summary", "").lower()
                    for m in all_messages[:idx]
                )
                if not has_create:
                    return self._make_violation(rule, "ActivateSession without prior CreateSession", idx)

        return None


class IEC104ComplianceChecker(BaseComplianceChecker):
    """IEC 60870-5-104 protocol compliance checker."""

    protocol_name = "iec104"

    rules = [
        ComplianceRule("IEC-001", "STARTDT Before Data",
                       "STARTDT act must precede data transfer", Severity.ERROR),
        ComplianceRule("IEC-002", "ASDU Type Validity",
                       "ASDU type identifier must be 1-127", Severity.ERROR),
        ComplianceRule("IEC-003", "Message Structure",
                       "Messages must have valid start byte 0x68", Severity.WARNING),
    ]

    def _check_rule(self, rule, msg, idx, all_messages):
        detail = msg.get("detail", {})
        msg_type = msg.get("message_type", "").lower()
        msg.get("summary", "").lower()

        if rule.id == "IEC-001":
            if idx > 0 and "data" in msg_type and "start" not in msg_type:
                has_start = any(
                    "startdt" in m.get("message_type", "").lower()
                    or "startdt" in m.get("summary", "").lower()
                    or "start" in m.get("summary", "").lower()
                    for m in all_messages[:idx]
                )
                if not has_start:
                    return self._make_violation(rule, "Data transfer without prior STARTDT", idx)

        elif rule.id == "IEC-002":
            type_id = detail.get("type_id") or detail.get("asdu_type")
            if type_id is not None:
                try:
                    tid = int(type_id)
                    if tid < 1 or tid > 127:
                        return self._make_violation(rule, f"Invalid ASDU type ID: {tid}", idx)
                except (ValueError, TypeError):
                    pass

        elif rule.id == "IEC-003":
            start_byte = detail.get("start_byte")
            if start_byte is not None and int(start_byte) != 0x68:
                return self._make_violation(rule, f"Invalid start byte: 0x{int(start_byte):02X}, expected 0x68", idx)

        return None


class MQTTComplianceChecker(BaseComplianceChecker):
    """MQTT protocol compliance checker."""

    protocol_name = "mqtt"

    rules = [
        ComplianceRule("MQTT-001", "Connect First",
                       "First packet must be CONNECT", Severity.ERROR),
        ComplianceRule("MQTT-002", "Packet Type Validity",
                       "Packet type must be 1-14", Severity.ERROR),
        ComplianceRule("MQTT-003", "QoS Validity",
                       "QoS level must be 0, 1, or 2", Severity.ERROR),
    ]

    VALID_PACKET_TYPES = {1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14}

    def _check_rule(self, rule, msg, idx, all_messages):
        detail = msg.get("detail", {})
        msg_type = msg.get("message_type", "").lower()
        summary = msg.get("summary", "").lower()

        if rule.id == "MQTT-001":
            if idx == 0 and "connect" not in msg_type and "connect" not in summary:
                return self._make_violation(rule, "First message is not CONNECT", idx)

        elif rule.id == "MQTT-002":
            pkt_type = detail.get("packet_type")
            if pkt_type is not None:
                try:
                    pt = int(pkt_type)
                    if pt not in self.VALID_PACKET_TYPES:
                        return self._make_violation(rule, f"Invalid packet type: {pt}", idx)
                except (ValueError, TypeError):
                    pass

        elif rule.id == "MQTT-003":
            qos = detail.get("qos")
            if qos is not None:
                try:
                    qos_int = int(qos)
                    if qos_int not in {0, 1, 2}:
                        return self._make_violation(rule, f"Invalid QoS level: {qos_int}", idx)
                except (ValueError, TypeError):
                    pass

        return None


class BACnetComplianceChecker(BaseComplianceChecker):
    """BACnet (ASHRAE 135) protocol compliance checker (v1.7.0)."""

    protocol_name = "bacnet"

    rules = [
        ComplianceRule("BC-001", "BVLC Version",
                       "BVLC version must be 0x81", Severity.ERROR),
        ComplianceRule("BC-002", "BVLC Function Code",
                       "BVLC function must be 0x00-0x0B (result/B_register/F_register/DistributeBroadcastToNetwork/orig-unicast/orig-broadcast/forward)", Severity.ERROR),
        ComplianceRule("BC-003", "NPDU Version",
                       "NPDU version must be 0x01", Severity.ERROR),
        ComplianceRule("BC-004", "APDU PDU Type",
                       "APDU type must be 0-7 (confirmed/unconfirmed/simpleack/complexack/segmentack/error/reject/abort)", Severity.ERROR),
        ComplianceRule("BC-005", "Confirmed Service Choice",
                       "Confirmed service choice must be a valid BACnet service (0-30)", Severity.WARNING),
    ]

    VALID_BVLC_FUNCTIONS = set(range(0x00, 0x0C))
    VALID_APDU_TYPES = set(range(0, 8))
    VALID_CONFIRMED_SERVICES = set(range(0, 31))

    def _check_rule(self, rule, msg, idx, all_messages):
        detail = msg.get("detail", {})

        if rule.id == "BC-001":
            version = detail.get("bvlc_version")
            if version is not None:
                try:
                    if int(version) != 0x81:
                        return self._make_violation(rule, f"BVLC version {version} != 0x81", idx)
                except (ValueError, TypeError):
                    pass

        elif rule.id == "BC-002":
            func = detail.get("bvlc_function")
            if func is not None:
                try:
                    f = int(func)
                    if f not in self.VALID_BVLC_FUNCTIONS:
                        return self._make_violation(rule, f"Invalid BVLC function: 0x{f:02X}", idx)
                except (ValueError, TypeError):
                    pass

        elif rule.id == "BC-003":
            version = detail.get("npdu_version")
            if version is not None:
                try:
                    if int(version) != 0x01:
                        return self._make_violation(rule, f"NPDU version {version} != 0x01", idx)
                except (ValueError, TypeError):
                    pass

        elif rule.id == "BC-004":
            apdu_type = detail.get("apdu_type")
            if apdu_type is not None:
                try:
                    t = int(apdu_type)
                    if t not in self.VALID_APDU_TYPES:
                        return self._make_violation(rule, f"Invalid APDU type: {t}", idx)
                except (ValueError, TypeError):
                    pass

        elif rule.id == "BC-005":
            svc = detail.get("service_choice")
            if svc is not None:
                try:
                    s = int(svc)
                    if s not in self.VALID_CONFIRMED_SERVICES:
                        return self._make_violation(rule, f"Invalid service choice: {s}", idx)
                except (ValueError, TypeError):
                    pass

        return None


class IEC61850ComplianceChecker(BaseComplianceChecker):
    """IEC 61850 (MMS mapping) protocol compliance checker (v1.7.0)."""

    protocol_name = "iec61850"

    rules = [
        ComplianceRule("MMS-001", "PDU Tag Validity",
                       "MMS PDU tag must be 0xA0-0xA8 (ConfirmedRequest/Response, UnconfirmedPDU, RejectPDU, AbortPDU, etc.)", Severity.ERROR),
        ComplianceRule("MMS-002", "BER Length Encoding",
                       "BER length must use short form (<=127) or long form with correct length-of-length", Severity.ERROR),
        ComplianceRule("MMS-003", "Invoke ID Present",
                       "ConfirmedRequest/Response must carry an invoke ID", Severity.WARNING),
        ComplianceRule("MMS-004", "Domain Object Name Format",
                       "Domain/LD names should follow LD0.. naming convention", Severity.INFO),
    ]

    VALID_PDU_TAGS = set(range(0xA0, 0xA9))

    def _check_rule(self, rule, msg, idx, all_messages):
        detail = msg.get("detail", {})

        if rule.id == "MMS-001":
            tag = detail.get("pdu_tag")
            if tag is not None:
                try:
                    t = int(tag)
                    if t not in self.VALID_PDU_TAGS:
                        return self._make_violation(rule, f"Invalid MMS PDU tag: 0x{t:02X}", idx)
                except (ValueError, TypeError):
                    pass

        elif rule.id == "MMS-002":
            length = detail.get("ber_length")
            length_of_length = detail.get("length_of_length")
            if length is not None and length_of_length is not None:
                try:
                    lol = int(length_of_length)
                    total = int(length)
                    if lol == 0 and total > 127:
                        return self._make_violation(
                            rule, f"Short-form length used for {total} bytes (>127)", idx)
                    if not (0 <= lol <= 4):
                        return self._make_violation(rule, f"Invalid length-of-length: {lol}", idx)
                except (ValueError, TypeError):
                    pass

        elif rule.id == "MMS-003":
            invoke_id = detail.get("invoke_id")
            pdu_tag = detail.get("pdu_tag")
            if pdu_tag in (0xA0, 0xA1) and invoke_id is None:
                return self._make_violation(rule, "Confirmed PDU without invoke ID", idx)

        elif rule.id == "MMS-004":
            domain = detail.get("domain_name") or detail.get("ld_name")
            if domain and not str(domain).upper().startswith("LD"):
                return self._make_violation(
                    rule, f"Domain name '{domain}' does not follow LD naming", idx)

        return None


# Registry of compliance checkers
CHECKER_REGISTRY: dict[str, type[BaseComplianceChecker]] = {
    "modbus_tcp": ModbusComplianceChecker,
    "modbus": ModbusComplianceChecker,
    "s7": S7ComplianceChecker,
    "opcua": OpcUaComplianceChecker,
    "opc_ua": OpcUaComplianceChecker,
    "iec104": IEC104ComplianceChecker,
    "iec_104": IEC104ComplianceChecker,
    "mqtt": MQTTComplianceChecker,
    "bacnet": BACnetComplianceChecker,
    "iec61850": IEC61850ComplianceChecker,
    "iec_61850": IEC61850ComplianceChecker,
}


def get_compliance_checker(protocol: str) -> BaseComplianceChecker | None:
    """Get a compliance checker for the given protocol.

    Returns None if no checker is available for the protocol.
    """
    checker_cls = CHECKER_REGISTRY.get(protocol.lower())
    if checker_cls:
        return checker_cls()
    return None


def get_supported_protocols() -> list[str]:
    """Return list of protocols that support compliance checking."""
    return sorted(set(CHECKER_REGISTRY.keys()))


def get_rules_for_protocol(protocol: str) -> list[dict[str, Any]]:
    """Return the list of compliance rules for a protocol."""
    checker = get_compliance_checker(protocol)
    if not checker:
        return []
    return [
        {
            "id": r.id,
            "name": r.name,
            "description": r.description,
            "severity": r.severity.value,
        }
        for r in checker.rules
    ]
