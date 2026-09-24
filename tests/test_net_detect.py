"""Regression for Issue #15: VPN FakeIP virtual adapter hijacks LAN IP detection.

Scenario: user runs Clash/Surge — the VPN creates a utun adapter (198.18.0.1,
RFC 2544 FakeIP range) and routes the default gateway through it. The legacy
"UDP connect 8.8.8.8" detection returned the FakeIP, so addresses reported to
EdgeLite gateways (and OPC-UA endpoint broadcasts) were unreachable.

The new detector enumerates hostname-associated addresses first (real NICs),
excludes virtual/reserved ranges, and filters the UDP fallback result too.
"""

import asyncio
import os
import socket

os.environ["PROTOFORGE_NO_AUTH"] = "1"

import pytest

from protoforge.core.netutils import detect_lan_ip, is_usable_lan_ip


# ---------------------------------------------------------------------------
# is_usable_lan_ip: virtual/reserved ranges must be rejected
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("ip,expected", [
    ("198.18.0.1", False),      # FakeIP (Clash/Surge) — the exact address from Issue #15
    ("198.19.255.255", False),  # FakeIP range end
    ("100.64.1.2", False),      # CGNAT (Tailscale etc.)
    ("169.254.10.5", False),    # link-local
    ("127.0.0.1", False),       # loopback
    ("224.0.0.1", False),       # multicast
    ("0.0.0.0", False),         # unspecified
    ("192.168.1.23", True),     # real LAN
    ("10.32.50.21", True),      # real LAN (user's subnet)
    ("172.20.1.5", True),       # private 172.16/12
])
def test_usable_lan_ip_ranges(ip, expected):
    assert is_usable_lan_ip(ip) is expected


def test_usable_lan_ip_invalid():
    assert is_usable_lan_ip("not-an-ip") is False
    assert is_usable_lan_ip("") is False


# ---------------------------------------------------------------------------
# detect_lan_ip: hostname enumeration path
# ---------------------------------------------------------------------------

def _fake_getaddrinfo(results):
    """Build a socket.getaddrinfo replacement returning [(AF_INET, ..., (ip, 0))]."""
    def fake(host, port, family=0, type=0, proto=0, flags=0):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0)) for ip in results]
    return fake


def test_detect_skips_vpn_fakeip(monkeypatch):
    """Hostname resolves to both the VPN FakeIP and the real NIC — must pick the real one."""
    monkeypatch.setattr(
        socket, "getaddrinfo",
        _fake_getaddrinfo(["198.18.0.1", "192.168.1.23"]),
    )
    assert detect_lan_ip() == "192.168.1.23"


def test_detect_prefers_192168_over_10(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo(["10.32.50.21", "192.168.1.23"]))
    assert detect_lan_ip() == "192.168.1.23"


def test_detect_10_when_no_192168(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo(["172.20.1.5", "10.32.50.21"]))
    assert detect_lan_ip() == "10.32.50.21"


def test_detect_all_virtual_returns_empty(monkeypatch):
    """Only VPN-range candidates → must NOT report them (caller falls back)."""
    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo(["198.18.0.1"]))
    # UDP fallback also returns the FakeIP → filtered → empty
    class FakeSock:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def settimeout(self, t):
            pass

        def connect(self, addr):
            self._local = ("198.18.0.1", 0)

        def getsockname(self):
            return self._local

    monkeypatch.setattr(socket, "socket", lambda *a, **k: FakeSock())
    assert detect_lan_ip() == ""


# ---------------------------------------------------------------------------
# UDP fallback path
# ---------------------------------------------------------------------------

def test_detect_udp_fallback_usable(monkeypatch):
    """No hostname addresses; UDP route detection returns a real LAN IP."""
    def raising_getaddrinfo(*a, **k):
        raise OSError("no hostname")

    monkeypatch.setattr(socket, "getaddrinfo", raising_getaddrinfo)

    class FakeSock:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def settimeout(self, t):
            pass

        def connect(self, addr):
            self._local = ("192.168.50.4", 0)

        def getsockname(self):
            return self._local

    monkeypatch.setattr(socket, "socket", lambda *a, **k: FakeSock())
    assert detect_lan_ip() == "192.168.50.4"


# ---------------------------------------------------------------------------
# get_protoforge_host integration
# ---------------------------------------------------------------------------

def test_get_protoforge_host_skips_fakeip(monkeypatch):
    """EdgeLite 回调地址上报：VPN FakeIP 不再被当成回调地址。"""
    from protoforge.integrations import edgelite

    class FakeSettings:
        protoforge_public_host = ""
        host = "0.0.0.0"

    monkeypatch.setattr(edgelite, "get_settings", lambda: FakeSettings())
    monkeypatch.setattr(
        socket, "getaddrinfo",
        _fake_getaddrinfo(["198.18.0.1", "10.32.50.21"]),
    )
    assert edgelite.get_protoforge_host() == "10.32.50.21"


def test_get_protoforge_host_public_override(monkeypatch):
    """PROTOFORGE_PUBLIC_HOST 配置优先于自动探测。"""
    from protoforge.integrations import edgelite

    class FakeSettings:
        protoforge_public_host = "192.168.88.88"
        host = "0.0.0.0"

    monkeypatch.setattr(edgelite, "get_settings", lambda: FakeSettings())

    def must_not_call(*a, **k):
        raise AssertionError("detect_lan_ip should not run when public host is set")

    monkeypatch.setattr("protoforge.core.netutils.detect_lan_ip", must_not_call)
    assert edgelite.get_protoforge_host() == "192.168.88.88"
