"""AI 点表导入 API（v1.13.1）：LLM 解析说明书文本 → 设备配置 / 一键建设备。

POST /ai/extract-points          {text, protocol_hint?} → 结构化配置（不落库）
POST /ai/create-device-from-text {text, name?, device_id?, protocol_hint?} → 创建+自动启动

LLM 默认本地 Ollama（OpenAI 兼容 /v1），配置见 protoforge/ai_extract.py。
创建走 device_routes.create_device 同一管道（校验/落库/回滚/webhook 完全一致）。
"""

import logging
import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import ValidationError

from protoforge.ai_extract import MAX_TEXT_CHARS, extract_device_config
from protoforge.api.v1.auth import require_operator
from protoforge.models.device import DeviceConfig

router = APIRouter()
logger = logging.getLogger(__name__)


def _do_extract(body: dict[str, Any]) -> dict[str, Any]:
    text = str(body.get("text", "")).strip()
    if not text:
        raise HTTPException(status_code=400, detail="text 不能为空")
    if len(text) > MAX_TEXT_CHARS:
        raise HTTPException(status_code=400,
                            detail=f"text 超长（>{MAX_TEXT_CHARS} 字符），请先分段")
    result = extract_device_config(text, protocol_hint=str(body.get("protocol_hint", "")))
    if not result.get("ok"):
        raise HTTPException(status_code=502, detail=result.get("error", "LLM 解析失败"),
                            headers={"X-ProtoForge-AI-Hint": str(result.get("hint", ""))})
    return result


@router.post("/ai/extract-points")
async def extract_points(body: dict[str, Any],
                         _user: dict[str, Any] = Depends(require_operator)):
    """解析说明书/寄存器表文本为设备配置 JSON（仅返回，不创建设备）。"""
    return _do_extract(body)


@router.post("/ai/create-device-from-text")
async def create_device_from_text(body: dict[str, Any],
                                  _user: dict[str, Any] = Depends(require_operator)):
    """一步到位：LLM 解析文本 → 创建并自动启动仿真设备（复用 /devices 创建管道）。"""
    # 延迟导入避免循环依赖（device_routes 不依赖本模块）
    from protoforge.api.v1.device_routes import create_device as _create_device_route

    result = _do_extract(body)
    device = result["device"]
    name = str(body.get("name", "")).strip() or device["name"]
    device_id = str(body.get("device_id", "")).strip() or (
        "ai-" + re.sub(r"[^a-zA-Z0-9_-]+", "-", name).strip("-").lower()[:40]
        or f"ai-{int(__import__('time').time())}")

    config = DeviceConfig(
        id=device_id,
        name=name,
        protocol=device["protocol"],
        points=device["points"],
        protocol_config=device.get("protocol_config") or {},
    )
    try:
        resp = await _create_device_route(config, _user=_user)
    except ValidationError as e:
        raise HTTPException(status_code=400,
                            detail=f"LLM 提取结果未通过设备配置校验：{e}") from e
    return {"ok": True, "device": resp, "device_id": device_id,
            "point_count": len(device["points"]), "model": result.get("model"),
            "notes": result.get("notes", [])}
