"""AI 点表导入单元测试 — Fake LLM 客户端，不依赖真实 Ollama（v1.13.1）。"""

import json

from protoforge import ai_extract as ae

VALID = {
    "name": "多功能电表",
    "protocol": "modbus_tcp",
    "protocol_config": {"slave_id": 2},
    "points": [
        {"name": "voltage_a", "address": "40001", "data_type": "float32",
         "unit": "V", "access": "r", "description": "A相电压"},
        {"name": "switch_state", "address": "00001", "data_type": "bool",
         "unit": "", "access": "rw", "description": "开关状态"},
    ],
    "notes": ["功率因数单位存疑"],
}


class FakeLLM:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def chat(self, system, user):
        self.calls.append((system, user))
        return self.responses.pop(0)


def _cfg():
    return ae.AIConfig(base_url="http://llm.test", model="test-model", timeout=5)


def test_extract_basic():
    out = ae.extract_device_config(" dummy ", config=_cfg(), client=FakeLLM([json.dumps(VALID)]))
    assert out["ok"] is True
    dev = out["device"]
    assert dev["name"] == "多功能电表"
    assert dev["protocol"] == "modbus_tcp"
    assert dev["protocol_config"] == {"slave_id": 2}
    assert out["point_count"] == 2
    assert dev["points"][0]["generator_type"] == "fixed"  # 说明书导入默认固定值
    assert "功率因数单位存疑" in " ".join(out["notes"])  # LLM 自身的 notes 被合并保留


def test_protocol_hint_overrides_llm_choice():
    data = dict(VALID, protocol="iec104")
    out = ae.extract_device_config("x", protocol_hint="modbus_tcp",
                                   config=_cfg(), client=FakeLLM([json.dumps(data)]))
    assert out["device"]["protocol"] == "modbus_tcp"  # 显式提示优先


def test_markdown_fence_stripped():
    raw = "```json\n" + json.dumps(VALID) + "\n```"
    out = ae.extract_device_config("x", config=_cfg(), client=FakeLLM([raw]))
    assert out["ok"] is True and out["point_count"] == 2


def test_repair_retry_on_invalid_json():
    llm = FakeLLM(["这不是 JSON，是一段散文。", json.dumps(VALID)])
    out = ae.extract_device_config("x", config=_cfg(), client=llm)
    assert out["ok"] is True
    assert len(llm.calls) == 2  # 首次 + 修复重试


def test_unparseable_after_repair():
    llm = FakeLLM(["nope", "still nope"])
    out = ae.extract_device_config("x", config=_cfg(), client=llm)
    assert out["ok"] is False
    assert "无法解析" in out["error"]


def test_llm_unreachable_hint():
    class Boom:
        def chat(self, system, user):
            raise ConnectionError("refused")

    out = ae.extract_device_config("x", config=_cfg(), client=Boom())
    assert out["ok"] is False
    assert "ollama" in out.get("hint", "").lower()


def test_missing_address_dropped_and_type_fallback():
    data = {"name": "dev", "protocol": "", "points": [
        {"name": "good", "address": "40001", "data_type": "float32"},
        {"name": "no_addr", "data_type": "float32"},
        {"address": "1", "data_type": "int16"},
        {"name": "weird", "address": "2", "data_type": "double_crazy"},
    ]}
    out = ae.extract_device_config("x", config=_cfg(), client=FakeLLM([json.dumps(data)]))
    pts = out["device"]["points"]
    assert out["point_count"] == 2  # 无 name / 无 address 的被丢弃
    assert {p["name"] for p in pts} == {"good", "weird"}
    assert pts[1]["data_type"] == "float32"  # 未知类型回落
    assert any("丢弃" in n for n in out["notes"])
    assert out["device"]["protocol"] == "modbus_tcp"  # 空协议回落默认
    assert out["device"]["protocol_config"] == {"slave_id": 1}


def test_empty_text():
    out = ae.extract_device_config("   ", config=_cfg(), client=FakeLLM([]))
    assert out["ok"] is False and "为空" in out["error"]


def test_long_text_truncated():
    llm = FakeLLM([json.dumps(VALID)])
    out = ae.extract_device_config("字" * (ae.MAX_TEXT_CHARS + 5000),
                                   config=_cfg(), client=llm)
    assert out["ok"] is True
    assert any("截断" in n for n in out["notes"])
    assert len(llm.calls[0][1]) <= ae.MAX_TEXT_CHARS + 100


def test_config_from_env(monkeypatch):
    monkeypatch.setenv("PROTOFORGE_AI_BASE_URL", "http://10.0.0.8:8000/v1/")
    monkeypatch.setenv("PROTOFORGE_AI_MODEL", "glm-4")
    monkeypatch.setenv("PROTOFORGE_AI_API_KEY", "sk-x")
    cfg = ae.AIConfig()
    assert cfg.base_url == "http://10.0.0.8:8000/v1"  # 尾斜杠被规范
    assert cfg.model == "glm-4"
    assert cfg.api_key == "sk-x"


def test_config_defaults(monkeypatch):
    for k in ("PROTOFORGE_AI_BASE_URL", "PROTOFORGE_AI_MODEL",
              "PROTOFORGE_AI_API_KEY", "PROTOFORGE_AI_TIMEOUT"):
        monkeypatch.delenv(k, raising=False)
    cfg = ae.AIConfig()
    assert cfg.base_url == ae.DEFAULT_BASE_URL
    assert cfg.model == ae.DEFAULT_MODEL
