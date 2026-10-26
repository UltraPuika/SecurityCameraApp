"""Outbound-connection guard: camera hosts must resolve to private/VPN ranges."""

import asyncio
import ipaddress
import re
import socket
from collections.abc import Iterable

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address
IPNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network

DEFAULT_ALLOWED: tuple[IPNetwork, ...] = tuple(
    ipaddress.ip_network(n)
    for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "100.64.0.0/10", "fc00::/7")
)

# Always rejected, even if an admin allowlist overlaps them.
FORBIDDEN: tuple[IPNetwork, ...] = tuple(
    ipaddress.ip_network(n)
    for n in (
        "0.0.0.0/8",
        "127.0.0.0/8",
        "169.254.0.0/16",
        "224.0.0.0/4",
        "240.0.0.0/4",
        "255.255.255.255/32",
        "100.100.100.200/32",  # Alibaba Cloud metadata (inside CGNAT range)
        "::/128",
        "::1/128",
        "fe80::/10",
        "ff00::/8",
        "fd00:ec2::254/128",  # AWS IPv6 metadata (inside ULA range)
    )
)

_LABEL = r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
_HOSTNAME_RE = re.compile(rf"^(?=.{{1,253}}$){_LABEL}(\.{_LABEL})*\.?$")


class AddressRejected(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def parse_networks(spec: str) -> tuple[IPNetwork, ...]:
    parts = (p.strip() for p in spec.split(","))
    return tuple(ipaddress.ip_network(p, strict=False) for p in parts if p)


def validate_host_syntax(host: str) -> str:
    host = host.strip()
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]
    try:
        return str(ipaddress.ip_address(host))
    except ValueError:
        pass
    if not _HOSTNAME_RE.match(host):
        raise AddressRejected("net.invalid_host")
    return host.lower().rstrip(".")


def _unmap(ip: IPAddress) -> IPAddress:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        return ip.ipv4_mapped
    return ip


class NetGuard:
    def __init__(self, extra_allowed: Iterable[IPNetwork] = ()) -> None:
        self.allowed = DEFAULT_ALLOWED + tuple(extra_allowed)

    def check_ip(self, ip: IPAddress) -> None:
        ip = _unmap(ip)
        if any(ip in n for n in FORBIDDEN):
            raise AddressRejected("net.forbidden_address")
        if not any(ip in n for n in self.allowed):
            raise AddressRejected("net.not_private")

    async def resolve(self, host: str, port: int) -> str:
        """Resolve and validate every address; callers must connect to the returned IP."""
        host = validate_host_syntax(host)
        try:
            literal: IPAddress | None = ipaddress.ip_address(host)
        except ValueError:
            literal = None
        if literal is not None:
            self.check_ip(literal)
            return str(_unmap(literal))
        loop = asyncio.get_running_loop()
        try:
            infos = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        except socket.gaierror as exc:
            raise AddressRejected("net.dns_failed") from exc
        ips = [_unmap(ipaddress.ip_address(info[4][0])) for info in infos]
        if not ips:
            raise AddressRejected("net.dns_failed")
        # Every answer must pass, so a mixed public/private record set is rejected.
        for ip in ips:
            self.check_ip(ip)
        return str(ips[0])


def host_for_url(ip: str) -> str:
    return f"[{ip}]" if ":" in ip else ip
