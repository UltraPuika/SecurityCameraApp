# Compatibility report

Status: **Stage 1 research, before any camera has been tested.** Nothing here is
*verified* yet. A camera becomes *verified* only after real video from it has
played through this app. Confidence levels:

- **verified**: real video tested end-to-end in this app
- **documented**: stated in official vendor docs (cited)
- **community**: stated by a third-party project or user report (cited)
- **unknown**: no reliable source; needs a test on the real device

Last researched: 2026-10-23.

---

## 1. Imou (via Imou Base Station Pro D2A / WA1001-300)

> **Model check:** in the Imou Life app the user sees only the *Base Station Pro D2A*
> as a device, so the battery cameras are **channels of the base station**. In the
> Open Platform API, a multi-channel device is addressed as `deviceId` (base
> station serial) + `channelId` (one per camera). `bindDeviceLive` and
> `createDeviceRtmpLive` both take `channelId`, and the official HA integration
> exposes each channel as its own camera. "LW08C" is the BitVision kit model,
> not an Imou camera. The cameras' own model numbers are still unknown (not
> required for the cloud path).

### 1.1 Findings

| Question | Finding | Confidence | Source |
|---|---|---|---|
| Free developer account for own devices? | Yes. You register at open.imoulife.com, create an app and get an AppId/AppSecret. Devices on your Imou account are reachable through the HTTP API. | documented | [Imou official HA integration README][imou-ha] |
| Quota model | Each API has a **daily call cap**, e.g. `accessToken` 2,000/day, `bindDeviceLive` 10,000/day, `deviceOnline` 100,000/day. If you exceed it you get error `OP1011`. A separate **monthly resource quota** per AppId covers API calls *and* video playback and is shown under *Console → My Resources*. The free amounts are not published in the public docs. | documented (caps) / unknown (free monthly amount) | [limit.html][imou-limit], [imou-ha] |
| Device count limit | Error `FL1001 "Insufficient remaining available licenses"` after **5 devices** per developer account (2022–2024 community report; may have changed). | community | [user2684/imou_life README][imou-legacy] |
| Token lifetime | `accessToken` lasts **3 days**. Refresh it before expiry or when you get `TK1002`. | documented | [accessToken.html][imou-token] |
| Live view API | `bindDeviceLive` creates **HLS** URLs (HD main or SD sub) and `createDeviceRtmpLive` returns **RTMP** URLs (`rtmp` SD, `rtmpHD`). Both are relayed through Imou's cloud. | documented | [bindDeviceLive][imou-live], [createDeviceRtmpLive][imou-rtmp] |
| Live URL security | The docs warn that *"after the live broadcast address is made public, others can directly view the camera video"*. The URL itself works as a bearer credential, so it **must stay server-side**. | documented | [bindDeviceLive][imou-live] |
| Identity verification | Error `LV1008`: *"Real-name authentication is required to create a live broadcast"*. Individual developers must upload ID in the console before any live address can be created. The app surfaces this as *unsupported, with the reason*. | documented | [global return codes][imou-codes] |
| Request signing | `sign = Base64(HMAC-SHA256("time:{t},nonce:{n},appSecret:{s}", hex(SHA-256(appSecret))))`. The app's unit test reproduces the official test vector. | **verified** (test vector) | [develop.html][imou-dev] |
| Stream duration / resolution | Not documented per call. `liveStatus = 3` means "insufficient traffic", so live time draws on a traffic quota. The official integration fetches a fresh address after about 10 s with no viewers. | documented (status code) / community (10 s) | [bindDeviceLive][imou-live], [imou-ha changelog][imou-ha-cl] |
| Local RTSP/ONVIF on battery cameras behind D2A | **Probably not.** The vendor's own integration says live view is a cloud stream and explicitly lists "local camera RTSP" as unsupported. Battery cameras sleep and don't hold a listening socket. | community (vendor-authored) / unknown for your exact models | [imou-ha configuration guide][imou-ha-cfg] |
| Local RTSP/ONVIF on the D2A base station | **Unknown.** No document found. To check it, I would scan the base station's LAN IP for TCP 554, 80, 37777 and 3702/udp on your network. | unknown | — |
| Existing open-source integrations | (1) **Imou-OpenPlatform/Imou-Home-Assistant** (MIT, official, active) built on **pyimouapi**. (2) **user2684/imou_life** + `imouapi`, which is unmaintained and says newer models need undocumented APIs. | community | [imou-ha], [imou-legacy] |
| Reusable as a dependency? | **pyimouapi** is the most promising, but I couldn't read its PyPI page (captcha) to confirm its licence or API stability. Plan: write a thin client over the *documented* HTTP endpoints only (`accessToken`, `deviceOnline`, `bindDeviceLive`/`createDeviceRtmpLive`, `setDeviceSnap`). Swap in pyimouapi later if its licence (MIT expected) is confirmed. | unknown | — |
| Sleeping cameras: wake latency | Not documented. The official integration waits **5–60 s (default 5 s)** before retrying a command to a sleeping device, which points to several seconds of wake time. My estimate is 5–15 s to first frame. | community / unknown | [imou-ha changelog][imou-ha-cl] |
| Sleeping cameras: battery impact | Not documented. Each live session wakes the radio and sensor, and continuous viewing will drain a battery camera quickly. | unknown | — |

