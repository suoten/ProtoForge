"""ProtoForge Python SDK - 物联网协议仿真与测试 SDK"""

import json
import time
from typing import Any, Optional

import httpx


class ProtoForgeClient:
    def __init__(self, base_url: str = "http://localhost:8000", timeout: float = 30.0,
                 retries: int = 0, retry_delay: float = 1.0):
        self._base_url = base_url.rstrip("/")
        self._api_url = f"{self._base_url}/api/v1"
        self._retries = retries
        self._retry_delay = retry_delay
        self._client = httpx.Client(timeout=timeout)

    def close(self):
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        url = f"{self._api_url}{path}"
        last_error = None
        for attempt in range(self._retries + 1):
            try:
                resp = self._client.request(method, url, **kwargs)
                resp.raise_for_status()
                return resp
            except (httpx.ConnectError, httpx.TimeoutException) as e:
                last_error = e
                if attempt < self._retries:
                    time.sleep(self._retry_delay)
        raise last_error

    def _get(self, path: str, **kwargs) -> Any:
        resp = self._request("GET", path, **kwargs)
        return resp.json()

    def _post(self, path: str, **kwargs) -> Any:
        resp = self._request("POST", path, **kwargs)
        return resp.json()

    def _put(self, path: str, **kwargs) -> Any:
        resp = self._request("PUT", path, **kwargs)
        return resp.json()

    def _delete(self, path: str, **kwargs) -> Any:
        resp = self._request("DELETE", path, **kwargs)
        return resp.json()

    def health(self) -> dict:
        resp = self._client.get(f"{self._base_url}/health")
        resp.raise_for_status()
        return resp.json()

    def list_protocols(self) -> list:
        return self._get("/protocols")

    def start_protocol(self, name: str, config: dict | None = None) -> dict:
        return self._post(f"/protocols/{name}/start", json=config or {})

    def stop_protocol(self, name: str) -> dict:
        return self._post(f"/protocols/{name}/stop")

    def list_devices(self, protocol: str | None = None) -> list:
        params = {}
        if protocol:
            params["protocol"] = protocol
        return self._get("/devices", params=params)

    def create_device(self, device_id: str, name: str, protocol: str,
                      points: list[dict] | None = None,
                      template_id: str | None = None,
                      protocol_config: dict | None = None) -> dict:
        data = {
            "id": device_id,
            "name": name,
            "protocol": protocol,
            "points": points or [],
        }
        if template_id:
            data["template_id"] = template_id
        if protocol_config:
            data["protocol_config"] = protocol_config
        return self._post("/devices", json=data)

    def quick_create(self, template_id: str, name: str, device_id: str | None = None) -> dict:
        return self._post("/devices/quick-create", json={
            "template_id": template_id, "name": name, "id": device_id or name,
        })

    def start_device(self, device_id: str) -> dict:
        return self._post(f"/devices/{device_id}/start")

    def stop_device(self, device_id: str) -> dict:
        return self._post(f"/devices/{device_id}/stop")

    def get_device(self, device_id: str) -> dict:
        return self._get(f"/devices/{device_id}")

    def delete_device(self, device_id: str) -> dict:
        return self._delete(f"/devices/{device_id}")

    def read_points(self, device_id: str) -> list:
        return self._get(f"/devices/{device_id}/points")

    def write_point(self, device_id: str, point_name: str, value: Any) -> dict:
        return self._put(f"/devices/{device_id}/points/{point_name}", params={"value": value})

    def batch_create_devices(self, configs: list[dict]) -> dict:
        return self._post("/devices/batch", json=configs)

    def batch_delete_devices(self, device_ids: list[str]) -> dict:
        return self._request("DELETE", "/devices/batch", json=device_ids).json()

    def batch_start_devices(self, device_ids: list[str]) -> dict:
        return self._post("/devices/batch/start", json=device_ids)

    def batch_stop_devices(self, device_ids: list[str]) -> dict:
        return self._post("/devices/batch/stop", json=device_ids)

    def list_templates(self, protocol: str | None = None) -> list:
        params = {}
        if protocol:
            params["protocol"] = protocol
        return self._get("/templates", params=params)

    def get_template(self, template_id: str) -> dict:
        return self._get(f"/templates/{template_id}")

    def create_template(self, template: dict) -> dict:
        return self._post("/templates", json=template)

    def search_templates(self, q: str = "", protocol: str | None = None,
                         tag: str | None = None) -> list:
        params = {}
        if q:
            params["q"] = q
        if protocol:
            params["protocol"] = protocol
        if tag:
            params["tag"] = tag
        return self._get("/templates/search", params=params)

    def list_template_tags(self) -> list:
        return self._get("/templates/tags")

    def instantiate_template(self, template_id: str, device_id: str,
                             device_name: str, protocol_config: dict | None = None) -> dict:
        params = {"device_id": device_id, "device_name": device_name}
        if protocol_config:
            params["protocol_config"] = json.dumps(protocol_config)
        return self._post(f"/templates/{template_id}/instantiate", params=params)

    def list_scenarios(self) -> list:
        return self._get("/scenarios")

    def create_scenario(self, scenario_id: str, name: str,
                        description: str = "", devices: list | None = None,
                        rules: list | None = None) -> dict:
        data = {
            "id": scenario_id,
            "name": name,
            "description": description,
            "devices": devices or [],
            "rules": rules or [],
        }
        return self._post("/scenarios", json=data)

    def get_scenario(self, scenario_id: str) -> dict:
        return self._get(f"/scenarios/{scenario_id}")

    def start_scenario(self, scenario_id: str) -> dict:
        return self._post(f"/scenarios/{scenario_id}/start")

    def stop_scenario(self, scenario_id: str) -> dict:
        return self._post(f"/scenarios/{scenario_id}/stop")

    def export_scenario(self, scenario_id: str) -> dict:
        return self._get(f"/scenarios/{scenario_id}/export")

    def import_scenario(self, config: dict) -> dict:
        return self._post("/scenarios/import", json=config)

    def get_scenario_snapshot(self, scenario_id: str) -> dict:
        return self._get(f"/scenarios/{scenario_id}/snapshot")

    def get_logs(self, count: int = 100, protocol: str | None = None,
                 device_id: str | None = None) -> list:
        params = {"count": count}
        if protocol:
            params["protocol"] = protocol
        if device_id:
            params["device_id"] = device_id
        return self._get("/logs", params=params)

    def create_test_case(self, case_def: dict) -> dict:
        return self._post("/tests/cases", json=case_def)

    def list_test_cases(self, tag: str | None = None) -> list:
        params = {}
        if tag:
            params["tag"] = tag
        return self._get("/tests/cases", params=params)

    def get_test_case(self, case_id: str) -> dict:
        return self._get(f"/tests/cases/{case_id}")

    def update_test_case(self, case_id: str, case_def: dict) -> dict:
        return self._put(f"/tests/cases/{case_id}", json=case_def)

    def delete_test_case(self, case_id: str) -> dict:
        return self._delete(f"/tests/cases/{case_id}")

    def create_test_suite(self, suite_def: dict) -> dict:
        return self._post("/tests/suites", json=suite_def)

    def list_test_suites(self) -> list:
        return self._get("/tests/suites")

    def get_test_suite(self, suite_id: str) -> dict:
        return self._get(f"/tests/suites/{suite_id}")

    def delete_test_suite(self, suite_id: str) -> dict:
        return self._delete(f"/tests/suites/{suite_id}")

    def run_tests(self, test_cases: list[dict]) -> dict:
        return self._post("/tests/run", json=test_cases)

    def run_test_case(self, case_id: str) -> dict:
        return self._post(f"/tests/run/case/{case_id}")

    def run_test_suite(self, suite_id: str) -> dict:
        return self._post(f"/tests/run/suite/{suite_id}")

    def list_test_reports(self) -> list:
        return self._get("/tests/reports")

    def get_test_report(self, report_id: str) -> dict:
        return self._get(f"/tests/reports/{report_id}")

    def get_test_report_html(self, report_id: str) -> str:
        resp = self._request("GET", f"/tests/reports/{report_id}/html")
        return resp.text

    def get_report_trend(self, count: int = 20) -> list:
        return self._get("/tests/reports/trend", params={"count": count})

    def import_edgelite(self, config: dict) -> dict:
        return self._post("/integration/edgelite", json=config)

    def import_pygbsentry(self, config: dict) -> dict:
        return self._post("/integration/pygbsentry", json=config)

    def login(self, username: str, password: str) -> dict:
        resp = self._post("/auth/login", json={"username": username, "password": password})
        token = resp.get("access_token")
        if token:
            self._client.headers["Authorization"] = f"Bearer {token}"
        return resp

    def refresh_token(self, refresh_token: str) -> dict:
        return self._post("/auth/refresh", json={"refresh_token": refresh_token})

    def change_password(self, old_password: str, new_password: str) -> dict:
        return self._post("/auth/change-password", json={"old_password": old_password, "new_password": new_password})

    def list_forward_targets(self) -> list:
        return self._get("/forward/targets")

    def add_forward_target(self, target: dict) -> dict:
        return self._post("/forward/targets", json=target)

    def start_forward(self) -> dict:
        return self._post("/forward/start")

    def stop_forward(self) -> dict:
        return self._post("/forward/stop")

    def get_forward_stats(self) -> dict:
        return self._get("/forward/stats")

    def start_recording(self, protocol: str | None = None, device_id: str | None = None) -> dict:
        params = {}
        if protocol:
            params["protocol"] = protocol
        if device_id:
            params["device_id"] = device_id
        return self._post("/recorder/start", params=params)

    def stop_recording(self) -> dict:
        return self._post("/recorder/stop")

    def list_recordings(self) -> list:
        return self._get("/recorder/recordings")

    def get_recording(self, recording_id: str) -> dict:
        return self._get(f"/recorder/recordings/{recording_id}")

    def export_recording(self, recording_id: str) -> dict:
        return self._get(f"/recorder/recordings/{recording_id}/export")

    def get_settings(self) -> dict:
        return self._get("/settings")

    def update_settings(self, updates: dict) -> dict:
        return self._put("/settings", json=updates)


