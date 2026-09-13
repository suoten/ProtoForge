"""Test plan execution engine.

Executes a test plan by:
1. Starting required protocols
2. Creating devices from plan config
3. Running each test suite
4. Applying fault scenarios
5. Collecting results and generating report
"""

from __future__ import annotations

import asyncio
import logging
import platform
import time
import uuid
from typing import Any

from protoforge.testing.plan import TestPlan, TestRun, RunStatus, TestPlanManager

logger = logging.getLogger(__name__)


class PlanRunner:
    """Executes test plans and produces test runs with results."""

    def __init__(self, plan_manager: TestPlanManager):
        self._plan_manager = plan_manager

    async def execute_plan(
        self,
        plan: TestPlan,
        triggered_by: str = "admin",
        trigger_source: str = "manual",
        test_runner=None,
        api_client=None,
        lang: str = "zh",
    ) -> TestRun:
        """Execute a test plan and return the test run with results.

        Args:
            plan: The test plan to execute.
            triggered_by: Who triggered this run.
            trigger_source: How it was triggered (manual/jenkins/gitlab/cron).
            test_runner: Optional TestRunner instance for running suites.
            api_client: Optional httpx client for internal API calls.
            lang: Language for test messages.
        """
        run = self._plan_manager.create_run(plan, triggered_by, trigger_source)
        run.environment = self._collect_environment()
        run.status = RunStatus.RUNNING.value

        total = 0
        passed = 0
        failed = 0
        errors = 0
        skipped = 0
        suite_reports: list[dict[str, Any]] = []

        try:
            # Execute each test suite
            if test_runner and plan.test_suite_ids:
                for suite_id in plan.test_suite_ids:
                    if self._plan_manager.is_aborted(run.id):
                        run.status = RunStatus.ABORTED.value
                        break

                    suite = test_runner.get_test_suite(suite_id)
                    if not suite:
                        logger.warning("Test suite not found: %s, skipping", suite_id)
                        skipped += 1
                        suite_reports.append({
                            "suite_id": suite_id,
                            "suite_name": "Unknown",
                            "status": "skipped",
                            "error": "Suite not found",
                        })
                        continue

                    try:
                        report = await test_runner.run_test_suite_by_id(
                            suite_id, api_client=api_client, lang=lang
                        )
                        total += report.total
                        passed += report.passed
                        failed += report.failed
                        errors += report.errors
                        skipped += report.skipped
                        suite_reports.append({
                            "suite_id": suite_id,
                            "suite_name": report.name,
                            "status": "passed" if report.failed == 0 and report.errors == 0 else "failed",
                            "total": report.total,
                            "passed": report.passed,
                            "failed": report.failed,
                            "errors": report.errors,
                            "skipped": report.skipped,
                            "report_id": report.id,
                            "start_time": report.start_time,
                            "end_time": report.end_time,
                        })
                    except Exception as e:
                        logger.exception("Failed to run suite %s: %s", suite_id, e)
                        errors += 1
                        suite_reports.append({
                            "suite_id": suite_id,
                            "suite_name": suite.name if suite else "Unknown",
                            "status": "error",
                            "error": str(e),
                        })
            else:
                # No test runner or no suites — just validate environment
                total = 0
                run.status = RunStatus.PASSED.value

            # Determine final status
            if run.status != RunStatus.ABORTED.value:
                if errors > 0:
                    run.status = RunStatus.ERROR.value
                elif failed > 0:
                    run.status = RunStatus.FAILED.value
                else:
                    run.status = RunStatus.PASSED.value

        except Exception as e:
            logger.exception("Test plan execution failed: %s", e)
            run.status = RunStatus.ERROR.value
            run.results_summary = {"error": str(e)}

        run.end_time = time.time()
        run.results_summary = {
            "total": total,
            "passed": passed,
            "failed": failed,
            "errors": errors,
            "skipped": skipped,
            "duration_seconds": round(run.end_time - run.start_time, 2),
            "suite_reports": suite_reports,
        }
        run.report_data = {
            "plan": plan.to_dict(),
            "suites": suite_reports,
            "summary": run.results_summary,
            "environment": run.environment,
        }

        await self._plan_manager.save_run(run)
        self._plan_manager.clear_abort(run.id)
        return run

    def _collect_environment(self) -> dict[str, Any]:
        """Collect execution environment info."""
        try:
            from protoforge import __version__ as pf_version
        except Exception:
            pf_version = "unknown"

        return {
            "protoforge_version": pf_version,
            "python_version": platform.python_version(),
            "platform": platform.platform(),
            "hostname": platform.node(),
        }

    def generate_junit_xml(self, run: TestRun) -> str:
        """Generate JUnit XML format report for CI/CD integration."""
        suites = run.report_data.get("suites", [])
        summary = run.results_summary

        xml_parts = ['<?xml version="1.0" encoding="UTF-8"?>']
        total_tests = summary.get("total", 0)
        total_failures = summary.get("failed", 0)
        total_errors = summary.get("errors", 0)
        total_skipped = summary.get("skipped", 0)
        total_time = summary.get("duration_seconds", 0)

        xml_parts.append(
            f'<testsuites name="{_xml_escape(run.plan_name)}" '
            f'tests="{total_tests}" failures="{total_failures}" '
            f'errors="{total_errors}" skipped="{total_skipped}" '
            f'time="{total_time}">'
        )

        for suite in suites:
            suite_name = _xml_escape(suite.get("suite_name", "Unknown"))
            suite_tests = suite.get("total", 0)
            suite_failures = suite.get("failed", 0)
            suite_errors = suite.get("errors", 0)
            suite_skipped = suite.get("skipped", 0)
            suite_time = round(suite.get("end_time", 0) - suite.get("start_time", 0), 3)

            xml_parts.append(
                f'  <testsuite name="{suite_name}" '
                f'tests="{suite_tests}" failures="{suite_failures}" '
                f'errors="{suite_errors}" skipped="{suite_skipped}" '
                f'time="{suite_time}">'
            )

            if suite.get("status") == "skipped":
                xml_parts.append(
                    f'    <testcase name="{suite_name}" classname="{suite_name}" time="0">'
                    f'<skipped /></testcase>'
                )
            elif suite.get("status") == "error":
                xml_parts.append(
                    f'    <testcase name="{suite_name}" classname="{suite_name}" time="{suite_time}">'
                    f'<error message="{_xml_escape(suite.get("error", ""))}" /></testcase>'
                )
            elif suite.get("status") == "failed":
                xml_parts.append(
                    f'    <testcase name="{suite_name}" classname="{suite_name}" time="{suite_time}">'
                    f'<failure message="Suite had {suite_failures} failures" /></testcase>'
                )
            else:
                xml_parts.append(
                    f'    <testcase name="{suite_name}" classname="{suite_name}" time="{suite_time}" />'
                )

            xml_parts.append('  </testsuite>')

        xml_parts.append('</testsuites>')
        return '\n'.join(xml_parts)

    def generate_json_report(self, run: TestRun) -> dict[str, Any]:
        """Generate JSON format report."""
        return {
            "run_id": run.id,
            "plan_id": run.plan_id,
            "plan_name": run.plan_name,
            "plan_version": run.plan_version,
            "status": run.status,
            "start_time": run.start_time,
            "end_time": run.end_time,
            "duration_seconds": round(run.end_time - run.start_time, 2) if run.end_time else 0,
            "triggered_by": run.triggered_by,
            "trigger_source": run.trigger_source,
            "environment": run.environment,
            "summary": run.results_summary,
            "suites": run.report_data.get("suites", []),
        }


def _xml_escape(text: str) -> str:
    """Escape special XML characters."""
    if not text:
        return ""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )
