#!/usr/bin/env python3
"""ProtoForge E2E Smoke Test Script.

Starts the ProtoForge server, waits for it to be ready, then tests
all critical API endpoints to verify the application is functioning
correctly end-to-end.

Usage:
    python scripts/smoke_test.py [--host HOST] [--port PORT]

Exit codes:
    0 - All smoke tests passed
    1 - One or more smoke tests failed
    2 - Server failed to start
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx

# Default settings
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 18000  # Use non-default port to avoid conflicts
STARTUP_TIMEOUT = 30  # seconds
REQUEST_TIMEOUT = 10  # seconds


def wait_for_server(base_url: str, timeout: int = STARTUP_TIMEOUT) -> bool:
    """Wait for the server to respond to health checks."""
    start = time.time()
    while time.time() - start < timeout:
        try:
            resp = httpx.get(f"{base_url}/health", timeout=2)
            if resp.status_code == 200:
                return True
        except (httpx.ConnectError, httpx.TimeoutException):
            pass
        time.sleep(0.5)
    return False


def run_smoke_tests(base_url: str) -> tuple[int, int]:
    """Run smoke tests against the running server.

    Returns (passed, failed) counts.
    """
    passed = 0
    failed = 0
    client = httpx.Client(base_url=base_url, timeout=REQUEST_TIMEOUT)

    tests = [
        ("GET /health", "GET", "/health", 200, None),
        ("GET /api/v1/health", "GET", "/api/v1/health", 200, None),
        ("GET / (root page)", "GET", "/", 200, None),
        ("GET /api/v1/protocols", "GET", "/api/v1/protocols", 200, None),
        ("GET /api/v1/templates", "GET", "/api/v1/templates", 200, None),
        ("GET /api/v1/devices", "GET", "/api/v1/devices", 200, None),
        ("GET /api/v1/logs", "GET", "/api/v1/logs", 200, None),
        ("GET /api/v1/protocols/info", "GET", "/api/v1/protocols/info", 200, None),
    ]

    for name, method, path, expected_status, json_body in tests:
        try:
            if method == "GET":
                resp = client.get(path)
            elif method == "POST":
                resp = client.post(path, json=json_body)
            elif method == "DELETE":
                resp = client.delete(path)

            if resp.status_code == expected_status:
                print(f"  ✅ {name} → {resp.status_code}")
                passed += 1
            else:
                print(f"  ❌ {name} → {resp.status_code} (expected {expected_status})")
                failed += 1
        except Exception as e:
            print(f"  ❌ {name} → ERROR: {e}")
            failed += 1

    # Test device CRUD
    try:
        device_config = {
            "id": "smoke-test-device",
            "name": "smoke-test",
            "protocol": "modbus_tcp",
            "points": [
                {
                    "name": "temperature",
                    "address": "0",
                    "data_type": "float32",
                    "unit": "C",
                    "generator_type": "random",
                    "min_value": 15.0,
                    "max_value": 35.0,
                }
            ],
        }
        resp = client.post("/api/v1/devices", json=device_config)
        if resp.status_code == 200:
            print(f"  ✅ POST /api/v1/devices (create) → {resp.status_code}")
            passed += 1
        else:
            print(f"  ❌ POST /api/v1/devices (create) → {resp.status_code}")
            failed += 1

        resp = client.get("/api/v1/devices/smoke-test-device")
        if resp.status_code == 200:
            print(f"  ✅ GET /api/v1/devices/{{id}} (read) → {resp.status_code}")
            passed += 1
        else:
            print(f"  ❌ GET /api/v1/devices/{{id}} (read) → {resp.status_code}")
            failed += 1

        resp = client.get("/api/v1/devices/smoke-test-device/points")
        if resp.status_code == 200:
            print(f"  ✅ GET /api/v1/devices/{{id}}/points → {resp.status_code}")
            passed += 1
        else:
            print(f"  ❌ GET /api/v1/devices/{{id}}/points → {resp.status_code}")
            failed += 1

        resp = client.delete("/api/v1/devices/smoke-test-device")
        if resp.status_code == 200:
            print(f"  ✅ DELETE /api/v1/devices/{{id}} (delete) → {resp.status_code}")
            passed += 1
        else:
            print(f"  ❌ DELETE /api/v1/devices/{{id}} (delete) → {resp.status_code}")
            failed += 1
    except Exception as e:
        print(f"  ❌ Device CRUD → ERROR: {e}")
        failed += 4

    # Test scenario CRUD
    try:
        scenario_config = {
            "id": "smoke-test-scenario",
            "name": "smoke-scenario",
            "description": "smoke test",
            "devices": [],
            "rules": [],
        }
        resp = client.post("/api/v1/scenarios", json=scenario_config)
        if resp.status_code == 200:
            print(f"  ✅ POST /api/v1/scenarios (create) → {resp.status_code}")
            passed += 1
        else:
            print(f"  ❌ POST /api/v1/scenarios (create) → {resp.status_code}")
            failed += 1

        resp = client.get("/api/v1/scenarios/smoke-test-scenario/export")
        if resp.status_code == 200:
            print(f"  ✅ GET /api/v1/scenarios/{{id}}/export → {resp.status_code}")
            passed += 1
        else:
            print(f"  ❌ GET /api/v1/scenarios/{{id}}/export → {resp.status_code}")
            failed += 1
    except Exception as e:
        print(f"  ❌ Scenario CRUD → ERROR: {e}")
        failed += 2

    client.close()
    return passed, failed


def main():
    parser = argparse.ArgumentParser(description="ProtoForge E2E Smoke Test")
    parser.add_argument("--host", default=DEFAULT_HOST, help=f"Host (default: {DEFAULT_HOST})")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"Port (default: {DEFAULT_PORT})")
    parser.add_argument("--no-start", action="store_true", help="Don't start server (use existing)")
    args = parser.parse_args()

    base_url = f"http://{args.host}:{args.port}"

    proc = None
    try:
        if not args.no_start:
            # Set environment for test server
            env = os.environ.copy()
            env["PROTOFORGE_NO_AUTH"] = "1"
            env["PROTOFORGE_DEMO_MODE"] = "1"
            env["PROTOFORGE_DB_PATH"] = "data/smoke_test.db"
            env["PROTOFORGE_PORT"] = str(args.port)
            env["PROTOFORGE_HOST"] = args.host
            env["PROTOFORGE_LOG_LEVEL"] = "warning"
            env["PROTOFORGE_JWT_SECRET"] = "smoke-test-secret-key"
            env["PROTOFORGE_ADMIN_PASSWORD"] = "smoke-test-admin"

            print(f"Starting ProtoForge server on {args.host}:{args.port}...")
            proc = subprocess.Popen(
                [sys.executable, "-m", "protoforge.cli", "demo"],
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=str(Path(__file__).parent.parent),
            )

            # Wait for server to be ready
            if not wait_for_server(base_url):
                print("❌ Server failed to start within timeout")
                if proc:
                    proc.terminate()
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                return 2

            print(f"✅ Server started successfully on {base_url}")

        print("\nRunning smoke tests...")
        print("-" * 60)

        passed, failed = run_smoke_tests(base_url)

        print("-" * 60)
        print(f"Results: {passed} passed, {failed} failed")

        if failed == 0:
            print("\n🎉 All smoke tests passed!")
            return 0
        else:
            print(f"\n⚠️  {failed} smoke test(s) failed")
            return 1

    finally:
        if proc:
            print("\nShutting down server...")
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
            print("✅ Server stopped")


if __name__ == "__main__":
    sys.exit(main())
