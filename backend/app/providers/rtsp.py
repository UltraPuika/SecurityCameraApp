"""Minimal RTSP DESCRIBE client: verifies reachability and credentials and reads codec info."""

from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import re
import secrets
import ssl
from dataclasses import dataclass

from app.netguard import host_for_url
from app.providers.base import AuthFailed, ProviderError, StreamProbe, Timeout, Unreachable

MAX_HEADER = 16 * 1024
MAX_BODY = 64 * 1024


@dataclass
class RtspResponse:
    status: int
    headers: list[tuple[str, str]]
    body: bytes

    def header(self, name: str) -> str | None:
        return next((v for k, v in self.headers if k == name.lower()), None)

    def all(self, name: str) -> list[str]:
        return [v for k, v in self.headers if k == name.lower()]


def _md5(s: str) -> str:
    return hashlib.md5(s.encode(), usedforsecurity=False).hexdigest()


def _parse_challenge(value: str) -> tuple[str, dict[str, str]]:
    scheme, _, rest = value.strip().partition(" ")
    pairs = re.findall(r'(\w+)=(?:"([^"]*)"|([^,\s]*))', rest)
    params = {m[0].lower(): m[1] or m[2] for m in pairs}
    return scheme.lower(), params


def authorization(
    challenges: list[str], method: str, uri: str, username: str, password: str
) -> str | None:
    parsed = [_parse_challenge(c) for c in challenges]
    for scheme, p in parsed:
        if scheme == "digest" and p.get("algorithm", "MD5").upper() == "MD5":
            ha1 = _md5(f"{username}:{p.get('realm', '')}:{password}")
            ha2 = _md5(f"{method}:{uri}")
            nonce = p.get("nonce", "")
            fields = {
                "username": username,
                "realm": p.get("realm", ""),
                "nonce": nonce,
                "uri": uri,
            }
            qops = [q.strip() for q in p.get("qop", "").split(",") if q.strip()]
            if "auth" in qops:
                cnonce = secrets.token_hex(8)
                nc = "00000001"
                fields["response"] = _md5(f"{ha1}:{nonce}:{nc}:{cnonce}:auth:{ha2}")
                fields.update(qop="auth", nc=nc, cnonce=cnonce)
            else:
                fields["response"] = _md5(f"{ha1}:{nonce}:{ha2}")
            if "opaque" in p:
                fields["opaque"] = p["opaque"]
            unquoted = {"qop", "nc"}
            return "Digest " + ", ".join(
                f"{k}={v}" if k in unquoted else f'{k}="{v}"' for k, v in fields.items()
            )
    if any(scheme == "basic" for scheme, _ in parsed):
        return "Basic " + base64.b64encode(f"{username}:{password}".encode()).decode()
    return None


