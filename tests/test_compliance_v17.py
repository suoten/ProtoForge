"""v1.7.0 合规检测扩容测试：BACnet（BC-xxx）与 IEC 61850/MMS（MMS-xxx）。

模式与既有 5 协议检测器一致：违规报文逐规则命中、合规报文零误伤。
"""

from protoforge.testing.compliance import (
    BACnetComplianceChecker,
    IEC61850ComplianceChecker,
    get_supported_protocols,
)


def test_registry_includes_new_protocols():
    supported = get_supported_protocols()
    assert "bacnet" in supported and "iec61850" in supported


def test_bacnet_detects_violations():
    checker = BACnetComplianceChecker()
    bad = [
        # BC-001: BVLC 版本错误
        {"detail": {"bvlc_version": 0x80}},
        # BC-002: 非法 BVLC function
        {"detail": {"bvlc_function": 0x20}},
        # BC-003: NPDU 版本错误
        {"detail": {"npdu_version": 2}},
        # BC-004: 非法 APDU 类型
        {"detail": {"apdu_type": 9}},
        # BC-005: 非法 service choice
        {"detail": {"service_choice": 99}},
    ]
    report = checker.check_messages(bad)
    hit = {v["rule_id"] for v in report.violations}
    assert {"BC-001", "BC-002", "BC-003", "BC-004", "BC-005"} <= hit


def test_bacnet_clean_messages_no_violations():
    checker = BACnetComplianceChecker()
    # Who-Is 广播帧的真实字段
    good = {"detail": {"bvlc_version": 0x81, "bvlc_function": 0x0B,
                       "npdu_version": 1, "apdu_type": 1, "service_choice": 8}}
    assert checker.check_messages([good]).violations == []


def test_iec61850_detects_violations():
    checker = IEC61850ComplianceChecker()
    bad = [
        # MMS-001: 非法 PDU tag
        {"detail": {"pdu_tag": 0xB0}},
        # MMS-002: short-form 长度装不下 300 字节
        {"detail": {"ber_length": 300, "length_of_length": 0}},
        # MMS-003: ConfirmedRequest 缺 invoke ID
        {"detail": {"pdu_tag": 0xA0, "invoke_id": None}},
        # MMS-004: 域名不符合 LD 约定
        {"detail": {"domain_name": "StationA"}},
    ]
    report = checker.check_messages(bad)
    hit = {v["rule_id"] for v in report.violations}
    assert {"MMS-001", "MMS-002", "MMS-003", "MMS-004"} <= hit


def test_iec61850_clean_messages_no_violations():
    checker = IEC61850ComplianceChecker()
    good = {"detail": {"pdu_tag": 0xA0, "invoke_id": 7, "domain_name": "LD0",
                       "ber_length": 20, "length_of_length": 0}}
    assert checker.check_messages([good]).violations == []
