"""Unit tests for the multi-device collaboration engine.

Covers: condition evaluation, action types (set/toggle/increment/decrement/delay),
chain execution, cooldown suppression, disabled rules, and read-failure handling.
Uses in-memory callbacks — no engine or DB required.
"""

from __future__ import annotations

import asyncio
import time

import pytest

from protoforge.simulation.collaboration import (
    CollaborationAction,
    CollaborationRule,
    DeviceCollaboration,
    evaluate_condition,
)


# ---------------------------------------------------------------------------
#  In-memory device store for testing
# ---------------------------------------------------------------------------


class FakeDeviceStore:
    """Minimal in-memory device point store with async write / sync read."""

    def __init__(self, initial: dict[str, dict[str, object]] | None = None):
        self.data: dict[str, dict[str, object]] = {}
        for dev_id, pts in (initial or {}).items():
            self.data[dev_id] = dict(pts)
        self.write_log: list[tuple[str, str, object]] = []

    def read(self, device_id: str, point_name: str):
        return self.data.get(device_id, {}).get(point_name)

    async def write(self, device_id: str, point_name: str, value) -> bool:
        self.data.setdefault(device_id, {})[point_name] = value
        self.write_log.append((device_id, point_name, value))
        return True


def _make_collab(store: FakeDeviceStore) -> DeviceCollaboration:
    return DeviceCollaboration(on_write_point=store.write, on_read_point=store.read)


# ---------------------------------------------------------------------------
#  Condition evaluation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("value,op,target,expected", [
    (90, ">", 80, True),
    (70, ">", 80, False),
    (80, ">=", 80, True),
    (79, ">=", 80, False),
    (80, "==", 80, True),
    (81, "==", 80, False),
    (81, "!=", 80, True),
    (30, "between", [10, 50], True),
    (60, "between", [10, 50], False),
    (2, "in", [1, 2, 3], True),
    (5, "in", [1, 2, 3], False),
    (5, "not_in", [1, 2, 3], True),
    (None, ">", 80, False),  # None value never satisfies ordered comparison
])
def test_evaluate_condition_operators(value, op, target, expected):
    assert evaluate_condition(value, {"operator": op, "value": target}) is expected


def test_evaluate_condition_empty_and_unknown():
    assert evaluate_condition(50, {}) is False
    assert evaluate_condition(50, {"operator": "weird", "value": 1}) is False


# ---------------------------------------------------------------------------
#  Action types
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_set_action_writes_value():
    store = FakeDeviceStore({"temp": {"temperature": 90}, "fan": {"speed": 0}})
    collab = _make_collab(store)
    collab.add_rule(CollaborationRule(
        id="r1", source_device_id="temp", source_point="temperature",
        condition={"operator": ">", "value": 80},
        actions=[CollaborationAction(target_device_id="fan", target_point="speed", action_type="set", value=100)],
    ))

    triggered = await collab.tick()

    assert triggered == 1
    assert store.data["fan"]["speed"] == 100


@pytest.mark.asyncio
async def test_toggle_action_flips_bool():
    store = FakeDeviceStore({"sensor": {"alarm": True}, "light": {"on": False}})
    collab = _make_collab(store)
    collab.add_rule(CollaborationRule(
        id="r-toggle", source_device_id="sensor", source_point="alarm",
        condition={"operator": "==", "value": True},
        actions=[CollaborationAction(target_device_id="light", target_point="on", action_type="toggle")],
    ))

    await collab.tick()
    assert store.data["light"]["on"] is True  # False → True

    # Flip source back to False, then True again to re-trigger
    store.data["sensor"]["alarm"] = True
    store.data["light"]["on"] = True
    await collab.tick()
    assert store.data["light"]["on"] is False  # True → False


@pytest.mark.asyncio
async def test_increment_and_decrement_actions():
    store = FakeDeviceStore({"src": {"val": 5}, "counter": {"n": 10}})
    collab = _make_collab(store)
    collab.add_rule(CollaborationRule(
        id="r-inc", source_device_id="src", source_point="val",
        condition={"operator": "==", "value": 5},
        actions=[
            CollaborationAction(target_device_id="counter", target_point="n", action_type="increment", value=3),
            CollaborationAction(target_device_id="counter", target_point="n", action_type="decrement"),
        ],
    ))

    await collab.tick()
    # 10 + 3 = 13, then 13 - 1 = 12
    assert store.data["counter"]["n"] == 12


@pytest.mark.asyncio
async def test_increment_defaults_to_step_one():
    store = FakeDeviceStore({"src": {"val": 1}, "ctr": {"n": 0}})
    collab = _make_collab(store)
    collab.add_rule(CollaborationRule(
        id="r-def", source_device_id="src", source_point="val",
        condition={"operator": "==", "value": 1},
        actions=[CollaborationAction(target_device_id="ctr", target_point="n", action_type="increment")],
    ))

    await collab.tick()
    assert store.data["ctr"]["n"] == 1  # 0 + default step 1


# ---------------------------------------------------------------------------
#  Chain with delay
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chain_with_delay_action():
    store = FakeDeviceStore({"src": {"val": 1}, "tgt": {"a": 0, "b": 0}})
    collab = _make_collab(store)
    collab.add_rule(CollaborationRule(
        id="r-chain", source_device_id="src", source_point="val",
        condition={"operator": "==", "value": 1},
        actions=[
            CollaborationAction(target_device_id="tgt", target_point="a", action_type="set", value=10),
            CollaborationAction(target_device_id="tgt", target_point="b", action_type="set", value=20, delay=0.05),
        ],
    ))

    start = time.time()
    await collab.tick()
    elapsed = time.time() - start

    assert store.data["tgt"]["a"] == 10
    assert store.data["tgt"]["b"] == 20
    assert elapsed >= 0.04  # delay was honored


