import asyncio
import ipaddress
from collections.abc import Coroutine
from typing import Any

import pytest

from app.netguard import AddressRejected, NetGuard, parse_networks, validate_host_syntax


def run[T](coro: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(coro)


@pytest.mark.parametrize(
    "host",
    [
        "192.168.1.68",
        "10.0.0.5",
        "172.16.3.4",
        "100.64.0.1",  # CGNAT / Tailscale
        "100.101.102.103",
        "fd12:3456::1",
    ],
)
def test_private_and_vpn_ranges_allowed(host: str) -> None:
    assert run(NetGuard().resolve(host, 554)) == host


@pytest.mark.parametrize(
    ("host", "code"),
    [
        ("127.0.0.1", "net.forbidden_address"),
        ("127.1.2.3", "net.forbidden_address"),
        ("::1", "net.forbidden_address"),
        ("::ffff:127.0.0.1", "net.forbidden_address"),
        ("169.254.169.254", "net.forbidden_address"),  # cloud metadata
        ("100.100.100.200", "net.forbidden_address"),  # metadata inside CGNAT
        ("fe80::1", "net.forbidden_address"),
        ("0.0.0.0", "net.forbidden_address"),
        ("224.0.0.1", "net.forbidden_address"),
        ("8.8.8.8", "net.not_private"),
        ("2001:4860:4860::8888", "net.not_private"),
        ("localhost", "net.forbidden_address"),
    ],
)
def test_forbidden_and_public_rejected(host: str, code: str) -> None:
    with pytest.raises(AddressRejected) as exc:
        run(NetGuard().resolve(host, 554))
    assert exc.value.code == code


@pytest.mark.parametrize(
    "host",
    ["user:pass@10.0.0.1", "10.0.0.1:554", "http://10.0.0.1", "cam/../x", "a b", "", "x" * 300],
)
def test_bad_host_syntax_rejected(host: str) -> None:
    with pytest.raises(AddressRejected) as exc:
        validate_host_syntax(host)
    assert exc.value.code == "net.invalid_host"


def test_allowlist_extends_but_never_overrides_forbidden() -> None:
    guard = NetGuard(parse_networks("203.0.113.0/24, 127.0.0.0/8"))
    assert run(guard.resolve("203.0.113.7", 554)) == "203.0.113.7"
    with pytest.raises(AddressRejected):
        run(guard.resolve("127.0.0.1", 554))


def test_dns_answer_with_any_public_address_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_getaddrinfo(host, port, **_kw):  # type: ignore[no-untyped-def]
        return [(0, 0, 0, "", ("192.168.1.10", port)), (0, 0, 0, "", ("93.184.216.34", port))]

    async def go() -> None:
        loop = asyncio.get_running_loop()
        monkeypatch.setattr(loop, "getaddrinfo", fake_getaddrinfo)
        with pytest.raises(AddressRejected) as exc:
            await NetGuard().resolve("rebind.example", 554)
        assert exc.value.code == "net.not_private"

    run(go())


def test_dns_resolves_to_ip_used_for_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_getaddrinfo(host, port, **_kw):  # type: ignore[no-untyped-def]
        return [(0, 0, 0, "", ("10.1.2.3", port))]

    async def go() -> str:
        loop = asyncio.get_running_loop()
        monkeypatch.setattr(loop, "getaddrinfo", fake_getaddrinfo)
        return await NetGuard().resolve("nvr.lan", 554)

    assert ipaddress.ip_address(run(go())) == ipaddress.ip_address("10.1.2.3")


def test_invalid_allowlist_rejected() -> None:
    with pytest.raises(ValueError):
        parse_networks("not-a-cidr")