### 1.2 Design consequences

- Imou tiles are labelled **"cloud-relayed"**. The backend fetches the RTMP or HLS
  URL and hands it to go2rtc, which pulls it (RTMP natively, HLS via ffmpeg
  remux). The browser only ever gets the app's own WebRTC/MSE endpoint.
- Battery cameras are **never auto-started** by grid visibility. The tile shows the
  last cloud cover image and a "tap to wake" action, with a short hard session cap
  (default 60 s idle). This protects both battery life and quota.
- One shared upstream per stream. Token cached for about 2.5 days in the encrypted DB.
  Quota errors map to `QuotaExceeded`.
- Codec of the cloud relay is **unknown**. If it's H.265, the tile shows a
  warning (see §3).

## 2. BitVision-managed IP cameras

### 2.1 Your devices

| Device | Model | Firmware |
|---|---|---|
| Wi-Fi system IPC (camera) | LW5B2 | `MFG5W_16NE_ALW_v1.0.0.241127_R1` |
| Wi-Fi system NVR | (kit model probably **LW08C**, from the firmware string) | `N3004_32NR_BDH1LW08C_V2.0.1.241217_R2` |

### 2.2 Platform

BitVision is the viewer app for the **HEROSPEED / Longse** OEM platform. The
independent BitVision docs name both vendors, and the NVR PC search tool is
downloaded from herospeed.net ([bitvisionapp.org/docs][bv-docs],
[Wi-Fi kit guide][bv-kit]). Your hardware is a **Wi-Fi NVR kit**: the cameras pair to the NVR
over the NVR's own wireless link ("Wireless Code Add"). They are usually **not on
your LAN**. Only the NVR's RJ45 port is on your LAN, so **the NVR is the
integration point** and each camera is one NVR channel.

| Item | Finding | Confidence | Source |
|---|---|---|---|
| ONVIF on the NVR | Retail listings for the same BitVision Wi-Fi NVR family give "ONVIF 2.4" and RTSP/RTP/RTCP among network functions. | community (vendor listing) | [store listing][bv-nvr] |
| ONVIF/RTSP on the cameras | Herospeed IPC manual: "ONVIF 2.4 / RTSP". Kit cameras sit on the NVR's private Wi-Fi, so they're likely not reachable directly. | documented (generic IPC) / unknown (LW5B2 reachability) | [device manual][bv-dev] |
| Default credentials | NVR `admin` / `12345`. **Change it.** The dashboard will refuse to save this default. | documented | [bv-kit-online] |
| RTSP port | 554 (Herospeed/Longse default). | community | [ispy herospeed][ispy-hs] |
| RTSP path | Herospeed/Longse firmware has used several formats (`/0`, `/1`, `/ch0_0.h264`, `/cam1/onvif-h264`, …). The NVR's per-channel format is **unknown**. **Plan:** read it authoritatively via ONVIF `GetProfiles` → `GetStreamUri` (one profile pair per channel). The preset list is only a fallback. | unknown | [ispy herospeed][ispy-hs], [ispy longse][ispy-ls] |
| Codec | The NVR records H.264/H.265/H.264+/H.265+. Camera encoding (codec, sub-stream, "H.265+") is set per stream in the web UI. **Recommendation:** set the sub-stream to H.264 and turn off H.265+/H.264+. | documented (settings exist) / unknown (your defaults) | [web settings][bv-web] |
| Sub-stream | Separate sub-stream configurable per camera. | documented | [web settings][bv-web] |
| Wi-Fi bandwidth | NVR wireless bandwidth ≤ 28 Mbit/s total (8-ch model). Pulling every main stream at once may saturate the link. Prefer sub-streams in the grid. | community (spec sheet) | [store listing][bv-nvr] |
| Cloud/P2P | Out of scope: undocumented vendor P2P, no official API. | — | — |

**Path:** the BitVision provider is a preset layer over generic RTSP/ONVIF that
targets the **NVR IP**, with *channel* as a field. Discovery goes ONVIF first,
then preset RTSP templates, then a manual path.

## 2b. Recordings and motion events (requested after Stage 3)

