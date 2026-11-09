"""AI 点表/说明书导入（v1.13.1）：LLM 吃非结构化文本 → 结构化设备配置。

Provider 走 OpenAI 兼容 chat completions 接口；本地 Ollama 原生暴露
`/v1/chat/completions` 与 `/v1/models`，零配置即可用（vLLM / LM Studio /
DeepSeek 等任何 OpenAI 兼容服务同样适用）：

    ollama pull qwen2.5:7b
    protoforge ai check

配置（环境变量）：
    PROTOFORGE_AI_BASE_URL  默认 http://localhost:11434/v1
    PROTOFORGE_AI_MODEL     默认 qwen2.5:7b
    PROTOFORGE_AI_API_KEY   可选（本地模型留空即可）
    PROTOFORGE_AI_TIMEOUT   默认 180 秒（本地大模型首次推理较慢）

设计：解析结果一律先返回结构化 JSON 供人工/AI 复核（notes 标注歧义），
`create-device-from-text` 才会真正建设备——识别 ≠ 落库，与 v1.7 点表导入
"粘贴 → 预览 → 确认" 的产品原则一致。
"""

import json
import logging
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "http://localhost:11434/v1"
DEFAULT_MODEL = "qwen2.5:7b"
DEFAULT_TIMEOUT = 180.0
MAX_TEXT_CHARS = 60_000
MAX_POINTS = 300

DATA_TYPES = {"bool", "int16", "uint16", "int32", "uint32",
              "float32", "float64", "string", "real"}
ACCESS_MODES = {"r", "w", "rw"}

_SYSTEM_PROMPT = """你是工业设备点表解析专家。从产品说明书/通信协议文档/寄存器表的原始文本中提取仿真设备配置，只输出一个 JSON 对象，不要输出任何解释文字：
{
  "name": "设备中文名",
  "protocol": "modbus_tcp|modbus_rtu|s7|mc|fins|ab|opcua|mqtt|http|iec104|iec61850|dlt645|cjt188|bacnet|coap|dds|gb28181|fanuc|mtconnect|toledo|profinet|ethercat|opcdc|custom_tcp|custom_udp 中最匹配的一个",
  "protocol_config": {"slave_id": 1},
  "points": [
    {"name": "snake_case 英文点名",
     "address": "寄存器地址（严格保留文档原写法，如 40001 / 0 / DB1.DBD0 / D100 / CV1）",
     "data_type": "bool|int16|uint16|int32|uint32|float32|float64|string|real 之一",
     "unit": "单位，缺失填空串",
     "access": "r|w|rw",
     "description": "中文含义"}
  ],
  "notes": ["无法确定或有歧义之处，逐条列出；没有则空数组"]
}
规则：
1. 只提取文档中明确出现的点位，不要编造；
2. address 必须原样保留文档写法，禁止换算偏移；
3. 分不清读写属性时 access 填 "r"；
4. 从站地址/单元号出现在文档中时写入 protocol_config.slave_id，否则 slave_id 填 1。"""


class AIConfig:
    """LLM 连接配置：参数 > 环境变量 > 内置默认（本地 Ollama）。"""

    def __init__(self, base_url: str | None = None, model: str | None = None,
                 api_key: str | None = None, timeout: float | None = None):
        self.base_url = (base_url or os.environ.get("PROTOFORGE_AI_BASE_URL")
                         or DEFAULT_BASE_URL).rstrip("/")
        self.model = model or os.environ.get("PROTOFORGE_AI_MODEL") or DEFAULT_MODEL
        self.api_key = (api_key if api_key is not None
                        else os.environ.get("PROTOFORGE_AI_API_KEY", ""))
        try:
            self.timeout = float(timeout or os.environ.get("PROTOFORGE_AI_TIMEOUT")
                                 or DEFAULT_TIMEOUT)
        except (TypeError, ValueError):
            self.timeout = DEFAULT_TIMEOUT


class AIClient:
    """OpenAI 兼容服务的极简同步客户端（不引入 openai SDK，httpx 直连）。"""

    def __init__(self, config: AIConfig | None = None):
        self.config = config or AIConfig()

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        return headers

    def chat(self, system: str, user: str) -> str:
        payload = {
            "model": self.config.model,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
            "temperature": 0,
            "stream": False,
        }
        r = httpx.post(f"{self.config.base_url}/chat/completions", json=payload,
                       headers=self._headers(), timeout=self.config.timeout)
        r.raise_for_status()
        data = r.json()
        return str(data["choices"][0]["message"]["content"])

    def list_models(self) -> list[str]:
        r = httpx.get(f"{self.config.base_url}/models", headers=self._headers(), timeout=15)
        r.raise_for_status()
        return [str(m.get("id", "")) for m in r.json().get("data", [])]


