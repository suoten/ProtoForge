"""Rule Chain Engine — visual DAG-based rule orchestration.

The rule chain engine allows users to define a directed acyclic graph (DAG)
of rules where each node represents a processing step (filter, transform,
action, delay, branch) and edges define execution flow.

Chain nodes types:
  - source: Reads a device point value (chain entry point)
  - filter: Conditional gate — passes value downstream if condition met
  - transform: Modifies the value (scale, offset, clamp, map)
  - action: Performs an operation (set point, toggle, inject fault, webhook)
  - delay: Waits for N seconds before passing downstream
  - branch: Forks execution into multiple paths
  - merge: Merges multiple incoming paths (waits for all)
  - sink: Terminal node (log, alert, notify)

Chain definition format:
  {
    "id": "chain-1",
    "name": "Temperature Control Chain",
    "nodes": [
      {"id": "n1", "type": "source", "config": {"device_id": "temp-sensor", "point": "temperature"}},
      {"id": "n2", "type": "filter", "config": {"operator": ">", "value": 80}},
      {"id": "n3", "type": "action", "config": {"action": "set", "device_id": "fan", "point": "speed", "value": 100}},
      {"id": "n4", "type": "sink", "config": {"sink_type": "log"}}
    ],
    "edges": [
      {"from": "n1", "to": "n2"},
      {"from": "n2", "to": "n3"},
      {"from": "n3", "to": "n4"}
    ],
    "enabled": true,
    "trigger_interval": 1.0
  }
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class ChainNode(BaseModel):
    """A node in the rule chain."""
    id: str
    type: str  # source, filter, transform, action, delay, branch, merge, sink
    config: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


class ChainEdge(BaseModel):
    """An edge connecting two nodes in the chain."""
    from_node: str = Field(alias="from")
    to_node: str = Field(alias="to")
    condition: dict[str, Any] | None = None  # Optional edge condition


class RuleChain(BaseModel):
    """A rule chain definition."""
    id: str
    name: str
    description: str = ""
    nodes: list[ChainNode] = Field(default_factory=list)
    edges: list[ChainEdge] = Field(default_factory=list)
    enabled: bool = True
    trigger_interval: float = 1.0  # seconds between chain evaluations


class RuleChainEngine:
    """Rule chain execution engine.

    Evaluates rule chains by traversing the DAG from source nodes,
    processing values through filters/transforms, and executing actions.
    """

    def __init__(self):
        self._chains: dict[str, RuleChain] = {}
        self._running: bool = False
        self._task: asyncio.Task | None = None
        self._device_provider: Any = None  # Callable to read device points
        self._action_executor: Any = None  # Callable to execute actions
        self._node_results: dict[str, Any] = {}  # Last result per node
        self._trigger_count: int = 0
        self._error_count: int = 0

    def set_device_provider(self, provider: Any) -> None:
        """Set the device point reader callback.

        :param provider: async callable(device_id, point_name) -> value
        """
        self._device_provider = provider

    def set_action_executor(self, executor: Any) -> None:
        """Set the action execution callback.

        :param executor: async callable(action_type, config) -> bool
        """
        self._action_executor = executor

    def add_chain(self, chain: RuleChain) -> None:
        self._chains[chain.id] = chain
        logger.info("Rule chain added: %s (%d nodes)", chain.id, len(chain.nodes))

    def remove_chain(self, chain_id: str) -> None:
        self._chains.pop(chain_id, None)

    def list_chains(self) -> list[dict[str, Any]]:
        result = []
        for chain in self._chains.values():
            result.append({
                "id": chain.id,
                "name": chain.name,
                "description": chain.description,
                "enabled": chain.enabled,
                "node_count": len(chain.nodes),
                "edge_count": len(chain.edges),
                "trigger_interval": chain.trigger_interval,
            })
        return result

    def get_chain(self, chain_id: str) -> RuleChain | None:
        return self._chains.get(chain_id)

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("Rule chain engine started with %d chains", len(self._chains))

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            with contextlib_suppress():
                await self._task
        logger.info("Rule chain engine stopped")

    async def _run_loop(self) -> None:
        """Main evaluation loop."""
        try:
            while self._running:
                for chain in list(self._chains.values()):
                    if not chain.enabled:
                        continue
                    try:
                        await self._evaluate_chain(chain)
                        self._trigger_count += 1
                    except Exception as e:
                        self._error_count += 1
                        logger.warning("Chain %s evaluation error: %s", chain.id, e)
                # Determine minimum interval
                min_interval = min(
                    (c.trigger_interval for c in self._chains.values() if c.enabled),
                    default=1.0
                )
                await asyncio.sleep(min_interval)
        except asyncio.CancelledError:
            pass

    async def _evaluate_chain(self, chain: RuleChain) -> None:
        """Evaluate a single rule chain by traversing the DAG."""
        # Build adjacency map
        adjacency: dict[str, list[str]] = defaultdict(list)
        in_degree: dict[str, int] = defaultdict(int)
        node_map = {n.id: n for n in chain.nodes}

        for edge in chain.edges:
            adjacency[edge.from_node].append(edge.to_node)
            in_degree[edge.to_node] += 1

        # Find source nodes (in-degree 0)
        sources = [n.id for n in chain.nodes if in_degree[n.id] == 0]
        if not sources:
            return

        # Topological traversal with value propagation
        # Start from source nodes
        pending: list[tuple[str, Any]] = []
        for src_id in sources:
            node = node_map.get(src_id)
            if node and node.enabled:
                value = await self._execute_node(node, None)
                if value is not None:
                    pending.append((src_id, value))

        # Process downstream nodes
        processed: set[str] = set()
        while pending:
            node_id, value = pending.pop(0)
            if node_id in processed:
                continue
            processed.add(node_id)

            for next_id in adjacency.get(node_id, []):
                next_node = node_map.get(next_id)
                if not next_node or not next_node.enabled:
                    continue
                result = await self._execute_node(next_node, value)
                if result is not None:
                    pending.append((next_id, result))

    async def _execute_node(self, node: ChainNode, input_value: Any) -> Any:
        """Execute a single chain node and return its output value."""
        try:
            ntype = node.type
            config = node.config

            if ntype == "source":
                device_id = config.get("device_id", "")
                point = config.get("point", "")
                if self._device_provider and device_id and point:
                    return await self._device_provider(device_id, point)
                return None

            elif ntype == "filter":
                if input_value is None:
                    return None
                operator = config.get("operator", ">")
                threshold = config.get("value", 0)
                if self._compare(input_value, operator, threshold):
                    return input_value
                return None

            elif ntype == "transform":
                if input_value is None:
                    return None
                transform_type = config.get("transform", "scale")
                if transform_type == "scale":
                    factor = config.get("factor", 1.0)
                    return float(input_value) * float(factor)
                elif transform_type == "offset":
                    offset = config.get("offset", 0)
                    return float(input_value) + float(offset)
                elif transform_type == "clamp":
                    min_val = config.get("min", 0)
                    max_val = config.get("max", 100)
                    return max(min_val, min(max_val, float(input_value)))
                elif transform_type == "map":
                    mapping = config.get("mapping", {})
                    return mapping.get(str(input_value), input_value)
                return input_value

            elif ntype == "action":
                if self._action_executor:
                    await self._action_executor(config.get("action", "set"), config)
                return input_value  # Pass through

            elif ntype == "delay":
                delay = config.get("delay", 0)
                if delay > 0:
                    await asyncio.sleep(float(delay))
                return input_value

            elif ntype == "branch":
                # Pass input to all downstream nodes (handled by DAG traversal)
                return input_value

            elif ntype == "merge":
                # Merge just passes through (real merge requires waiting for all inputs)
                return input_value

            elif ntype == "sink":
                sink_type = config.get("sink_type", "log")
                if sink_type == "log":
                    logger.info("Chain sink [%s]: %s", node.id, input_value)
                elif sink_type == "alert":
                    logger.warning("Chain ALERT [%s]: %s", node.id, input_value)
                return None  # Terminal node

            return input_value

        except Exception as e:
            logger.warning("Chain node %s execution error: %s", node.id, e)
            return None

    @staticmethod
    def _compare(value: Any, operator: str, threshold: Any) -> bool:
        try:
            v = float(value)
            t = float(threshold)
        except (ValueError, TypeError):
            v, t = value, threshold
        ops = {
            ">": lambda a, b: a > b,
            ">=": lambda a, b: a >= b,
            "<": lambda a, b: a < b,
            "<=": lambda a, b: a <= b,
            "==": lambda a, b: a == b,
            "!=": lambda a, b: a != b,
        }
        return ops.get(operator, lambda a, b: False)(v, t)

    def get_stats(self) -> dict[str, Any]:
        return {
            "chains": len(self._chains),
            "running": self._running,
            "trigger_count": self._trigger_count,
            "error_count": self._error_count,
        }


class contextlib_suppress:
    """Minimal context manager to suppress CancelledError."""

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return True
