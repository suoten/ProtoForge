"""v1.9.0 合规检测扩容测试：FINS（FINS-xxx）与 DL/T 645（D645-xxx）。

模式与既有检测器测试一致：违规报文逐规则命中、合规报文零误伤。
"""

from protoforge.testing.compliance import (
    DLT645ComplianceChecker,
    FinsComplianceChecker,
    get_supported_protocols,
)


def test_registry_includes_v19_protocols():
    supported = get_supported_protocols()
    assert "fins" in supported and "dlt645" in supported


def test_fins_detects_violations():
    checker = FinsComplianceChecker()
    bad = [
        # FINS-001: TCP magic 错误
        {"detail": {"magic": "XXXX"}},
        # FINS-002: 非法 MRC
        {"detail": {"mrc": 0xAA}},
        # FINS-003: 成功类消息携带非零 end code
        {"message_type": "fins_resp", "detail": {"end_code": 0x2101}},
        # FINS-004: 数据报不足 10 字节
        {"detail": {"datagram_length": 6}},
    ]
    report = checker.check_messages(bad)
    assert not report.passed
    hit = {v["rule_id"] for v in report.violations}
    assert hit == {"FINS-001", "FINS-002", "FINS-003", "FINS-004"}


def test_fins_clean_messages_no_violations():
    checker = FinsComplianceChecker()
    good = [
        {"direction": "send", "message_type": "fins_frame",
         "summary": "FINS 读命令", "detail": {"magic": "FINS", "mrc": 0x01}},
        {"direction": "recv", "message_type": "fins_resp",
         "summary": "FINS 读应答", "detail": {"magic": "FINS", "mrc": 0x01,
                                              "end_code": 0}},
        {"direction": "recv", "message_type": "fins_resp",
         "summary": "FINS 错误应答（异常允许非零 end code）",
         "detail": {"mrc": 0x01}},  # 错误帧 detail 不携带 end_code
    ]
    report = checker.check_messages(good)
    assert report.passed and report.compliance_score == 100.0


def test_dlt645_detects_violations():
    checker = DLT645ComplianceChecker()
    bad = [
        # D645-001: 起始符/结束符错误
        {"detail": {"start_byte": 0x67, "end_byte": 0x16}},
        {"detail": {"start_byte": 0x68, "end_byte": 0x17}},
        # D645-002: 地址非 12 位 BCD
        {"detail": {"address": "123"}},
        # D645-003: 非法控制码
        {"detail": {"control_code": 0x55}},
        # D645-004: 数据域超长
        {"detail": {"data_length": 300}},
        # D645-005: 校验和不符
        {"detail": {"checksum_calc": 0x57, "checksum": 0x58}},
    ]
    report = checker.check_messages(bad)
    assert not report.passed
    hit = {v["rule_id"] for v in report.violations}
    assert hit == {"D645-001", "D645-002", "D645-003", "D645-004", "D645-005"}


def test_dlt645_clean_messages_no_violations():
    checker = DLT645ComplianceChecker()
    good = [
        {"direction": "recv", "message_type": "dlt645", "summary": "读电能",
         "detail": {"start_byte": 0x68, "end_byte": 0x16,
                    "address": "060504030201", "control_code": 0x11,
                    "data_length": 4, "checksum_calc": 0x57, "checksum": 0x57}},
        {"direction": "recv", "message_type": "dlt645", "summary": "读电能应答",
         "detail": {"start_byte": 0x68, "end_byte": 0x16,
                    "address": "060504030201", "control_code": 0x91,
                    "data_length": 4, "checksum_calc": 0x57, "checksum": 0x57}},
    ]
    report = checker.check_messages(good)
    assert report.passed and report.compliance_score == 100.0
