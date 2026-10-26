# Camdash: unified private camera dashboard

A self-hosted dashboard for Imou and BitVision (and generic RTSP/ONVIF) cameras.
It runs as one Docker Compose stack, costs €0 and is never exposed to the public
internet.

> **Status: Stage 2 (app shell, auth, persistence).** Camera providers,
> streaming and the PWA come in later stages. See
> [docs/compatibility-report.md](docs/compatibility-report.md) for what each
> camera type can and cannot do.

## Install

Requirements: a 64-bit Linux host (Raspberry Pi 5 or amd64) with Docker and the
Compose plugin.

```sh
cp .env.example .env
# Fill in CAMDASH_ENCRYPTION_KEY and CAMDASH_ADMIN_PASSWORD (see comments in the file)
docker compose up -d --build
```

Open <http://127.0.0.1:8080> on the host and sign in with the admin credentials
from `.env`. The admin is created **only on the first start**. Changing the
password in `.env` later does not overwrite it.

Data lives in the named volume `camdash-data` and survives
`docker compose down && docker compose up -d`. (`down -v` deletes it.)

## Security model

- The web port binds to `127.0.0.1` by default. Nothing listens on the LAN or the internet.
- Passwords are hashed with Argon2id. Session cookies are `HttpOnly`, `Secure`,
  `SameSite=Strict`, and the token is stored only as a SHA-256 hash.
- Every state-changing request needs an `X-CSRF-Token` header that matches the session,
  plus a same-origin `Origin` check.
- Failed logins are rate-limited per client IP and per username (default 5 per 15 min).
- Camera credentials are encrypted at rest with `CAMDASH_ENCRYPTION_KEY`
  (Fernet / AES-128-CBC + HMAC-SHA256). **Back up this key.** Without it the stored
  credentials can't be recovered.
- The container runs as a non-root user with a read-only root filesystem, all
  capabilities dropped and a 256 MB memory limit.

## Live view

- Video goes **camera → go2rtc → backend → browser** over the same web port. The backend
  proxies go2rtc's MSE stream (fMP4 over WebSocket), checking the session and same-origin
  on every connection. go2rtc has no published ports and the browser never sees camera URLs.
- No transcoding: H.264 plays everywhere. H.265 plays only in browsers with HEVC support
  (Safari, Chrome with hardware decoding). The camera test warns about it.
- iPhone/iPad need **iOS 17.1+** (ManagedMediaSource).
- Grid tiles use the substream and start only while visible. Battery cameras start
  only on tap. A stream stops `CAMDASH_STREAM_IDLE_SECONDS` (default 60) after the last
  viewer leaves. `CAMDASH_MAX_STREAMS` (default 6) is **not yet measured** on a Pi 5.
- A camera is marked *verified* only after real video has reached a browser.

## Remote access (private only)

Don't port-forward this app. Options, all free:

- **Tailscale** (free personal plan): install it on the host, then
  `tailscale serve --bg 8080` publishes the app over HTTPS **inside your tailnet only**.
  It also gives phones the HTTPS that iOS needs for secure cookies.
- **WireGuard** on your router or host: connect over VPN, then use a reverse proxy
  with a certificate trusted by your devices.

If a VPN or reverse proxy on the host must reach the container on a different
address, change `CAMDASH_BIND_ADDRESS` (e.g. to the host's Tailscale IP). Never use `0.0.0.0`
on a host that's reachable from the internet.

## Backup and restore

```sh
# Backup (consistent copy while running; WAL mode)
docker compose exec app python -c "import sqlite3; s=sqlite3.connect('/data/camdash.db'); d=sqlite3.connect('/data/backup.db'); s.backup(d); d.close()"
docker compose cp app:/data/backup.db ./camdash-backup.db
# Also keep a copy of .env (contains the encryption key) somewhere safe and offline.

# Restore
docker compose down
docker run --rm -v camdash_camdash-data:/data -v "$PWD":/b alpine sh -c "cp /b/camdash-backup.db /data/camdash.db && rm -f /data/camdash.db-wal /data/camdash.db-shm && chown 10001:10001 /data/camdash.db"
docker compose up -d
```

## Development

```sh
# Backend (Python 3.12+)
cd backend && python -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/pytest && .venv/bin/ruff check . && .venv/bin/mypy app tests

# Frontend (Node 22+)
cd frontend && npm ci && npm run typecheck && npm run lint && npm test && npm run build
npm run dev   # proxies /api to 127.0.0.1:8000
```

---

## Ātrā palaišana (latviski)

1. Nokopējiet `.env.example` uz `.env` un aizpildiet `CAMDASH_ENCRYPTION_KEY` un
   `CAMDASH_ADMIN_PASSWORD` (vismaz 12 rakstzīmes).
2. Palaidiet `docker compose up -d --build`.
3. Atveriet <http://127.0.0.1:8080> un piesakieties ar administratora datiem no `.env`.
4. Attālinātai piekļuvei izmantojiet VPN (piemēram, Tailscale vai WireGuard). Nekad
   neatveriet šo lietotni publiskajam internetam.
5. Regulāri dublējiet datubāzi un `.env` failu (tajā ir šifrēšanas atslēga).
