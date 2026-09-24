"""Network utilities: LAN IP detection that skips VPN/FakeIP virtual adapters.

传统探测方式（``UDP connect 8.8.8.8`` 后读 ``getsockname()``）依赖默认路由。
VPN 工具（Clash/Surge 等）会把默认路由指向 utun/TUN 虚拟网卡，此时探测返回
的是 FakeIP 网段（198.18.x.x，RFC 2544 保留段）等虚拟地址——上报给网关/广播
给客户端的地址因此不可达（Issue #15）。

这里改为优先枚举与本机主机名关联的地址（通常只含真实物理网卡），
过滤虚拟/保留网段后按局域网段优先级选择；UDP 探测仅作为回退且结果同样过滤。
"""

import ipaddress
import logging
import socket

logger = logging.getLogger(__name__)

# 不应作为"对外可达的本机地址"的网段：
#   198.18.0.0/15  — RFC 2544 基准测试保留段，Clash/Surge 等 VPN 的 FakeIP 常用段
#   100.64.0.0/10  — CGNAT（Tailscale 等 overlay VPN 虚拟地址）
#   169.254.0.0/16 — 链路本地（DHCP 失败时的自动配置地址）
#   224.0.0.0/4    — 组播；240.0.0.0/4 — 保留；0.0.0.0/8 与 127.0.0.0/8 — 未指定/回环
_EXCLUDED_NETWORKS = tuple(
    ipaddress.ip_network(n) for n in (
        "0.0.0.0/8", "127.0.0.0/8", "169.254.0.0/16",
        "198.18.0.0/15", "100.64.0.0/10", "224.0.0.0/4", "240.0.0.0/4",
    )
)

# 真实局域网段优先级：192.168 > 10 > 172.16-31 > 其他
_PRIORITY_NETWORKS = (
    (ipaddress.ip_network("192.168.0.0/16"), 0),
    (ipaddress.ip_network("10.0.0.0/8"), 1),
    (ipaddress.ip_network("172.16.0.0/12"), 2),
)


def is_usable_lan_ip(ip: str) -> bool:
    """判断给定 IPv4 地址是否可作为"对外可达的本机地址"对外上报。

    排除回环、链路本地、FakeIP(198.18.0.0/15)、CGNAT(100.64.0.0/10)、组播等
    虚拟/保留网段。
    """
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    if addr.version != 4:
        return False
    return not any(addr in net for net in _EXCLUDED_NETWORKS)


def _priority(ip: str) -> int:
    addr = ipaddress.ip_address(ip)
    for net, rank in _PRIORITY_NETWORKS:
        if addr in net:
            return rank
    return 3


def detect_lan_ip() -> str:
    """探测本机局域网 IP，自动跳过 VPN/FakeIP 虚拟网卡地址。

    :return: 局域网 IPv4 地址字符串；全部不可用时返回空字符串
             （由调用方决定回退，如 127.0.0.1）
    """
    # 首选：枚举与本机主机名关联的地址（通常只包含真实物理网卡，
    # VPN 虚拟网卡地址一般不与主机名关联）
    candidates: list[str] = []
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip not in candidates:
                candidates.append(ip)
    except OSError as e:
        logger.debug("getaddrinfo(hostname) failed: %s", e)

    usable = [ip for ip in candidates if is_usable_lan_ip(ip)]
    if usable:
        chosen = sorted(usable, key=_priority)[0]
        logger.debug("LAN IP detected via hostname: %s (candidates: %s)", chosen, candidates)
        return chosen

    # 回退：UDP connect 探测（结果同样过滤虚拟网段）
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(2)
            sock.connect(("8.8.8.8", 80))
            ip = sock.getsockname()[0]
        if is_usable_lan_ip(ip):
            logger.debug("LAN IP detected via UDP route: %s", ip)
            return ip
        logger.warning(
            "Detected local IP %s belongs to a virtual/VPN range (FakeIP/CGNAT), ignored; "
            "set PROTOFORGE_PUBLIC_HOST to override the reported address",
            ip,
        )
    except OSError as e:
        logger.debug("UDP local IP detection failed: %s", e)

    return ""
