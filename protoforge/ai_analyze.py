"""AI 调试排障（v1.13.4）：LLM 分析调试日志 → 结构化诊断，每条结论必须带出处。

与 v1.13.1 点表导入同一套 provider 抽象（AIConfig/AIClient，默认本地 Ollama，
OpenAI 兼容服务可切）。设计红线：**结论必须引用真实日志字段值作为证据**——
没有 evidence 的 finding 一律丢弃并记入 notes，禁止 LLM 编造出处。
"""

import json
import logging
from typing import Any

from protoforge.ai_extract import MAX_TEXT_CHARS, AIClient, AIConfig, _parse_json

logger = logging.getLogger(__name__)

CONFIDENCE_LEVELS = {"high", "medium", "low"}
MAX_FINDINGS = 10
_PER_ENTRY_CHARS = 500

_SYSTEM_PROMPT = """你是工业协议通信排障专家，正在分析 ProtoForge 仿真平台的调试日志。
每行日志是一条 JSON，字段含 timestamp/protocol/direction/device_id/event/message/detail 等。

只输出一个 JSON 对象，不要任何解释文字：
{
  "summary": "一句话总结发生了什么（或：链路正常）",
  "findings": [
    {"issue": "问题描述",
     "evidence": ["逐条出处：必须引用真实日志的时间戳+方向+设备+事件摘要"],
     "likely_cause": "最可能的根因",
     "suggested_fix": "建议动作（配置/代码/网络层面）",
     "confidence": "high|medium|low"}
  ],
  "notes": ["数据不足以判断之处"]
}
规则：
1. evidence 必须逐条引用真实存在的日志字段值，禁止编造日志或时间戳；
2. 懂协议语义：Modbus 异常码 0x01 非法功能 / 0x02 非法数据地址 / 0x03 非法数据值 /
   0x04 从站故障 / 0x0A 网关不可达；连接超时；从站无响应；CRC 错误；
   S7 CPU 拒绝；OPC-UA BadXxx；MQTT 认证失败等；
3. findings 按严重程度排序；链路正常则 findings 为空数组，summary 说明之。"""


def _compact_entry(entry: Any) -> str:
    if not isinstance(entry, dict):
        return str(entry)[:_PER_ENTRY_CHARS]
    return json.dumps(entry, ensure_ascii=False, default=str)[:_PER_ENTRY_CHARS]


def _normalize_findings(raw: Any, notes: list[str]) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        notes.append("LLM 未返回 findings 数组")
        return []
    findings: list[dict[str, Any]] = []
    for item in raw[:MAX_FINDINGS]:
        if not isinstance(item, dict):
            continue
        evidence = item.get("evidence")
        if not isinstance(evidence, list) or not [e for e in evidence if str(e).strip()]:
            # 出处红线：没有证据的结论直接丢弃
            notes.append(f"丢弃缺少 evidence 出处的结论: {str(item.get('issue', ''))[:60]}")
            continue
        confidence = str(item.get("confidence", "medium")).strip().lower()
        if confidence not in CONFIDENCE_LEVELS:
            notes.append(f"结论 {str(item.get('issue', ''))[:40]}: 非法置信度 {confidence!r}，回落 medium")
            confidence = "medium"
        findings.append({
            "issue": str(item.get("issue", "")).strip(),
            "evidence": [str(e) for e in evidence if str(e).strip()],
            "likely_cause": str(item.get("likely_cause", "")).strip(),
            "suggested_fix": str(item.get("suggested_fix", "")).strip(),
            "confidence": confidence,
        })
    if len(raw) > MAX_FINDINGS:
        notes.append(f"结论超过 {MAX_FINDINGS} 条，已截断")
    return findings


def analyze_debug_logs(logs: list[Any], question: str = "",
                       config: AIConfig | None = None,
                       client: AIClient | None = None) -> dict[str, Any]:
    """调试日志 → 结构化诊断。失败带 error 返回，绝不抛出。"""
    logs = [e for e in (logs or []) if e]
    if not logs:
        return {"ok": False, "error": "没有可分析的日志（先产生一些通信，或放宽过滤条件）"}

    lines: list[str] = []
    total = 0
    truncated = False
    for entry in logs:
        line = _compact_entry(entry)
        if total + len(line) > MAX_TEXT_CHARS:
            truncated = True
            break
        lines.append(line)
        total += len(line)

    user = (f"用户问题：{question.strip() or '分析这些调试日志，找出异常和根因'}\n\n"
            f"调试日志（每行一条 JSON，共 {len(lines)} 条）：\n" + "\n".join(lines))

    cfg = config or AIConfig()
    llm = client or AIClient(cfg)
    try:
        raw = llm.chat(_SYSTEM_PROMPT, user)
    except Exception as e:
        return {"ok": False,
                "error": f"LLM 服务不可达（{cfg.base_url}）：{type(e).__name__}: {e}",
                "hint": "本地 Ollama：先 `ollama serve` 再 `ollama pull " + cfg.model
                        + "`；或用 protoforge ai check 诊断"}

    obj, err = _parse_json(raw)
    if obj is None:
        try:
            raw2 = llm.chat("只输出合法 JSON 对象，不要任何其他文字。",
                            f"你上一次的输出无法解析（{err}）。重新输出正确的 JSON：\n{raw[:2000]}")
            obj, err2 = _parse_json(raw2)
        except Exception as e:
            return {"ok": False, "error": f"LLM 修复重试失败：{type(e).__name__}: {e}"}
        if obj is None:
            return {"ok": False, "error": f"LLM 输出无法解析为 JSON（{err2}）", "raw": raw[:800]}

    notes: list[str] = []
    if not isinstance(obj, dict):
        return {"ok": False, "error": "LLM 返回的 JSON 不是对象", "raw": raw[:800]}
    for n in obj.get("notes") or []:
        if isinstance(n, str) and n.strip():
            notes.append(f"LLM: {n.strip()}")

    diagnosis = {
        "summary": str(obj.get("summary", "")).strip() or "（LLM 未给出摘要）",
        "findings": _normalize_findings(obj.get("findings"), notes),
    }
    if truncated:
        notes.append(f"日志总量超限，仅送入前 {len(lines)} 条")
    return {"ok": True, "diagnosis": diagnosis, "model": cfg.model,
            "base_url": cfg.base_url, "log_count": len(lines), "notes": notes}