| Device | Motion / events | Recording playback | Confidence |
|---|---|---|---|
| Imou (D2A cameras) | `getAlarmMessage`: list per channel and time range with time, type (PIR, motion, low battery, …) and picture URLs; 20,000 calls/day; polling (push needs a public URL, so it's not used). Pictures may be **encrypted**: the official HA integration decrypts them with native libraries that are **linux x86-64 only**, so on the Pi images may not be viewable. | `queryLocalRecords` lists clips (time, type `Event`, size) from the base station/SD card. The **HTTP API has no playback URL**. Playback goes through the Imou SDK / player (to research: does the "light application" web player work without paid services?). Cloud recordings need a paid cloud-storage package, so they're excluded (€0 rule). | documented (list) / unknown (playback) |
| BitVision NVR | ONVIF events (PullPoint, `RuleEngine/CellMotionDetector`), if the NVR supports them. Verify on the device. | NVR records to its HDD. Possible through ONVIF Profile G (`FindRecordings` / `GetReplayUri`) if supported. Alternative: the app records itself on the Pi (`-c copy`, low CPU, needs a disk). | unknown (needs the reachable NVR) |

## 3. Platform / codec constraints (Raspberry Pi 5)

- No hardware H.264/H.265 encoder; HEVC **decode** only. **Default: pass-through.**
- WebRTC H.265 works in Safari 18+ and in recent Chrome with hardware support, but
  not reliably elsewhere. H.265-only cameras get flagged on the tile (*"H.265:
  may not play in this browser"*) instead of being silently transcoded.
- Concurrent stream limit: **to be measured** in Stage 5. Not guessed.

## 4. Per-device summary

| Device | Integration method | Prerequisites | Expected latency | Cost | Limitations | Confidence | Recommended path |
|---|---|---|---|---|---|---|---|
| Imou battery cameras (behind D2A) | Imou Open Platform → RTMP/HLS cloud relay → go2rtc → WebRTC | Free developer account, AppId/AppSecret, cameras on that Imou account | RTMP ~2–5 s; HLS ~5–15 s; plus wake 5–15 s (estimates) | €0 within free quota | Cloud-only; daily caps and monthly quota; possible 5-device licence limit; battery drain; codec unknown | documented (API) / unknown (quota, codec, latency) | Imou provider, tap-to-wake, cloud-relayed label |
| Imou D2A base station | None needed for video (cameras are addressed individually through the cloud) | — | — | €0 | Local RTSP unknown | unknown | Optional LAN port scan to rule local access in or out |
| BitVision Wi-Fi NVR kit (NVR + LW5B2 cameras) | NVR RTSP per channel via ONVIF `GetStreamUri` (or preset path) → go2rtc pass-through | Route to the **NVR's** LAN IP (LAN/VPN), NVR admin password changed from default, ONVIF/RTSP enabled on the NVR | ~0.5–1.5 s (estimate: camera→NVR Wi-Fi hop + WebRTC) | €0 | Channel path format unknown; codec defaults unknown; shared NVR Wi-Fi bandwidth | community / unknown | Generic RTSP/ONVIF + BitVision NVR preset |

## 5. Build vs reuse (Stage 2d)

| Option | Fit |
|---|---|
| **go2rtc UI** | A streaming engine with an admin UI. It has no proper user auth (only optional basic auth), no i18n, no PWA and no camera status model, and its config exposes source URLs **including credentials**. Fails rules 4 and 6 on its own, but is ideal *underneath* as the streaming engine. |
| **Frigate** | A full NVR (recording plus object detection). Heavier on a Pi 5, cameras are managed in YAML (no "test before save"), there's no Imou cloud provider and no "unsupported/needs setup" tiles, and Latvian isn't available. Customising those would mean forking. |

**Recommendation: A, a custom app with go2rtc as the streaming engine.** Neither tool
meets the auth/secret rules, the honest-status tiles, the Imou cloud lifecycle
(token refresh, quota, wake) or lv/en localisation without forking. go2rtc
already does the hard part (RTSP/RTMP ingest, WebRTC/MSE output, shared
upstreams), so the custom layer is mainly auth, provider logic and UI.

[imou-ha]: https://github.com/Imou-OpenPlatform/Imou-Home-Assistant
[imou-ha-cl]: https://github.com/Imou-OpenPlatform/Imou-Home-Assistant/blob/main/CHANGELOG.md
[imou-ha-cfg]: https://github.com/Imou-OpenPlatform/Imou-Home-Assistant/blob/main/guides/configuration.md
[imou-legacy]: https://github.com/user2684/imou_life
[imou-codes]: https://open.imoulife.com/book/faq/code.html
[imou-dev]: https://open.imoulife.com/book/http/develop.html
[bv-docs]: https://bitvisionapp.org/docs
[bv-kit]: https://bitvisionapp.org/docs/wifi-kit
[bv-kit-online]: https://bitvisionapp.org/docs/wifi-kit/getting-online
[bv-dev]: https://bitvisionapp.org/docs/device-manual
[bv-web]: https://bitvisionapp.org/docs/device-manual/web-settings
[bv-nvr]: https://store.eyeseecomputers.com/product/bitvision-onvif-8ch-wifi-nvr/
[ispy-hs]: https://www.ispyconnect.com/camera/herospeed
[ispy-ls]: https://www.ispyconnect.com/camera/longse
[imou-limit]: https://open.imoulife.com/book/faq/limit.html
[imou-token]: https://open.imoulife.com/book/http/accessToken.html
[imou-live]: https://open.imoulife.com/book/http/device/live/bindDeviceLive.html
[imou-rtmp]: https://open.imoulife.com/book/http/device/live/createDeviceRtmpLive.html