class _Conn:
    def __init__(self, ip: str, port: int, tls: bool, timeout: float) -> None:
        self.ip, self.port, self.tls, self.timeout = ip, port, tls, timeout
        self.reader: asyncio.StreamReader | None = None
        self.writer: asyncio.StreamWriter | None = None
        self.cseq = 0

    async def open(self) -> None:
        ctx = ssl.create_default_context() if self.tls else None
        try:
            self.reader, self.writer = await asyncio.wait_for(
                asyncio.open_connection(self.ip, self.port, ssl=ctx, limit=MAX_HEADER),
                self.timeout,
            )
        except TimeoutError as exc:
            raise Timeout("net.tcp_timeout") from exc
        except ssl.SSLError as exc:
            raise Unreachable("net.tls_failed") from exc
        except OSError as exc:
            raise Unreachable("net.tcp_refused") from exc

    async def close(self) -> None:
        if self.writer is not None:
            self.writer.close()
            with contextlib.suppress(OSError):
                await self.writer.wait_closed()
            self.writer = None

    async def request(self, method: str, uri: str, headers: dict[str, str]) -> RtspResponse:
        if self.writer is None or self.reader is None or self.writer.is_closing():
            await self.open()
        assert self.reader is not None and self.writer is not None
        self.cseq += 1
        lines = [f"{method} {uri} RTSP/1.0", f"CSeq: {self.cseq}", "User-Agent: camdash"]
        lines += [f"{k}: {v}" for k, v in headers.items()]
        self.writer.write(("\r\n".join(lines) + "\r\n\r\n").encode())
        try:
            await asyncio.wait_for(self.writer.drain(), self.timeout)
            raw = await asyncio.wait_for(self.reader.readuntil(b"\r\n\r\n"), self.timeout)
        except TimeoutError as exc:
            raise Timeout("rtsp.timeout") from exc
        except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, OSError) as exc:
            raise Unreachable("rtsp.connection_closed") from exc
        head = raw.decode("latin-1").split("\r\n")
        m = re.match(r"RTSP/1\.\d (\d{3})", head[0])
        if not m:
            raise Unreachable("rtsp.bad_response")
        parsed = []
        for line in head[1:]:
            if ":" in line:
                k, _, v = line.partition(":")
                parsed.append((k.strip().lower(), v.strip()))
        resp = RtspResponse(int(m.group(1)), parsed, b"")
        length = int(resp.header("content-length") or 0)
        if length > MAX_BODY:
            raise Unreachable("rtsp.bad_response")
        if length:
            try:
                resp.body = await asyncio.wait_for(self.reader.readexactly(length), self.timeout)
            except (TimeoutError, asyncio.IncompleteReadError) as exc:
                raise Timeout("rtsp.timeout") from exc
        return resp


async def tcp_check(ip: str, port: int, timeout: float) -> None:
    conn = _Conn(ip, port, False, timeout)
    await conn.open()
    await conn.close()


async def describe(
    ip: str,
    port: int,
    path: str,
    username: str,
    password: str,
    timeout: float,
    tls: bool = False,
) -> StreamProbe:
    scheme = "rtsps" if tls else "rtsp"
    uri = f"{scheme}://{host_for_url(ip)}:{port}{path}"
    conn = _Conn(ip, port, tls, timeout)
    try:
        resp = await conn.request("DESCRIBE", uri, {"Accept": "application/sdp"})
        if resp.status == 401:
            auth = authorization(resp.all("www-authenticate"), "DESCRIBE", uri, username, password)
            if auth is None or not username:
                raise AuthFailed("rtsp.auth_required")
            if (resp.header("connection") or "").lower() == "close":
                await conn.close()
            resp = await conn.request(
                "DESCRIBE", uri, {"Accept": "application/sdp", "Authorization": auth}
            )
            if resp.status == 401:
                raise AuthFailed("rtsp.auth_failed")
        if resp.status == 404:
            raise ProviderError("rtsp.not_found")
        if resp.status == 403:
            raise AuthFailed("rtsp.forbidden")
        if resp.status != 200:
            raise Unreachable("rtsp.bad_status", rtsp_status=resp.status)
        return parse_sdp(resp.body.decode("utf-8", "replace"))
    finally:
        await conn.close()


# --- SDP / SPS parsing -----------------------------------------------------------------


def parse_sdp(sdp: str) -> StreamProbe:
    probe = StreamProbe()
    in_video = False
    payloads: dict[str, str] = {}
    fmtp: dict[str, str] = {}
    for line in sdp.splitlines():
        line = line.strip()
        if line.startswith("m="):
            if in_video:
                break
            in_video = line.startswith("m=video")
        elif in_video and line.startswith("a=rtpmap:"):
            pt, _, rest = line[9:].partition(" ")
            payloads[pt] = rest.split("/")[0].upper()
        elif in_video and line.startswith("a=fmtp:"):
            pt, _, rest = line[7:].partition(" ")
            fmtp[pt] = rest
        elif in_video and (line.startswith("a=framerate:") or line.startswith("a=x-framerate:")):
            with contextlib.suppress(ValueError):
                probe.fps = float(line.split(":", 1)[1])
    if not payloads:
        return probe
    pt, name = next(iter(payloads.items()))
    probe.codec = {"H265": "H265", "HEVC": "H265", "H264": "H264", "JPEG": "MJPEG"}.get(name, name)
    params = dict(
        (k.strip().lower(), v.strip())
        for k, _, v in (p.partition("=") for p in fmtp.get(pt, "").split(";"))
        if k.strip()
    )
    try:
        if probe.codec == "H264" and "sprop-parameter-sets" in params:
            sps = _b64(params["sprop-parameter-sets"].split(",")[0])
            probe.width, probe.height = h264_dimensions(sps)
        elif probe.codec == "H265" and "sprop-sps" in params:
            probe.width, probe.height = h265_dimensions(_b64(params["sprop-sps"]))
    except (ValueError, IndexError):
        pass
    return probe


