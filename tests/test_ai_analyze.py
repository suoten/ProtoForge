"""AI 调试排障单元测试 — Fake LLM 客户端，不依赖真实 Ollama（v1.13.4）。"""

import json

from protoforge import ai_analyze as aa

LOGS = [
    {"timestamp": 1794295743.1, "protocol": "modbus_tcp", "direction": "inbound",
     "device_id": "plc-1", "event": "exception_response",
     "message": "FC03 -> exception 0x02 (illegal data address)"},
    {"timestamp": 1794295743.5, "protocol": "modbus_tcp", "direction": "outbound",
     "device_id": "plc-1", "event": "read_holding_registers", "message": "addr=4050 count=2"},
]

DIAGNOSIS = {
    "summary": "PLC 对 FC03 读请求返回异常码 0x02（非法数据地址）",
    "findings": [
        {"issue": "读取地址超出从站点表范围",
         "evidence": ["1794295743.1 inbound plc-1 exception_response FC03 0x02",
                      "1794295743.5 outbound plc-1 read addr=4050"],
         "likely_cause": "主站配置的寄存器地址与从站点表不一致（40001 记法与偏移混淆）",
         "suggested_fix": "核对点表：把主站地址改为从站已定义的 HR 偏移",
         "confidence": "high"},
        {"issue": "无证据的猜测结论"},
    ],
    "notes": ["日志窗口较短"],
}


class FakeLLM:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def chat(self, system, user):
        self.calls.append((system, user))
        return self.responses.pop(0)


def _cfg():
    return aa.AIConfig(base_url="http://llm.test", model="test", timeout=5)


def test_analyze_basic():
    out = aa.analyze_debug_logs(LOGS, config=_cfg(), client=FakeLLM([json.dumps(DIAGNOSIS)]))
    assert out["ok"] is True
    diag = out["diagnosis"]
    assert "0x02" in diag["summary"]
    # 出处红线：无 evidence 的结论被丢弃并记入 notes
    assert len(diag["findings"]) == 1
    assert diag["findings"][0]["confidence"] == "high"
    assert any("丢弃缺少 evidence" in n for n in out["notes"])
    assert any("LLM: 日志窗口较短" in n for n in out["notes"])
    assert out["log_count"] == 2


def test_empty_logs():
    out = aa.analyze_debug_logs([], config=_cfg(), client=FakeLLM([]))
    assert out["ok"] is False and "日志" in out["error"]


def test_invalid_confidence_falls_back():
    data = {"summary": "s", "findings": [
        {"issue": "x", "evidence": ["ev"], "confidence": "绝对确定"}]}
    out = aa.analyze_debug_logs(LOGS, config=_cfg(), client=FakeLLM([json.dumps(data)]))
    assert out["diagnosis"]["findings"][0]["confidence"] == "medium"
    assert any("回落 medium" in n for n in out["notes"])


def test_findings_truncated_to_cap():
    many = {"summary": "s", "findings": [
        {"issue": f"i{i}", "evidence": ["ev"], "confidence": "low"} for i in range(15)]}
    out = aa.analyze_debug_logs(LOGS, config=_cfg(), client=FakeLLM([json.dumps(many)]))
    assert len(out["diagnosis"]["findings"]) == aa.MAX_FINDINGS
    assert any("截断" in n for n in out["notes"])


def test_repair_retry_on_invalid_json():
    llm = FakeLLM(["散文输出", json.dumps(DIAGNOSIS)])
    out = aa.analyze_debug_logs(LOGS, config=_cfg(), client=llm)
    assert out["ok"] is True
    assert len(llm.calls) == 2


def test_llm_unreachable_hint():
    class Boom:
        def chat(self, system, user):
            raise ConnectionError("refused")

    out = aa.analyze_debug_logs(LOGS, config=_cfg(), client=Boom())
    assert out["ok"] is False
    assert "ollama" in out.get("hint", "").lower()


def test_long_logs_truncated():
    big = [dict(LOGS[0], message="x" * 2000) for _ in range(200)]
    llm = FakeLLM([json.dumps(DIAGNOSIS)])
    out = aa.analyze_debug_logs(big, config=_cfg(), client=llm)
    assert out["ok"] is True
    assert out["log_count"] < 200  # 总长超限截断
    assert any("仅送入" in n for n in out["notes"])
