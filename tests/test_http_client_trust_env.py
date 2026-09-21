"""Regression tests: all outbound httpx clients must bypass environment proxies.

System/environment proxies (HTTP_PROXY/HTTPS_PROXY/system proxy settings)
hijacked requests to loopback/intranet endpoints — failover peer health
checks, data forward targets, webhook delivery and EdgeLite integration
channels all returned 502 when a system proxy was on. Every outbound
``httpx.AsyncClient`` must be created with ``trust_env=False``.

We assert on ``client._trust_env`` (httpx stores the flag there); this is an
implementation detail of httpx but the only way to check the effective
setting without performing real network I/O through a proxy.
"""

from __future__ import annotations

import pytest

httpx = pytest.importorskip("httpx")


def _assert_no_env_proxy(client: httpx.AsyncClient, label: str) -> None:
    try:
        assert client._trust_env is False, (
            f"{label} must be created with trust_env=False (system proxy "
            f"hijacks loopback/intranet requests)"
        )
    finally:
        # 同步客户端可 aclose；事件循环外创建的客户端直接丢弃即可
        pass


class TestEdgeLiteHttpClient:
    def test_shared_client_bypasses_proxy(self):
        from protoforge.integrations.edgelite import _get_http_client

        client = _get_http_client()
        _assert_no_env_proxy(client, "edgelite._get_http_client")


class TestForwardTargets:
    @pytest.mark.asyncio
    async def test_http_target_bypasses_proxy(self):
        from protoforge.integrations.forward import HTTPTarget

        target = HTTPTarget(url="http://127.0.0.1:18099/hook")
        try:
            client = await target._ensure_client()
            _assert_no_env_proxy(client, "HTTPTarget")
        finally:
            if target._client is not None:
                await target._client.aclose()

    @pytest.mark.asyncio
    async def test_influxdb_target_bypasses_proxy(self):
        from protoforge.integrations.forward import InfluxDBTarget

        target = InfluxDBTarget(
            url="http://127.0.0.1:18086", token="t", org="o", bucket="b"
        )
        try:
            client = await target._ensure_client()
            _assert_no_env_proxy(client, "InfluxDBTarget")
        finally:
            if target._client is not None:
                await target._client.aclose()


class TestIntegrationLayer:
    def test_auth_client_bypasses_proxy(self):
        from protoforge.integrations.integration.auth import IntegrationAuth

        auth = IntegrationAuth(base_url="http://127.0.0.1:8000")
        _assert_no_env_proxy(auth._client, "IntegrationAuth")
