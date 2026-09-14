"""Test plan management module.

Provides versioned, traceable test plan management for industrial protocol testing.
A test plan bundles test suites, device configs, and fault scenarios into a
repeatable execution unit.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class PlanStatus(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    ARCHIVED = "archived"


class RunStatus(str, Enum):
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    ERROR = "error"
    ABORTED = "aborted"


@dataclass
class TestPlan:
    """A versioned test plan."""

    id: str = ""
    name: str = ""
    version: str = "1.0.0"
    description: str = ""
    test_suite_ids: list[str] = field(default_factory=list)
    device_configs: list[dict[str, Any]] = field(default_factory=list)
    protocol_configs: list[dict[str, Any]] = field(default_factory=list)
    fault_scenarios: list[dict[str, Any]] = field(default_factory=list)
    schedule: dict[str, Any] = field(default_factory=dict)
    created_by: str = "admin"
    created_at: float = 0.0
    updated_at: float = 0.0
    status: str = "draft"

    def __post_init__(self):
        if not self.id:
            self.id = uuid.uuid4().hex[:12]
        if not self.created_at:
            self.created_at = time.time()
        if not self.updated_at:
            self.updated_at = self.created_at

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "test_suite_ids": self.test_suite_ids,
            "device_configs": self.device_configs,
            "protocol_configs": self.protocol_configs,
            "fault_scenarios": self.fault_scenarios,
            "schedule": self.schedule,
            "created_by": self.created_by,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TestPlan:
        return cls(
            id=data.get("id", ""),
            name=data.get("name", ""),
            version=data.get("version", "1.0.0"),
            description=data.get("description", ""),
            test_suite_ids=data.get("test_suite_ids", []),
            device_configs=data.get("device_configs", []),
            protocol_configs=data.get("protocol_configs", []),
            fault_scenarios=data.get("fault_scenarios", []),
            schedule=data.get("schedule", {}),
            created_by=data.get("created_by", "admin"),
            created_at=data.get("created_at", 0.0),
            updated_at=data.get("updated_at", 0.0),
            status=data.get("status", "draft"),
        )

    def clone(self, new_name: str | None = None) -> TestPlan:
        """Create a copy of this plan with a new ID."""
        data = self.to_dict()
        data["id"] = uuid.uuid4().hex[:12]
        data["name"] = new_name or f"{self.name} (Copy)"
        data["created_at"] = time.time()
        data["updated_at"] = time.time()
        data["status"] = "draft"
        return TestPlan.from_dict(data)


@dataclass
class TestRun:
    """A single execution of a test plan."""

    id: str = ""
    plan_id: str = ""
    plan_version: str = ""
    plan_name: str = ""
    plan_snapshot: dict[str, Any] = field(default_factory=dict)
    triggered_by: str = "manual"
    trigger_source: str = "manual"
    start_time: float = 0.0
    end_time: float = 0.0
    status: str = "running"
    environment: dict[str, Any] = field(default_factory=dict)
    results_summary: dict[str, Any] = field(default_factory=dict)
    report_data: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.id:
            self.id = uuid.uuid4().hex[:12]
        if not self.start_time:
            self.start_time = time.time()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "plan_id": self.plan_id,
            "plan_version": self.plan_version,
            "plan_name": self.plan_name,
            "plan_snapshot": self.plan_snapshot,
            "triggered_by": self.triggered_by,
            "trigger_source": self.trigger_source,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "status": self.status,
            "environment": self.environment,
            "results_summary": self.results_summary,
            "report_data": self.report_data,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TestRun:
        return cls(
            id=data.get("id", ""),
            plan_id=data.get("plan_id", ""),
            plan_version=data.get("plan_version", ""),
            plan_name=data.get("plan_name", ""),
            plan_snapshot=data.get("plan_snapshot", {}),
            triggered_by=data.get("triggered_by", "manual"),
            trigger_source=data.get("trigger_source", "manual"),
            start_time=data.get("start_time", 0.0),
            end_time=data.get("end_time", 0.0),
            status=data.get("status", "running"),
            environment=data.get("environment", {}),
            results_summary=data.get("results_summary", {}),
            report_data=data.get("report_data", {}),
        )


class TestPlanManager:
    """Manages test plans and execution history with database persistence."""

    def __init__(self):
        self._plans: dict[str, TestPlan] = {}
        self._runs: dict[str, TestRun] = {}
        self._db = None
        self._active_runs: dict[str, bool] = {}  # run_id -> abort flag

    def set_database(self, db) -> None:
        self._db = db

    # ── Plan CRUD ──────────────────────────────────────────────────────

    async def create_plan(self, plan: TestPlan) -> TestPlan:
        self._plans[plan.id] = plan
        if self._db:
            try:
                await self._db.save_test_plan(plan.to_dict())
            except Exception as e:
                logger.warning("Failed to persist test plan: %s", e)
        return plan

    async def update_plan(self, plan_id: str, updates: dict[str, Any]) -> TestPlan:
        plan = self._plans.get(plan_id)
        if not plan:
            raise ValueError(f"Test plan not found: {plan_id}")
        data = plan.to_dict()
        data.update(updates)
        data["updated_at"] = time.time()
        plan = TestPlan.from_dict(data)
        self._plans[plan_id] = plan
        if self._db:
            try:
                await self._db.save_test_plan(plan.to_dict())
            except Exception as e:
                logger.warning("Failed to persist test plan update: %s", e)
        return plan

    async def delete_plan(self, plan_id: str) -> bool:
        if plan_id not in self._plans:
            return False
        del self._plans[plan_id]
        if self._db:
            try:
                await self._db.delete_test_plan(plan_id)
            except Exception as e:
                logger.warning("Failed to delete test plan from DB: %s", e)
        return True

    def get_plan(self, plan_id: str) -> TestPlan | None:
        return self._plans.get(plan_id)

    def list_plans(self, status: str | None = None) -> list[TestPlan]:
        plans = list(self._plans.values())
        if status:
            plans = [p for p in plans if p.status == status]
        return sorted(plans, key=lambda p: p.updated_at, reverse=True)

    def clone_plan(self, plan_id: str, new_name: str | None = None) -> TestPlan:
        plan = self._plans.get(plan_id)
        if not plan:
            raise ValueError(f"Test plan not found: {plan_id}")
        cloned = plan.clone(new_name)
        self._plans[cloned.id] = cloned
        return cloned

    # ── Run Management ─────────────────────────────────────────────────

    def create_run(self, plan: TestPlan, triggered_by: str = "admin",
                   trigger_source: str = "manual") -> TestRun:
        run = TestRun(
            plan_id=plan.id,
            plan_version=plan.version,
            plan_name=plan.name,
            plan_snapshot=plan.to_dict(),
            triggered_by=triggered_by,
            trigger_source=trigger_source,
        )
        self._runs[run.id] = run
        self._active_runs[run.id] = False  # not aborted
        return run

    def update_run(self, run: TestRun) -> None:
        self._runs[run.id] = run
        if self._db:
            try:
                self._db._sync_execute_save_test_run(run.to_dict())
            except Exception as e:
                logger.debug("Failed to persist test run (async needed): %s", e)

    async def save_run(self, run: TestRun) -> None:
        self._runs[run.id] = run
        if self._db:
            try:
                await self._db.save_test_run(run.to_dict())
            except Exception as e:
                logger.warning("Failed to persist test run: %s", e)

    def get_run(self, run_id: str) -> TestRun | None:
        return self._runs.get(run_id)

    def list_runs(self, plan_id: str | None = None, limit: int = 20) -> list[TestRun]:
        runs = list(self._runs.values())
        if plan_id:
            runs = [r for r in runs if r.plan_id == plan_id]
        runs.sort(key=lambda r: r.start_time, reverse=True)
        return runs[:limit] if limit > 0 else runs

    def request_abort(self, run_id: str) -> bool:
        if run_id in self._active_runs:
            self._active_runs[run_id] = True  # mark for abort
            return True
        return False

    def is_aborted(self, run_id: str) -> bool:
        return self._active_runs.get(run_id, False)

    def clear_abort(self, run_id: str) -> None:
        self._active_runs.pop(run_id, None)

    # ── Load from DB ───────────────────────────────────────────────────

    async def load_from_db(self) -> None:
        if not self._db:
            return
        try:
            plans = await self._db.load_all_test_plans()
            for p in plans:
                plan = TestPlan.from_dict(p)
                self._plans[plan.id] = plan
            runs = await self._db.load_all_test_runs()
            for r in runs:
                run = TestRun.from_dict(r)
                self._runs[run.id] = run
            logger.info("Loaded %d test plans and %d runs from DB", len(plans), len(runs))
        except Exception as e:
            logger.warning("Failed to load test plans from DB: %s", e)