class AsyncProtoForgeClient:
    def __init__(self, base_url: str = "http://localhost:8000", timeout: float = 30.0,
                 retries: int = 0, retry_delay: float = 1.0):
        self._base_url = base_url.rstrip("/")
        self._api_url = f"{self._base_url}/api/v1"
        self._retries = retries
        self._retry_delay = retry_delay
        self._client = httpx.AsyncClient(timeout=timeout)

    async def close(self):
        await self._client.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()

    async def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        url = f"{self._api_url}{path}"
        last_error = None
        for attempt in range(self._retries + 1):
            try:
                resp = await self._client.request(method, url, **kwargs)
                resp.raise_for_status()
                return resp
            except (httpx.ConnectError, httpx.TimeoutException) as e:
                last_error = e
                if attempt < self._retries:
                    import asyncio
                    await asyncio.sleep(self._retry_delay)
        raise last_error

    async def _get(self, path: str, **kwargs) -> Any:
        resp = await self._request("GET", path, **kwargs)
        return resp.json()

    async def _post(self, path: str, **kwargs) -> Any:
        resp = await self._request("POST", path, **kwargs)
        return resp.json()

    async def _put(self, path: str, **kwargs) -> Any:
        resp = await self._request("PUT", path, **kwargs)
        return resp.json()

    async def _delete(self, path: str, **kwargs) -> Any:
        resp = await self._request("DELETE", path, **kwargs)
        return resp.json()

    async def health(self) -> dict:
        resp = await self._client.get(f"{self._base_url}/health")
        resp.raise_for_status()
        return resp.json()

    async def list_protocols(self) -> list:
        return await self._get("/protocols")

    async def list_devices(self, protocol: str | None = None) -> list:
        params = {}
        if protocol:
            params["protocol"] = protocol
        return await self._get("/devices", params=params)

    async def create_device(self, device_id: str, name: str, protocol: str,
                            points: list[dict] | None = None,
                            protocol_config: dict | None = None) -> dict:
        data = {"id": device_id, "name": name, "protocol": protocol, "points": points or []}
        if protocol_config:
            data["protocol_config"] = protocol_config
        return await self._post("/devices", json=data)

    async def quick_create(self, template_id: str, name: str, device_id: str | None = None) -> dict:
        return await self._post("/devices/quick-create", json={
            "template_id": template_id, "name": name, "id": device_id or name,
        })

    async def start_device(self, device_id: str) -> dict:
        return await self._post(f"/devices/{device_id}/start")

    async def stop_device(self, device_id: str) -> dict:
        return await self._post(f"/devices/{device_id}/stop")

    async def get_device(self, device_id: str) -> dict:
        return await self._get(f"/devices/{device_id}")

    async def delete_device(self, device_id: str) -> dict:
        return await self._delete(f"/devices/{device_id}")

    async def read_points(self, device_id: str) -> list:
        return await self._get(f"/devices/{device_id}/points")

    async def write_point(self, device_id: str, point_name: str, value: Any) -> dict:
        return await self._put(f"/devices/{device_id}/points/{point_name}", params={"value": value})

    async def batch_create_devices(self, configs: list[dict]) -> dict:
        return await self._post("/devices/batch", json=configs)

    async def batch_delete_devices(self, device_ids: list[str]) -> dict:
        resp = await self._request("DELETE", "/devices/batch", json=device_ids)
        return resp.json()

    async def list_templates(self, protocol: str | None = None) -> list:
        params = {}
        if protocol:
            params["protocol"] = protocol
        return await self._get("/templates", params=params)

    async def search_templates(self, q: str = "", protocol: str | None = None,
                               tag: str | None = None) -> list:
        params = {}
        if q:
            params["q"] = q
        if protocol:
            params["protocol"] = protocol
        if tag:
            params["tag"] = tag
        return await self._get("/templates/search", params=params)

    async def create_scenario(self, scenario_id: str, name: str,
                              description: str = "", devices: list | None = None,
                              rules: list | None = None) -> dict:
        data = {"id": scenario_id, "name": name, "description": description,
                "devices": devices or [], "rules": rules or []}
        return await self._post("/scenarios", json=data)

    async def start_scenario(self, scenario_id: str) -> dict:
        return await self._post(f"/scenarios/{scenario_id}/start")

    async def stop_scenario(self, scenario_id: str) -> dict:
        return await self._post(f"/scenarios/{scenario_id}/stop")

    async def get_scenario_snapshot(self, scenario_id: str) -> dict:
        return await self._get(f"/scenarios/{scenario_id}/snapshot")

    async def get_logs(self, count: int = 100, protocol: str | None = None,
                       device_id: str | None = None) -> list:
        params = {"count": count}
        if protocol:
            params["protocol"] = protocol
        if device_id:
            params["device_id"] = device_id
        return await self._get("/logs", params=params)

    async def create_test_case(self, case_def: dict) -> dict:
        return await self._post("/tests/cases", json=case_def)

    async def list_test_cases(self, tag: str | None = None) -> list:
        params = {}
        if tag:
            params["tag"] = tag
        return await self._get("/tests/cases", params=params)

    async def run_tests(self, test_cases: list[dict]) -> dict:
        return await self._post("/tests/run", json=test_cases)

    async def run_test_case(self, case_id: str) -> dict:
        return await self._post(f"/tests/run/case/{case_id}")

    async def run_test_suite(self, suite_id: str) -> dict:
        return await self._post(f"/tests/run/suite/{suite_id}")

    async def list_test_reports(self) -> list:
        return await self._get("/tests/reports")

    async def get_test_report(self, report_id: str) -> dict:
        return await self._get(f"/tests/reports/{report_id}")

    async def get_test_report_html(self, report_id: str) -> str:
        resp = await self._request("GET", f"/tests/reports/{report_id}/html")
        return resp.text

    async def get_report_trend(self, count: int = 20) -> list:
        return await self._get("/tests/reports/trend", params={"count": count})

    async def import_edgelite(self, config: dict) -> dict:
        return await self._post("/integration/edgelite", json=config)

    async def import_pygbsentry(self, config: dict) -> dict:
        return await self._post("/integration/pygbsentry", json=config)

    async def login(self, username: str, password: str) -> dict:
        resp = await self._post("/auth/login", json={"username": username, "password": password})
        token = resp.get("access_token")
        if token:
            self._client.headers["Authorization"] = f"Bearer {token}"
        return resp

    async def refresh_token(self, refresh_token: str) -> dict:
        return await self._post("/auth/refresh", json={"refresh_token": refresh_token})

    async def change_password(self, old_password: str, new_password: str) -> dict:
        return await self._post("/auth/change-password", json={"old_password": old_password, "new_password": new_password})

    async def start_protocol(self, name: str, config: dict | None = None) -> dict:
        return await self._post(f"/protocols/{name}/start", json=config or {})

    async def stop_protocol(self, name: str) -> dict:
        return await self._post(f"/protocols/{name}/stop")

    async def batch_start_devices(self, device_ids: list[str]) -> dict:
        return await self._post("/devices/batch/start", json=device_ids)

    async def batch_stop_devices(self, device_ids: list[str]) -> dict:
        return await self._post("/devices/batch/stop", json=device_ids)

    async def get_template(self, template_id: str) -> dict:
        return await self._get(f"/templates/{template_id}")

    async def create_template(self, template: dict) -> dict:
        return await self._post("/templates", json=template)

    async def list_template_tags(self) -> list:
        return await self._get("/templates/tags")

    async def instantiate_template(self, template_id: str, device_id: str,
                                   device_name: str, protocol_config: dict | None = None) -> dict:
        params = {"device_id": device_id, "device_name": device_name}
        if protocol_config:
            params["protocol_config"] = json.dumps(protocol_config)
        return await self._post(f"/templates/{template_id}/instantiate", params=params)

    async def list_scenarios(self) -> list:
        return await self._get("/scenarios")

    async def get_scenario(self, scenario_id: str) -> dict:
        return await self._get(f"/scenarios/{scenario_id}")

    async def export_scenario(self, scenario_id: str) -> dict:
        return await self._get(f"/scenarios/{scenario_id}/export")

    async def import_scenario(self, config: dict) -> dict:
        return await self._post("/scenarios/import", json=config)

    async def get_test_case(self, case_id: str) -> dict:
        return await self._get(f"/tests/cases/{case_id}")

    async def update_test_case(self, case_id: str, case_def: dict) -> dict:
        return await self._put(f"/tests/cases/{case_id}", json=case_def)

    async def delete_test_case(self, case_id: str) -> dict:
        return await self._delete(f"/tests/cases/{case_id}")

    async def create_test_suite(self, suite_def: dict) -> dict:
        return await self._post("/tests/suites", json=suite_def)

    async def list_test_suites(self) -> list:
        return await self._get("/tests/suites")

    async def get_test_suite(self, suite_id: str) -> dict:
        return await self._get(f"/tests/suites/{suite_id}")

    async def delete_test_suite(self, suite_id: str) -> dict:
        return await self._delete(f"/tests/suites/{suite_id}")

    async def list_forward_targets(self) -> list:
        return await self._get("/forward/targets")

    async def add_forward_target(self, target: dict) -> dict:
        return await self._post("/forward/targets", json=target)

    async def start_forward(self) -> dict:
        return await self._post("/forward/start")

    async def stop_forward(self) -> dict:
        return await self._post("/forward/stop")

    async def get_forward_stats(self) -> dict:
        return await self._get("/forward/stats")

    async def start_recording(self, protocol: str | None = None, device_id: str | None = None) -> dict:
        params = {}
        if protocol:
            params["protocol"] = protocol
        if device_id:
            params["device_id"] = device_id
        return await self._post("/recorder/start", params=params)

    async def stop_recording(self) -> dict:
        return await self._post("/recorder/stop")

    async def list_recordings(self) -> list:
        return await self._get("/recorder/recordings")

    async def get_recording(self, recording_id: str) -> dict:
        return await self._get(f"/recorder/recordings/{recording_id}")

    async def export_recording(self, recording_id: str) -> dict:
        return await self._get(f"/recorder/recordings/{recording_id}/export")

    async def get_settings(self) -> dict:
        return await self._get("/settings")

    async def update_settings(self, updates: dict) -> dict:
        return await self._put("/settings", json=updates)
