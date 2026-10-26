"""Test doubles: a real asyncio RTSP server and bitstream builders."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import re
from dataclasses import dataclass, field

import httpx

from app.netguard import NetGuard


class PermissiveGuard(NetGuard):
    """Lets tests reach the loopback fake servers; production guard forbids loopback."""

    def check_ip(self, ip):  # type: ignore[no-untyped-def]
        return None


class BitWriter:
    def __init__(self) -> None:
        self.bits: list[int] = []

    def u(self, n: int, v: int) -> BitWriter:
        self.bits += [(v >> (n - 1 - i)) & 1 for i in range(n)]
        return self

    def ue(self, v: int) -> BitWriter:
        code = v + 1
        n = code.bit_length()
        return self.u(n - 1, 0).u(n, code)

    def bytes(self) -> bytes:
        bits = self.bits + [1]  # rbsp stop bit
        bits += [0] * (-len(bits) % 8)
        return bytes(int("".join(map(str, bits[i : i + 8])), 2) for i in range(0, len(bits), 8))


def h264_sps(width_mbs: int, height_mbs: int, crop_bottom: int) -> bytes:
    w = BitWriter().u(8, 66).u(8, 0).u(8, 30).ue(0)
    w.ue(0).ue(2).ue(1).u(1, 0).ue(width_mbs - 1).ue(height_mbs - 1)
    w.u(1, 1).u(1, 1).u(1, 1).ue(0).ue(0).ue(0).ue(crop_bottom).u(1, 0)
    return b"\x67" + w.bytes()


def h265_sps(width: int, height: int) -> bytes:
    w = BitWriter().u(4, 0).u(3, 0).u(1, 1)
    for byte in (0x01, 0x60, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0x5D):
        w.u(8, byte)
    w.ue(0).ue(1).ue(width).ue(height).u(1, 0)
    return b"\x42\x01" + w.bytes()


def sdp_for(codec: str, sps: bytes, fps: int = 25) -> str:
    b64 = base64.b64encode(sps).decode()
    fmtp = f"sprop-parameter-sets={b64},aM48gA==" if codec == "H264" else f"sprop-sps={b64}"
    return (
        "v=0\r\no=- 0 0 IN IP4 0.0.0.0\r\ns=cam\r\nt=0 0\r\n"
        "m=video 0 RTP/AVP 96\r\n"
        f"a=rtpmap:96 {codec}/90000\r\n"
        f"a=fmtp:96 packetization-mode=1;{fmtp}\r\n"
        f"a=framerate:{fps}\r\n"
        "m=audio 0 RTP/AVP 8\r\na=rtpmap:8 PCMA/8000\r\n"
    )


def _md5(s: str) -> str:
    return hashlib.md5(s.encode(), usedforsecurity=False).hexdigest()


@dataclass
class FakeOnvif:
    """httpx handler emulating an ONVIF NVR with N channels (2 profiles each)."""

    username: str = "admin"
    password: str = "s3cret-pass"
    channels: int = 2
    # Deliberately different from the address we connect to, to test host pinning.
    reported_host: str = "10.9.9.9"
    seen_urls: list[str] = field(default_factory=list)

    def _check_auth(self, body: str) -> bool:
        m = {k: re.search(rf"<(?:\w+:)?{k}[^>]*>([^<]+)<", body) for k in
             ("Username", "Password", "Nonce", "Created")}
        if not all(m.values()):
            return False
        vals = {k: v.group(1) for k, v in m.items() if v}
        digest = base64.b64encode(
            hashlib.sha1(
                base64.b64decode(vals["Nonce"]) + vals["Created"].encode()
                + self.password.encode(),
                usedforsecurity=False,
            ).digest()
        ).decode()
        return vals["Username"] == self.username and vals["Password"] == digest

    @staticmethod
    def _env(inner: str) -> str:
        return (
            '<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope" '
            'xmlns:tt="http://www.onvif.org/ver10/schema" '
            'xmlns:trt="http://www.onvif.org/ver10/media/wsdl" '
            'xmlns:tds="http://www.onvif.org/ver10/device/wsdl">'
            f"<s:Body>{inner}</s:Body></s:Envelope>"
        )

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.seen_urls.append(str(request.url))
        body = request.content.decode()
        if "GetSystemDateAndTime" in body:
            return httpx.Response(200, text=self._env(
                "<tds:GetSystemDateAndTimeResponse><tds:SystemDateAndTime><tt:UTCDateTime>"
                "<tt:Time><tt:Hour>10</tt:Hour><tt:Minute>0</tt:Minute><tt:Second>0</tt:Second>"
                "</tt:Time><tt:Date><tt:Year>2026</tt:Year><tt:Month>10</tt:Month>"
                "<tt:Day>23</tt:Day></tt:Date></tt:UTCDateTime></tds:SystemDateAndTime>"
                "</tds:GetSystemDateAndTimeResponse>"))
        if not self._check_auth(body):
            return httpx.Response(400, text=self._env(
                "<s:Fault><s:Code><s:Value>s:Sender</s:Value><s:Subcode>"
                "<s:Value>ter:NotAuthorized</s:Value></s:Subcode></s:Code></s:Fault>"))
        if "GetDeviceInformation" in body:
            return httpx.Response(200, text=self._env(
                "<tds:GetDeviceInformationResponse><tds:Manufacturer>H</tds:Manufacturer>"
                "<tds:Model>N3004</tds:Model><tds:FirmwareVersion>V2.0.1</tds:FirmwareVersion>"
                "<tds:SerialNumber>SN123</tds:SerialNumber></tds:GetDeviceInformationResponse>"))
        if "GetCapabilities" in body:
            return httpx.Response(200, text=self._env(
                "<tds:GetCapabilitiesResponse><tds:Capabilities><tt:Media>"
                f"<tt:XAddr>http://{self.reported_host}:8080/onvif/media</tt:XAddr>"
                "</tt:Media></tds:Capabilities></tds:GetCapabilitiesResponse>"))
        if "GetProfiles" in body:
            profiles = ""
            for ch in range(1, self.channels + 1):
                for kind, (w, h) in (("main", (2560, 1440)), ("sub", (640, 360))):
                    profiles += (
                        f'<trt:Profiles token="p{ch}{kind}"><tt:VideoSourceConfiguration>'
                        f"<tt:SourceToken>src{ch}</tt:SourceToken></tt:VideoSourceConfiguration>"
                        "<tt:VideoEncoderConfiguration><tt:Encoding>H264</tt:Encoding>"
                        f"<tt:Resolution><tt:Width>{w}</tt:Width><tt:Height>{h}</tt:Height>"
                        "</tt:Resolution><tt:RateControl><tt:FrameRateLimit>15</tt:FrameRateLimit>"
                        "</tt:RateControl></tt:VideoEncoderConfiguration></trt:Profiles>"
                    )
            return httpx.Response(200, text=self._env(
                f"<trt:GetProfilesResponse>{profiles}</trt:GetProfilesResponse>"))
        if "GetStreamUri" in body:
            m = re.search(r"<ProfileToken>p(\d+)(main|sub)</ProfileToken>", body)
            assert m
            path = f"/ch{int(m.group(1)):02d}/{0 if m.group(2) == 'main' else 1}"
            return httpx.Response(200, text=self._env(
                "<trt:GetStreamUriResponse><trt:MediaUri>"
                f"<tt:Uri>rtsp://{self.reported_host}:554{path}</tt:Uri>"
                "</trt:MediaUri></trt:GetStreamUriResponse>"))
        return httpx.Response(500)


@dataclass
class FakeRtsp:
    streams: dict[str, str]  # path -> SDP
    username: str = "admin"
    password: str = "s3cret-pass"
    realm: str = "IPCam"
    nonce: str = "abc123"
    requests: list[str] = field(default_factory=list)
    server: asyncio.Server | None = None
    port: int = 0

    async def start(self) -> FakeRtsp:
        self.server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        self.port = self.server.sockets[0].getsockname()[1]
        return self

    async def stop(self) -> None:
        if self.server:
            self.server.close()
            await self.server.wait_closed()

    def _authorized(self, header: str | None, uri: str) -> bool:
        if not header or not header.startswith("Digest "):
            return False
        p = dict(re.findall(r'(\w+)="?([^",]*)"?', header[7:]))
        ha1 = _md5(f"{self.username}:{self.realm}:{self.password}")
        ha2 = _md5(f"DESCRIBE:{uri}")
        if p.get("qop") == "auth":
            expected = _md5(f"{ha1}:{self.nonce}:{p['nc']}:{p['cnonce']}:auth:{ha2}")
        else:
            expected = _md5(f"{ha1}:{self.nonce}:{ha2}")
        return p.get("username") == self.username and p.get("response") == expected

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            while True:
                raw = await reader.readuntil(b"\r\n\r\n")
                lines = raw.decode().split("\r\n")
                method, uri, _ = lines[0].split(" ")
                headers = dict(
                    (k.strip().lower(), v.strip())
                    for k, _, v in (ln.partition(":") for ln in lines[1:] if ln)
                )
                self.requests.append(lines[0])
                cseq = headers.get("cseq", "0")
                path = "/" + uri.split("/", 3)[3] if uri.count("/") >= 3 else "/"
                if method != "DESCRIBE" or path not in self.streams:
                    writer.write(f"RTSP/1.0 404 Not Found\r\nCSeq: {cseq}\r\n\r\n".encode())
                elif not self._authorized(headers.get("authorization"), uri):
                    writer.write(
                        (
                            f"RTSP/1.0 401 Unauthorized\r\nCSeq: {cseq}\r\n"
                            f'WWW-Authenticate: Digest realm="{self.realm}", nonce="{self.nonce}"'
                            "\r\n\r\n"
                        ).encode()
                    )
                else:
                    body = self.streams[path].encode()
                    writer.write(
                        (
                            f"RTSP/1.0 200 OK\r\nCSeq: {cseq}\r\nContent-Type: application/sdp\r\n"
                            f"Content-Length: {len(body)}\r\n\r\n"
                        ).encode()
                        + body
                    )
                await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            writer.close()