def _b64(s: str) -> bytes:
    return base64.b64decode(s + "=" * (-len(s) % 4))


def _unescape(nal: bytes) -> bytes:
    return re.sub(b"\x00\x00\x03", b"\x00\x00", nal)


class BitReader:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.pos = 0

    def u(self, n: int) -> int:
        v = 0
        for _ in range(n):
            byte = self.data[self.pos >> 3]
            v = (v << 1) | ((byte >> (7 - (self.pos & 7))) & 1)
            self.pos += 1
        return v

    def ue(self) -> int:
        zeros = 0
        while self.u(1) == 0:
            zeros += 1
            if zeros > 31:
                raise ValueError("bad exp-golomb")
        return (1 << zeros) - 1 + self.u(zeros)

    def se(self) -> int:
        v = self.ue()
        return (v + 1) // 2 if v & 1 else -(v // 2)


def h264_dimensions(sps: bytes) -> tuple[int, int]:
    r = BitReader(_unescape(sps)[1:])
    profile = r.u(8)
    r.u(16)
    r.ue()
    chroma = 1
    if profile in (100, 110, 122, 244, 44, 83, 86, 118, 128, 138, 139, 134, 135):
        chroma = r.ue()
        if chroma == 3:
            r.u(1)
        r.ue()
        r.ue()
        r.u(1)
        if r.u(1):
            for i in range(8 if chroma != 3 else 12):
                if r.u(1):
                    last, nxt = 8, 8
                    for _ in range(16 if i < 6 else 64):
                        if nxt:
                            nxt = (last + r.se() + 256) % 256
                        last = nxt or last
    r.ue()
    poc = r.ue()
    if poc == 0:
        r.ue()
    elif poc == 1:
        r.u(1)
        r.se()
        r.se()
        for _ in range(r.ue()):
            r.se()
    r.ue()
    r.u(1)
    w_mbs = r.ue() + 1
    h_units = r.ue() + 1
    frame_mbs_only = r.u(1)
    if not frame_mbs_only:
        r.u(1)
    r.u(1)
    cl = cr = ct = cb = 0
    if r.u(1):
        cl, cr, ct, cb = r.ue(), r.ue(), r.ue(), r.ue()
    sub_w, sub_h = (1, 1) if chroma in (0, 3) else (2, 2 if chroma == 1 else 1)
    crop_y = sub_h * (2 - frame_mbs_only)
    width = w_mbs * 16 - (cl + cr) * sub_w
    height = (2 - frame_mbs_only) * h_units * 16 - (ct + cb) * crop_y
    return width, height


def h265_dimensions(sps: bytes) -> tuple[int, int]:
    r = BitReader(_unescape(sps)[2:])
    r.u(4)
    max_sub = r.u(3)
    r.u(1)
    r.u(96)  # general profile/tier/level
    prof_present, level_present = [], []
    for _ in range(max_sub):
        prof_present.append(r.u(1))
        level_present.append(r.u(1))
    if max_sub > 0:
        for _ in range(max_sub, 8):
            r.u(2)
    for i in range(max_sub):
        if prof_present[i]:
            r.u(88)
        if level_present[i]:
            r.u(8)
    r.ue()
    chroma = r.ue()
    if chroma == 3:
        r.u(1)
    width, height = r.ue(), r.ue()
    if r.u(1):
        cl, cr, ct, cb = r.ue(), r.ue(), r.ue(), r.ue()
        sub_w = 2 if chroma in (1, 2) else 1
        sub_h = 2 if chroma == 1 else 1
        width -= sub_w * (cl + cr)
        height -= sub_h * (ct + cb)
    return width, height
