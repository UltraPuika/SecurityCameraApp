"""Small ONVIF Profile S client (device + media services) and WS-Discovery probe."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import secrets
import socket
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit
from xml.etree.ElementTree import Element  # noqa: S405  (type only; parsing uses defusedxml)

import httpx
from defusedxml.ElementTree import fromstring

from app.netguard import host_for_url
from app.providers.base import AuthFailed, ProviderError, Timeout, Unreachable

SOAP_ENV = "http://www.w3.org/2003/05/soap-envelope"
WSSE = "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd"
WSU = "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd"
PW_DIGEST = (
    "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-username-token-profile-1.0"
    "#PasswordDigest"
)
TDS = "http://www.onvif.org/ver10/device/wsdl"
TRT = "http://www.onvif.org/ver10/media/wsdl"
TT = "http://www.onvif.org/ver10/schema"
MAX_RESPONSE = 512 * 1024


@dataclass
class OnvifProfile:
    token: str
    source: str
    encoding: str | None
    width: int | None
    height: int | None
    fps: float | None


def _security_header(username: str, password: str, clock_offset: timedelta) -> str:
    nonce = secrets.token_bytes(16)
    created = (datetime.now(UTC) + clock_offset).strftime("%Y-%m-%dT%H:%M:%SZ")
    digest = base64.b64encode(
        hashlib.sha1(nonce + created.encode() + password.encode(), usedforsecurity=False).digest()
    ).decode()
    return (
        f'<Security xmlns="{WSSE}" xmlns:wsu="{WSU}"><UsernameToken>'
        f"<Username>{_xml_escape(username)}</Username>"
        f'<Password Type="{PW_DIGEST}">{digest}</Password>'
        f"<Nonce>{base64.b64encode(nonce).decode()}</Nonce>"
        f"<wsu:Created>{created}</wsu:Created></UsernameToken></Security>"
    )


def _xml_escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _find(el: Element, path: str) -> Element | None:
    return el.find(".//{*}" + "/{*}".join(path.split("/")))


def _text(el: Element | None, path: str) -> str | None:
    if el is None:
        return None
    found = _find(el, path)
    return found.text.strip() if found is not None and found.text else None


class OnvifClient:
    def __init__(
        self,
        http: httpx.AsyncClient,
        ip: str,
        port: int,
        username: str,
        password: str,
        timeout: float,
        https: bool = False,
    ) -> None:
        self.http = http
        self.ip = ip
        self.port = port
        self.scheme = "https" if https else "http"
        self.username = username
        self.password = password
        self.timeout = timeout
        self.clock_offset = timedelta()
        self.device_url = self._url("/onvif/device_service")
        self.media_url: str | None = None

    def _url(self, path: str, port: int | None = None) -> str:
        return f"{self.scheme}://{host_for_url(self.ip)}:{port or self.port}{path}"

    def _pin(self, xaddr: str) -> str:
        """Keep only path/port from device-reported addresses; the host is always our IP."""
        parts = urlsplit(xaddr)
        path = parts.path or "/"
        if parts.query:
            path += "?" + parts.query
        return self._url(path, parts.port or self.port)

    async def _call(self, url: str, body: str, auth: bool = True) -> Element:
        header = ""
        if auth and self.username:
            sec = _security_header(self.username, self.password, self.clock_offset)
            header = f"<s:Header>{sec}</s:Header>"
        envelope = f'<s:Envelope xmlns:s="{SOAP_ENV}">{header}<s:Body>{body}</s:Body></s:Envelope>'
        try:
            resp = await self.http.post(
                url,
                content=envelope.encode(),
                headers={"Content-Type": "application/soap+xml; charset=utf-8"},
                timeout=self.timeout,
                follow_redirects=False,
            )
        except httpx.TimeoutException as exc:
            raise Timeout("onvif.timeout") from exc
        except httpx.HTTPError as exc:
            raise Unreachable("onvif.unreachable") from exc
        if len(resp.content) > MAX_RESPONSE:
            raise Unreachable("onvif.bad_response")
        if resp.status_code == 401:
            raise AuthFailed("onvif.auth_failed")
        try:
            root = fromstring(resp.content)
        except Exception as exc:
            raise Unreachable("onvif.bad_response", http_status=resp.status_code) from exc
        fault = _find(root, "Body/Fault")
        if fault is not None or resp.status_code >= 400:
            text = "".join(fault.itertext()).lower() if fault is not None else ""
            if resp.status_code == 401 or "notauthorized" in text or "failedauthentication" in text:
                raise AuthFailed("onvif.auth_failed")
            raise ProviderError("onvif.fault", http_status=resp.status_code)
        body_el = _find(root, "Body")
        if body_el is None:
            raise Unreachable("onvif.bad_response")
        return body_el

    async def sync_clock(self) -> None:
        body = await self._call(self.device_url, f'<GetSystemDateAndTime xmlns="{TDS}"/>', False)
        utc = _find(body, "UTCDateTime")
        if utc is None:
            return
        try:
            dev = datetime(
                int(_text(utc, "Date/Year") or 0),
                int(_text(utc, "Date/Month") or 0),
                int(_text(utc, "Date/Day") or 0),
                int(_text(utc, "Time/Hour") or 0),
                int(_text(utc, "Time/Minute") or 0),
                int(_text(utc, "Time/Second") or 0),
                tzinfo=UTC,
            )
        except ValueError:
            return
        self.clock_offset = dev - datetime.now(UTC)

    async def device_info(self) -> dict[str, str | None]:
        body = await self._call(self.device_url, f'<GetDeviceInformation xmlns="{TDS}"/>')
        return {
            k: _text(body, k)
            for k in ("Manufacturer", "Model", "FirmwareVersion", "SerialNumber")
        }

    async def _media(self) -> str:
        if self.media_url is None:
            body = await self._call(
                self.device_url,
                f'<GetCapabilities xmlns="{TDS}"><Category>Media</Category></GetCapabilities>',
            )
            xaddr = _text(body, "Media/XAddr")
            self.media_url = self._pin(xaddr) if xaddr else self._url("/onvif/media_service")
        return self.media_url

    async def profiles(self) -> list[OnvifProfile]:
        body = await self._call(await self._media(), f'<GetProfiles xmlns="{TRT}"/>')
        out = []
        for p in body.iter():
            if not p.tag.endswith("}Profiles") or "token" not in p.attrib:
                continue
            fps_txt = _text(p, "VideoEncoderConfiguration/RateControl/FrameRateLimit")
            w = _text(p, "VideoEncoderConfiguration/Resolution/Width")
            h = _text(p, "VideoEncoderConfiguration/Resolution/Height")
            src = _find(p, "VideoSourceConfiguration/SourceToken")
            out.append(
                OnvifProfile(
                    token=p.attrib["token"],
                    source=(src.text or "").strip() if src is not None else "",
                    encoding=_text(p, "VideoEncoderConfiguration/Encoding"),
                    width=int(w) if w and w.isdigit() else None,
                    height=int(h) if h and h.isdigit() else None,
                    fps=float(fps_txt) if fps_txt else None,
                )
            )
        return out

    async def stream_uri(self, profile_token: str) -> tuple[int, str]:
        """Returns (rtsp_port, path_with_query) of the profile's RTSP URI."""
        body = await self._call(
            await self._media(),
            f'<GetStreamUri xmlns="{TRT}"><StreamSetup>'
            f'<Stream xmlns="{TT}">RTP-Unicast</Stream>'
            f'<Transport xmlns="{TT}"><Protocol>RTSP</Protocol></Transport>'
            f"</StreamSetup><ProfileToken>{_xml_escape(profile_token)}</ProfileToken></GetStreamUri>",
        )
        uri = _text(body, "MediaUri/Uri")
        if not uri:
            raise ProviderError("onvif.no_stream_uri")
        parts = urlsplit(uri)
        if parts.scheme not in ("rtsp", "rtsps"):
            raise ProviderError("onvif.no_stream_uri")
        path = parts.path or "/"
        if parts.query:
            path += "?" + parts.query
        return parts.port or 554, path