def _parse_json(text: str) -> tuple[Any, str | None]:
    """容忍 markdown 围栏与前后杂文：定位第一个 { 做平衡解析。失败返回 (None, 原因)。"""
    cleaned = text.strip()
    if "```" in cleaned:  # 去掉 ```json ... ``` 围栏
        parts = cleaned.split("```")
        for part in parts:
            part = part.strip()
            if part.startswith("json"):
                part = part[4:].strip()
            if part.startswith("{"):
                cleaned = part
                break
    start = cleaned.find("{")
    if start < 0:
        return None, "输出中找不到 JSON 对象"
    try:
        obj, _ = json.JSONDecoder().raw_decode(cleaned[start:])
        return obj, None
    except json.JSONDecodeError as e:
        return None, f"JSON 解析失败: {e}"


def _normalize_points(raw_points: Any, notes: list[str]) -> list[dict[str, Any]]:
    if not isinstance(raw_points, list):
        notes.append("LLM 未返回 points 数组")
        return []
    points: list[dict[str, Any]] = []
    for item in raw_points[:MAX_POINTS]:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        address = str(item.get("address", "")).strip()
        if not name or not address:
            notes.append(f"丢弃缺少 name/address 的点: {json.dumps(item, ensure_ascii=False)[:80]}")
            continue
        data_type = str(item.get("data_type", "float32")).strip().lower()
        if data_type not in DATA_TYPES:
            notes.append(f"点 {name}: 未知数据类型 {data_type!r}，回落 float32")
            data_type = "float32"
        access = str(item.get("access", "r")).strip().lower()
        if access not in ACCESS_MODES:
            notes.append(f"点 {name}: 非法 access {access!r}，回落 r")
            access = "r"
        points.append({
            "name": name,
            "address": address,
            "data_type": data_type,
            "unit": str(item.get("unit", "")).strip(),
            "access": access,
            "description": str(item.get("description", "")).strip(),
            "generator_type": "fixed",  # 说明书导入默认固定值，避免假装"真实变化"
        })
    if len(raw_points) > MAX_POINTS:
        notes.append(f"点数超过上限，截断至 {MAX_POINTS}")
    return points


def _normalize_device(obj: dict[str, Any], protocol_hint: str,
                      notes: list[str]) -> dict[str, Any]:
    protocol = (protocol_hint or str(obj.get("protocol", "")).strip() or "modbus_tcp").strip()
    protocol_config = obj.get("protocol_config")
    if not isinstance(protocol_config, dict) or not protocol_config:
        slave_id = obj.get("slave_id", 1)
        try:
            slave_id = int(slave_id)
        except (TypeError, ValueError):
            slave_id = 1
        protocol_config = {"slave_id": slave_id}
    return {
        "name": str(obj.get("name", "")).strip() or "AI导入设备",
        "protocol": protocol,
        "protocol_config": protocol_config,
        "points": _normalize_points(obj.get("points"), notes),
    }


def extract_device_config(text: str, protocol_hint: str = "",
                          config: AIConfig | None = None,
                          client: AIClient | None = None) -> dict[str, Any]:
    """说明书/寄存器表原文 → 结构化设备配置。失败带 error 返回，绝不抛出。"""
    text = (text or "").strip()
    if not text:
        return {"ok": False, "error": "文本为空"}
    truncated = False
    if len(text) > MAX_TEXT_CHARS:
        text = text[:MAX_TEXT_CHARS]
        truncated = True

    cfg = config or AIConfig()
    llm = client or AIClient(cfg)
    try:
        raw = llm.chat(_SYSTEM_PROMPT,
                       f"目标协议提示：{protocol_hint or '自动判断'}\n\n文档原文：\n{text}")
    except Exception as e:
        return {"ok": False, "error": f"LLM 服务不可达（{cfg.base_url}）：{type(e).__name__}: {e}",
                "hint": "本地 Ollama：先 `ollama serve` 再 `ollama pull "
                        + cfg.model + "`；或用 protoforge ai check 诊断"}

    obj, err = _parse_json(raw)
    if obj is None:
        # 一次修复重试：把失败原因喂回去
        try:
            raw2 = llm.chat("只输出合法 JSON 对象，不要任何其他文字。",
                            f"你上一次的输出无法解析（{err}）。重新输出正确的 JSON：\n{raw[:2000]}")
            obj, err2 = _parse_json(raw2)
        except Exception as e:
            return {"ok": False, "error": f"LLM 修复重试失败：{type(e).__name__}: {e}"}
        if obj is None:
            return {"ok": False, "error": f"LLM 输出无法解析为 JSON（{err2}）",
                    "raw": raw[:800]}

    notes: list[str] = []
    if not isinstance(obj, dict):
        return {"ok": False, "error": "LLM 返回的 JSON 不是对象", "raw": raw[:800]}
    for n in obj.get("notes") or []:
        if isinstance(n, str) and n.strip():
            notes.append(f"LLM: {n.strip()}")
    device = _normalize_device(obj, protocol_hint, notes)
    if truncated:
        notes.append(f"输入文本超长，已截断至 {MAX_TEXT_CHARS} 字符")
    if not device["points"]:
        notes.append("未能提取到任何有效点位——检查文档是否包含寄存器表")
    return {"ok": True, "device": device, "model": cfg.model,
            "base_url": cfg.base_url, "point_count": len(device["points"]),
            "notes": notes}
