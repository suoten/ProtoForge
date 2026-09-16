"""Rule chain API routes — visual DAG-based rule orchestration."""

import logging
import uuid
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException

from protoforge.api.v1._helpers import _get_engine
from protoforge.api.v1.auth import require_operator, require_viewer
from protoforge.engine.rule_chain import ChainEdge, ChainNode, RuleChain, RuleChainEngine

router = APIRouter()
logger = logging.getLogger(__name__)

_chain_engine: RuleChainEngine | None = None


def _get_chain_engine() -> RuleChainEngine:
    global _chain_engine
    if _chain_engine is None:
        _chain_engine = RuleChainEngine()
    return _chain_engine


@router.get("/rule-chains")
async def list_rule_chains(_user: dict[str, Any] = Depends(require_viewer)):
    engine = _get_chain_engine()
    return {"chains": engine.list_chains(), "stats": engine.get_stats()}


@router.post("/rule-chains")
async def create_rule_chain(chain: dict[str, Any] = Body(...),
                            _user: dict[str, Any] = Depends(require_operator)):
    engine = _get_chain_engine()
    chain_id = chain.get("id") or f"chain-{uuid.uuid4().hex[:8]}"
    name = chain.get("name", chain_id)
    description = chain.get("description", "")
    nodes = [ChainNode(**n) for n in chain.get("nodes", [])]
    edges = [ChainEdge(**e) for e in chain.get("edges", [])]
    enabled = chain.get("enabled", True)
    trigger_interval = chain.get("trigger_interval", 1.0)

    rc = RuleChain(
        id=chain_id, name=name, description=description,
        nodes=nodes, edges=edges, enabled=enabled,
        trigger_interval=trigger_interval,
    )
    engine.add_chain(rc)
    return {"status": "ok", "id": chain_id}


@router.get("/rule-chains/{chain_id}")
async def get_rule_chain(chain_id: str, _user: dict[str, Any] = Depends(require_viewer)):
    engine = _get_chain_engine()
    chain = engine.get_chain(chain_id)
    if not chain:
        raise HTTPException(status_code=404, detail=f"Rule chain not found: {chain_id}")
    return chain.model_dump()


@router.put("/rule-chains/{chain_id}")
async def update_rule_chain(chain_id: str, chain: dict[str, Any] = Body(...),
                            _user: dict[str, Any] = Depends(require_operator)):
    engine = _get_chain_engine()
    existing = engine.get_chain(chain_id)
    if not existing:
        raise HTTPException(status_code=404, detail=f"Rule chain not found: {chain_id}")
    nodes = [ChainNode(**n) for n in chain.get("nodes", existing.nodes)]
    edges = [ChainEdge(**e) for e in chain.get("edges", existing.edges)]
    updated = RuleChain(
        id=chain_id,
        name=chain.get("name", existing.name),
        description=chain.get("description", existing.description),
        nodes=nodes,
        edges=edges,
        enabled=chain.get("enabled", existing.enabled),
        trigger_interval=chain.get("trigger_interval", existing.trigger_interval),
    )
    engine.add_chain(updated)
    return {"status": "ok"}


@router.delete("/rule-chains/{chain_id}")
async def delete_rule_chain(chain_id: str, _user: dict[str, Any] = Depends(require_operator)):
    engine = _get_chain_engine()
    engine.remove_chain(chain_id)
    return {"status": "ok"}


@router.post("/rule-chains/{chain_id}/start")
async def start_rule_chain(chain_id: str, _user: dict[str, Any] = Depends(require_operator)):
    engine = _get_chain_engine()
    chain = engine.get_chain(chain_id)
    if not chain:
        raise HTTPException(status_code=404, detail=f"Rule chain not found: {chain_id}")
    chain.enabled = True
    if not engine._running:
        await engine.start()
    return {"status": "ok"}


@router.post("/rule-chains/{chain_id}/stop")
async def stop_rule_chain(chain_id: str, _user: dict[str, Any] = Depends(require_operator)):
    engine = _get_chain_engine()
    chain = engine.get_chain(chain_id)
    if not chain:
        raise HTTPException(status_code=404, detail=f"Rule chain not found: {chain_id}")
    chain.enabled = False
    return {"status": "ok"}


@router.get("/rule-chains/templates")
async def list_chain_templates(_user: dict[str, Any] = Depends(require_viewer)):
    """List pre-built rule chain templates."""
    templates = [
        {
            "id": "temp-control",
            "name": "温度控制链",
            "description": "温度超阈值 → 启动风扇 → 记录日志",
            "nodes": [
                {"id": "n1", "type": "source", "config": {"device_id": "", "point": "temperature"}},
                {"id": "n2", "type": "filter", "config": {"operator": ">", "value": 80}},
                {"id": "n3", "type": "action", "config": {"action": "set", "device_id": "", "point": "speed", "value": 100}},
                {"id": "n4", "type": "sink", "config": {"sink_type": "alert"}},
            ],
            "edges": [
                {"from": "n1", "to": "n2"},
                {"from": "n2", "to": "n3"},
                {"from": "n3", "to": "n4"},
            ],
        },
        {
            "id": "pressure-safety",
            "name": "压力安全链",
            "description": "压力超阈值 → 打开泄压阀 → 延迟 → 关闭泄压阀",
            "nodes": [
                {"id": "n1", "type": "source", "config": {"device_id": "", "point": "pressure"}},
                {"id": "n2", "type": "filter", "config": {"operator": ">", "value": 2.5}},
                {"id": "n3", "type": "action", "config": {"action": "set", "device_id": "", "point": "valve", "value": 1}},
                {"id": "n4", "type": "delay", "config": {"delay": 30}},
                {"id": "n5", "type": "action", "config": {"action": "set", "device_id": "", "point": "valve", "value": 0}},
                {"id": "n6", "type": "sink", "config": {"sink_type": "log"}},
            ],
            "edges": [
                {"from": "n1", "to": "n2"},
                {"from": "n2", "to": "n3"},
                {"from": "n3", "to": "n4"},
                {"from": "n4", "to": "n5"},
                {"from": "n5", "to": "n6"},
            ],
        },
        {
            "id": "data-pipeline",
            "name": "数据管道链",
            "description": "读取数据 → 缩放 → 钳位 → 写入目标点位",
            "nodes": [
                {"id": "n1", "type": "source", "config": {"device_id": "", "point": ""}},
                {"id": "n2", "type": "transform", "config": {"transform": "scale", "factor": 1.5}},
                {"id": "n3", "type": "transform", "config": {"transform": "clamp", "min": 0, "max": 100}},
                {"id": "n4", "type": "action", "config": {"action": "set", "device_id": "", "point": "", "value": 0}},
            ],
            "edges": [
                {"from": "n1", "to": "n2"},
                {"from": "n2", "to": "n3"},
                {"from": "n3", "to": "n4"},
            ],
        },
    ]
    return {"templates": templates}