def select_channel_profiles(
    profiles: list[OnvifProfile], channel: int
) -> tuple[OnvifProfile, OnvifProfile | None]:
    """Group profiles by video source (one per NVR channel); pick main (largest) and sub."""
    groups: dict[str, list[OnvifProfile]] = {}
    for p in profiles:
        groups.setdefault(p.source, []).append(p)
    ordered = list(groups.values())
    if not 1 <= channel <= len(ordered):
        raise ProviderError("onvif.channel_not_found", channels=len(ordered))
    group = sorted(
        ordered[channel - 1], key=lambda p: (p.width or 0) * (p.height or 0), reverse=True
    )
    return group[0], (group[-1] if len(group) > 1 else None)


async def ws_discover(timeout: float = 3.0) -> list[dict[str, Any]]:
    """Multicast WS-Discovery. Only finds devices on the same L2 network as the container."""
    msg_id = f"uuid:{uuid.uuid4()}"
    probe = (
        f'<?xml version="1.0" encoding="UTF-8"?>'
        f'<e:Envelope xmlns:e="{SOAP_ENV}" '
        f'xmlns:w="http://schemas.xmlsoap.org/ws/2004/08/addressing" '
        f'xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery" '
        f'xmlns:dn="http://www.onvif.org/ver10/network/wsdl">'
        f"<e:Header><w:MessageID>{msg_id}</w:MessageID>"
        f"<w:To>urn:schemas-xmlsoap-org:ws:2005:04:discovery</w:To>"
        f"<w:Action>http://schemas.xmlsoap.org/ws/2005/04/discovery/Probe</w:Action></e:Header>"
        f"<e:Body><d:Probe><d:Types>dn:NetworkVideoTransmitter</d:Types></d:Probe></e:Body>"
        f"</e:Envelope>"
    ).encode()
    loop = asyncio.get_running_loop()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setblocking(False)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
    found: dict[str, dict[str, Any]] = {}
    try:
        sock.sendto(probe, ("239.255.255.250", 3702))
        deadline = loop.time() + timeout
        while (remaining := deadline - loop.time()) > 0:
            try:
                data, addr = await asyncio.wait_for(loop.sock_recvfrom(sock, 65535), remaining)
            except TimeoutError:
                break
            try:
                root = fromstring(data)
            except Exception:  # noqa: S112  (ignore malformed replies)
                continue
            xaddrs = (_text(root, "ProbeMatch/XAddrs") or "").split()
            scopes = (_text(root, "ProbeMatch/Scopes") or "").split()
            name = next((s.rsplit("/", 1)[-1] for s in scopes if "/name/" in s), None)
            hw = next((s.rsplit("/", 1)[-1] for s in scopes if "/hardware/" in s), None)
            ports = [urlsplit(x).port or 80 for x in xaddrs]
            found[addr[0]] = {"ip": addr[0], "onvif_port": ports[0] if ports else 80,
                              "name": name, "hardware": hw}
    except OSError:
        pass
    finally:
        sock.close()
    return list(found.values())
