import asyncio

import pytest

from app.providers import rtsp
from app.providers.base import AuthFailed, ProviderError, Unreachable
from tests.fakes import FakeRtsp, h264_sps, h265_sps, sdp_for


def test_h264_sps_dimensions() -> None:
    assert rtsp.h264_dimensions(h264_sps(120, 68, crop_bottom=4)) == (1920, 1080)
    assert rtsp.h264_dimensions(h264_sps(40, 30, crop_bottom=0)) == (640, 480)


def test_h265_sps_dimensions() -> None:
    assert rtsp.h265_dimensions(h265_sps(2560, 1440)) == (2560, 1440)


def test_parse_sdp_h264_and_h265() -> None:
    p = rtsp.parse_sdp(sdp_for("H264", h264_sps(120, 68, 4), fps=20))
    assert (p.codec, p.width, p.height, p.fps) == ("H264", 1920, 1080, 20.0)
    p = rtsp.parse_sdp(sdp_for("H265", h265_sps(2560, 1440)))
    assert (p.codec, p.width, p.height) == ("H265", 2560, 1440)


def test_parse_sdp_without_video() -> None:
    p = rtsp.parse_sdp("v=0\r\nm=audio 0 RTP/AVP 8\r\na=rtpmap:8 PCMA/8000\r\n")
    assert p.codec is None


def test_digest_with_qop_shape() -> None:
    header = rtsp.authorization(
        ['Digest realm="r", nonce="n", qop="auth"'], "DESCRIBE", "rtsp://x/1", "u", "p"
    )
    assert header is not None and header.startswith("Digest ")
    assert "qop=auth" in header and 'cnonce="' in header


def test_basic_only_when_offered() -> None:
    assert rtsp.authorization(['Basic realm="r"'], "DESCRIBE", "u", "a", "b") == "Basic YTpi"
    assert rtsp.authorization(['Bearer x="y"'], "DESCRIBE", "u", "a", "b") is None


async def _with_server(streams: dict[str, str], fn):  # type: ignore[no-untyped-def]
    server = await FakeRtsp(streams).start()
    try:
        return await fn(server)
    finally:
        await server.stop()


def test_describe_against_fake_camera() -> None:
    sdp = sdp_for("H264", h264_sps(40, 30, 0), fps=15)

    async def go(s: FakeRtsp):  # type: ignore[no-untyped-def]
        return await rtsp.describe("127.0.0.1", s.port, "/ch01/1", s.username, s.password, 3)

    probe = asyncio.run(_with_server({"/ch01/1": sdp}, go))
    assert (probe.codec, probe.width, probe.height, probe.fps) == ("H264", 640, 480, 15.0)


def test_describe_wrong_password() -> None:
    async def go(s: FakeRtsp) -> None:
        with pytest.raises(AuthFailed) as exc:
            await rtsp.describe("127.0.0.1", s.port, "/x", s.username, "wrong", 3)
        assert exc.value.code == "rtsp.auth_failed"

    asyncio.run(_with_server({"/x": "v=0\r\n"}, go))


def test_describe_unknown_path() -> None:
    async def go(s: FakeRtsp) -> None:
        with pytest.raises(ProviderError) as exc:
            await rtsp.describe("127.0.0.1", s.port, "/nope", s.username, s.password, 3)
        assert exc.value.code == "rtsp.not_found"

    asyncio.run(_with_server({"/x": "v=0\r\n"}, go))


def test_tcp_refused() -> None:
    async def go() -> None:
        server = await asyncio.start_server(lambda r, w: None, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        server.close()
        await server.wait_closed()
        with pytest.raises(Unreachable) as exc:
            # Windows retries refused SYNs for ~2 s; Linux fails immediately.
            await rtsp.tcp_check("127.0.0.1", port, 10)
        assert exc.value.code == "net.tcp_refused"

    asyncio.run(go())


def test_silent_server_times_out() -> None:
    async def go() -> None:
        async def hang(r: asyncio.StreamReader, w: asyncio.StreamWriter) -> None:
            await asyncio.sleep(5)

        server = await asyncio.start_server(hang, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        try:
            with pytest.raises(ProviderError) as exc:
                await rtsp.describe("127.0.0.1", port, "/x", "a", "b", 0.3)
            assert exc.value.code == "rtsp.timeout"
        finally:
            server.close()

    asyncio.run(go())
