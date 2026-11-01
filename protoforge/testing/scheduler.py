"""定时测试调度器（v1.10.0）：测试计划 cron 落地。

每 30 秒扫描一遍带 ``schedule.cron`` 的测试计划，到点（``is_due`` 的
整分钟命中只触发一次）即执行并记录 ``schedule_last_run``，防止重启重复。
执行走 PlanRunner（与手动触发同一条链路），完成后经 notify 渠道推送。
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from protoforge.testing.cron_min import is_due, parse_cron

logger = logging.getLogger(__name__)

_SCAN_INTERVAL = 30.0


def plan_cron(plan) -> str:
    """取测试计划的 cron 表达式（schedule: {cron: "*/5 * * * *"}）。"""
    schedule = getattr(plan, "schedule", None) or {}
    return str(schedule.get("cron", "") or "").strip()


class TestPlanScheduler:
    def __init__(self, plan_manager, runner_factory, server_url: str = ""):
        """
        plan_manager: TestPlanManager（列出/读取计划 + 保存 schedule_last_run）
        runner_factory: async () -> PlanRunner（延迟取，避免循环依赖）
        """
        self._plan_manager = plan_manager
        self._runner_factory = runner_factory
        self._server_url = server_url
        self._task: asyncio.Task | None = None
        self._running = False
        self.last_dispatch: dict[str, str] = {}  # plan_id -> run_id

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._running = True
            self._task = asyncio.create_task(self._loop(), name="test-plan-scheduler")

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    @property
    def running(self) -> bool:
        return self._running

    async def _loop(self) -> None:
        logger.info("Test plan scheduler started (scan every %.0fs)", _SCAN_INTERVAL)
        while self._running:
            try:
                await self._scan_once()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.exception("scheduler scan error: %s", e)
            await asyncio.sleep(_SCAN_INTERVAL)

    def due_plans(self, now: float | None = None) -> list[Any]:
        """返回到点的计划（导出为方法便于测试注入时间）。"""
        now = now if now is not None else time.time()
        due: list[Any] = []
        for plan in self._plan_manager.list_plans():
            cron = plan_cron(plan)
            if not cron:
                continue
            try:
                parse_cron(cron)
            except ValueError as e:
                logger.warning("plan %s invalid cron %r: %s", plan.id, cron, e)
                continue
            last_run = float(getattr(plan, "schedule_last_run", 0.0) or 0.0)
            if is_due(cron, last_run, now):
                due.append(plan)
        return due

    async def _scan_once(self, now: float | None = None) -> list[str]:
        dispatched: list[str] = []
        for plan in self.due_plans(now):
            try:
                run_id = await self.dispatch_plan(plan, now=now)
                dispatched.append(run_id)
            except Exception as e:
                logger.exception("scheduled dispatch failed for %s: %s", plan.id, e)
        return dispatched

    async def dispatch_plan(self, plan, now: float | None = None) -> str:
        runner = await self._runner_factory()
        run = await runner.execute_plan(
            plan, triggered_by="scheduler", trigger_source="cron")
        # 记录触发时间（防重启重复）；写回持久层
        plan.schedule_last_run = now if now is not None else time.time()
        try:
            await self._plan_manager.update_plan(
                plan.id, {"schedule_last_run": plan.schedule_last_run})
        except Exception as e:
            logger.debug("persist schedule_last_run failed: %s", e)
        self.last_dispatch[plan.id] = run.id
        # 通知（失败不影响执行链路）
        try:
            from protoforge.testing.notify import notify_test_run
            await notify_test_run(run.to_dict(), self._server_url)
        except Exception as e:
            logger.warning("notify after scheduled run failed: %s", e)
        logger.info("scheduled plan %s fired -> run %s (%s)",
                    plan.id, run.id, run.status)
        return run.id
