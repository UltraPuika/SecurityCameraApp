import asyncio

import httpx
import pytest

from app.providers.base import AuthFailed, ProviderError
from app.providers.onvif import OnvifClient, select_channel_profiles
from tests.fakes import FakeOnvif


def _client(fake: FakeOnvif, password: str | None = None) -> tuple[OnvifClient, httpx.AsyncClient]:
    http = httpx.AsyncClient(transport=httpx.MockTransport(fake.handler))
    return OnvifClient(http, "192.168.1.68", 80, fake.username, password or fake.password, 3), http


def test_profiles_and_stream_uri_per_channel() -> None:
    fake = FakeOnvif(channels=4)

    async def go() -> None:
        client, http = _client(fake)
        async with http:
            await client.sync_clock()
            info = await client.device_info()
            assert info["Model"] == "N3004"
            profiles = await client.profiles()
            assert len(profiles) == 8
            main, sub = select_channel_profiles(profiles, 3)
            assert (main.token, main.width) == ("p3main", 2560)
            assert sub is not None and sub.token == "p3sub"
            assert await client.stream_uri(main.token) == (554, "/ch03/0")
            assert await client.stream_uri(sub.token) == (554, "/ch03/1")

    asyncio.run(go())
    # The device reported 10.9.9.9 for its media service; we must stay on the validated IP.
    assert fake.seen_urls and all(httpx.URL(u).host == "192.168.1.68" for u in fake.seen_urls)
    assert "http://192.168.1.68:8080/onvif/media" in fake.seen_urls


def test_channel_out_of_range() -> None:
    fake = FakeOnvif(channels=2)

    async def go() -> None:
        client, http = _client(fake)
        async with http:
            with pytest.raises(ProviderError) as exc:
                select_channel_profiles(await client.profiles(), 3)
            assert exc.value.code == "onvif.channel_not_found"
            assert exc.value.detail == {"channels": 2}

    asyncio.run(go())


def test_wrong_password_is_auth_failure() -> None:
    async def go() -> None:
        client, http = _client(FakeOnvif(), password="wrong")
        async with http:
            with pytest.raises(AuthFailed):
                await client.device_info()

    asyncio.run(go())


def test_xml_bombs_are_rejected() -> None:
    bomb = (
        '<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol">'
        '<!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">]><a>&lol2;</a>'
    )

    async def go() -> None:
        http = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, text=bomb)))
        async with http:
            client = OnvifClient(http, "10.0.0.2", 80, "u", "p", 3)
            with pytest.raises(ProviderError) as exc:
                await client.device_info()
            assert exc.value.code == "onvif.bad_response"

    asyncio.run(go())