@pytest.mark.asyncio
async def test_pure_delay_action_does_not_write():
    store = FakeDeviceStore({"src": {"val": 1}, "tgt": {"a": 0}})
    collab = _make_collab(store)
    collab.add_rule(CollaborationRule(
        id="r-pure-delay", source_device_id="src", source_point="val",
        condition={"operator": "==", "value": 1},
        actions=[
            CollaborationAction(target_device_id="tgt", target_point="a", action_type="delay", delay=0.01),
            CollaborationAction(target_device_id="tgt", target_point="a", action_type="set", value=5),
        ],
    ))

    await collab.tick()
    # delay action writes nothing; only the set action writes
    assert store.data["tgt"]["a"] == 5
    assert len(store.write_log) == 1


# ---------------------------------------------------------------------------
#  Cooldown
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cooldown_suppresses_rapid_retrigger():
    store = FakeDeviceStore({"src": {"val": 100}, "tgt": {"n": 0}})
    collab = _make_collab(store)
    collab.add_rule(CollaborationRule(
        id="r-cooldown", source_device_id="src", source_point="val",
        condition={"operator": ">", "value": 50},
        actions=[CollaborationAction(target_device_id="tgt", target_point="n", action_type="increment")],
        cooldown=1.0,  # 1 second cooldown
    ))

    # First tick: triggers
    t1 = await collab.tick()
    assert t1 == 1
    assert store.data["tgt"]["n"] == 1

    # Immediate second tick: suppressed by cooldown
    t2 = await collab.tick()
    assert t2 == 0
    assert store.data["tgt"]["n"] == 1  # unchanged

    # After cooldown passes: triggers again
    await asyncio.sleep(1.05)
    t3 = await collab.tick()
    assert t3 == 1
    assert store.data["tgt"]["n"] == 2


# ---------------------------------------------------------------------------
#  Edge cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_disabled_rule_not_triggered():
    store = FakeDeviceStore({"src": {"val": 100}, "tgt": {"n": 0}})
    collab = _make_collab(store)
    collab.add_rule(CollaborationRule(
        id="r-disabled", source_device_id="src", source_point="val",
        condition={"operator": ">", "value": 50},
        actions=[CollaborationAction(target_device_id="tgt", target_point="n", action_type="set", value=99)],
        enabled=False,
    ))

    triggered = await collab.tick()
    assert triggered == 0
    assert store.data["tgt"]["n"] == 0


@pytest.mark.asyncio
async def test_condition_not_met_does_not_trigger():
    store = FakeDeviceStore({"src": {"val": 30}, "tgt": {"n": 0}})
    collab = _make_collab(store)
    collab.add_rule(CollaborationRule(
        id="r-not-met", source_device_id="src", source_point="val",
        condition={"operator": ">", "value": 50},
        actions=[CollaborationAction(target_device_id="tgt", target_point="n", action_type="set", value=99)],
    ))

    triggered = await collab.tick()
    assert triggered == 0
    assert store.data["tgt"]["n"] == 0


@pytest.mark.asyncio
async def test_read_none_does_not_trigger():
    store = FakeDeviceStore({"src": {}, "tgt": {"n": 0}})  # src has no point value
    collab = _make_collab(store)
    collab.add_rule(CollaborationRule(
        id="r-none", source_device_id="src", source_point="missing",
        condition={"operator": ">", "value": 50},
        actions=[CollaborationAction(target_device_id="tgt", target_point="n", action_type="set", value=99)],
    ))

    triggered = await collab.tick()
    assert triggered == 0


@pytest.mark.asyncio
async def test_remove_rule():
    store = FakeDeviceStore({"src": {"val": 100}, "tgt": {"n": 0}})
    collab = _make_collab(store)
    collab.add_rule(CollaborationRule(
        id="r-remove", source_device_id="src", source_point="val",
        condition={"operator": ">", "value": 50},
        actions=[CollaborationAction(target_device_id="tgt", target_point="n", action_type="set", value=1)],
    ))

    assert len(collab.rules) == 1
    collab.remove_rule("r-remove")
    assert len(collab.rules) == 0
    triggered = await collab.tick()
    assert triggered == 0


@pytest.mark.asyncio
async def test_multiple_rules_independent():
    store = FakeDeviceStore({
        "s1": {"v": 100}, "s2": {"v": 10},
        "t1": {"n": 0}, "t2": {"n": 0},
    })
    collab = _make_collab(store)
    collab.add_rule(CollaborationRule(
        id="r1", source_device_id="s1", source_point="v",
        condition={"operator": ">", "value": 50},
        actions=[CollaborationAction(target_device_id="t1", target_point="n", action_type="set", value=1)],
    ))
    collab.add_rule(CollaborationRule(
        id="r2", source_device_id="s2", source_point="v",
        condition={"operator": "<", "value": 20},
        actions=[CollaborationAction(target_device_id="t2", target_point="n", action_type="set", value=2)],
    ))

    triggered = await collab.tick()
    assert triggered == 2  # both rules triggered
    assert store.data["t1"]["n"] == 1
    assert store.data["t2"]["n"] == 2
