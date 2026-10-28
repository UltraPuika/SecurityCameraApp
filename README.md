# Camdash: unified private camera dashboard

A self-hosted dashboard for Imou and BitVision (and generic RTSP/ONVIF) cameras.
It runs as one Docker Compose stack, costs €0 and is never exposed to the public
internet.

> **Status:** login, camera management, live view, PWA and an Android app are built.
> Real-hardware verification is still pending. See
> [docs/compatibility-report.md](docs/compatibility-report.md) for what each camera
> type can and cannot do.

## Setup, step by step

### 1. Prepare the server (Raspberry Pi 5 or any 64-bit Linux box)

1. Install **Raspberry Pi OS Lite (64-bit)** with Raspberry Pi Imager. In the imager's
   settings, enable SSH and set a user/password. Connect the Pi by **Ethernet** to the same
   router as the cameras' NVR.
2. Log in over SSH and install Docker:

   ```sh
   curl -fsSL https://get.docker.com | sh
   sudo usermod -aG docker $USER   # log out and back in afterwards
   ```

3. Copy this project to the Pi (`git clone <your GitHub repo URL> camdash`, or copy the
   folder) and `cd camdash`.

> **Just trying it on a Windows PC?** Install Docker Desktop and run the same commands
> in PowerShell from the project folder.

### 2. Configure and start

```sh
cp .env.example .env
# Generate the encryption key and paste it into CAMDASH_ENCRYPTION_KEY:
docker run --rm python:3.13-slim sh -c "pip -q install cryptography && python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'"
nano .env    # set CAMDASH_ENCRYPTION_KEY and CAMDASH_ADMIN_PASSWORD (min. 12 characters)
docker compose up -d --build
docker compose ps   # both "app" and "go2rtc" should become "healthy"
```

Open <http://127.0.0.1:8080> **on the server itself**. To open it from your phone or PC,
see step 5. The admin user is created from `.env` **only on the first start**.

### 3. Add the BitVision cameras (Wi-Fi NVR kit)

Your kit's cameras talk to the NVR over its own Wi-Fi, so the dashboard connects to the
**NVR**, one camera per **channel**.

1. **On the NVR** (its own screen, or `http://<NVR-IP>` in Chrome/Edge):
   - Change the default password (`admin` / `12345`). The dashboard refuses the default.
   - Under *Network*, check that **ONVIF** (and RTSP, port 554) is enabled. Note the NVR's **IP address**.
   - Optional but recommended: under *Camera → Encoding*, set each camera's **sub stream to H.264**,
     and turn off H.265+/H.264+.
2. **In the dashboard:** *Settings → Cameras → Add camera*:
   - Camera type: **BitVision (NVR or camera)**
   - Name and Location, e.g. "Gate" / "Home"
   - IP address: the NVR's IP. Channel: `1` for the first camera, `2` for the second, …
   - Password: the NVR password (username defaults to `admin`)
3. Click **Test connection**. Every step should show ✓, including the codec and
   resolution. Then **Save**. Repeat for each channel.

If the test fails, the failing step says why (wrong password, ONVIF port, NVR not
reachable, …). If ONVIF is off and can't be turned on, untick *Find stream addresses via
ONVIF* and enter the paths manually.

### 4. Add the Imou cameras (D2A base station)

1. In the **Imou developer console** (open.imoulife.com → *My App*), copy the **App ID** and
   **App Secret**, and note your **data centre** (*Basic information → My information*;
   for Latvia usually *Central Europe*). If the console asks for identity verification,
   complete it: Imou requires it before live streams work.
2. In the dashboard: *Settings → Cloud accounts → Add account*. Choose the data centre,
   paste the App ID / Secret, **Test**, then **Save**.
3. Click **Show cameras**. Each camera behind the base station is listed as a
   channel. Click **Add** next to each, give it a name, **Test**, **Save**.

Imou cameras are *cloud-relayed* and battery-powered. They start only when you tap
**Wake and view**, which saves battery and your free Imou quota.

### 5. Open it on your phone

The app is private, so your phone reaches it through a VPN. The easiest free option is
**Tailscale**:

1. Create a free Tailscale account. Install Tailscale on the Pi (`curl -fsSL
   https://tailscale.com/install.sh | sh && sudo tailscale up`) and on your phone.
2. On the Pi: `sudo tailscale serve --bg 8080`. It prints an address like
   `https://camdash.<your-tailnet>.ts.net` that only your own devices can open.
   If sign-in then says *Request blocked*, put that address in `CAMDASH_TRUSTED_ORIGINS`
   in `.env` and run `docker compose up -d`.
3. On the phone, open that address and sign in. Then either:
   - **Install as an app (PWA):** Chrome → ⋮ → *Install app* (Android), or Safari → Share →
     *Add to Home Screen* (iOS 17.1+), **or**
   - **Install the Android APK** (see below) and enter the same address on first launch.

For plain-HTTP testing on the home Wi-Fi only (e.g. `http://192.168.1.50:8080`), set
`CAMDASH_BIND_ADDRESS=0.0.0.0` and `CAMDASH_COOKIE_SECURE=false` in `.env`, then
`docker compose up -d`. Don't do this on a server reachable from the internet.

## Android app (.apk from GitHub)

`mobile/` contains a small Android wrapper (Capacitor). On first launch it asks for your
dashboard address, then opens the dashboard inside the app. Android "Back" returns to that
screen if you want to change servers. GitHub builds it for free with
[.github/workflows/android.yml](.github/workflows/android.yml).

**One-time: create your signing key** (keeps the same signature, so updates install over
the old version). Run on any PC with Java, or in the `eclipse-temurin` Docker image:

```sh
keytool -genkeypair -v -keystore camdash.jks -alias camdash -keyalg RSA -keysize 4096 -validity 10000
base64 -w0 camdash.jks > camdash.jks.b64     # Windows PowerShell: [Convert]::ToBase64String([IO.File]::ReadAllBytes("camdash.jks")) > camdash.jks.b64
```

In GitHub, open your repo → *Settings → Secrets and variables → Actions* and add:
`ANDROID_KEYSTORE_BASE64` (contents of `camdash.jks.b64`), `ANDROID_KEYSTORE_PASSWORD`,
`ANDROID_KEY_ALIAS` (`camdash`), `ANDROID_KEY_PASSWORD`. Keep `camdash.jks` safe and
**never commit it** (it's in `.gitignore`). Without these secrets the build still works
but is debug-signed, so each update needs an uninstall first.

**Build and download:**

- **Automatic:** every push to `main` that changes `mobile/` or the workflow builds a new
  APK and publishes it under the repo's **Releases** (e.g. `camdash-0.0.3.apk`).
- **Versioned:** push a tag (`git tag v0.1.0 && git push origin v0.1.0`) → `camdash-0.1.0.apk`.
- **Manual:** *Actions → Android APK → Run workflow*; it is published to **Releases** too.

On the phone, open the APK and allow *Install unknown apps* for your browser/file manager
when Android asks.

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

Data lives in the named volume `camdash-data` and survives
`docker compose down && docker compose up -d`. (`down -v` deletes it.)

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
Uz Raspberry Pi (64-bit) uzstādiet Docker: `curl -fsSL https://get.docker.com | sh`.
2. Nokopējiet `.env.example` uz `.env` un aizpildiet `CAMDASH_ENCRYPTION_KEY` un
   `CAMDASH_ADMIN_PASSWORD` (vismaz 12 rakstzīmes). Palaidiet `docker compose up -d --build`.
3. **BitVision:** NVR iestatījumos nomainiet noklusējuma paroli un ieslēdziet ONVIF.
   Panelī atveriet *Iestatījumi → Kameras → Pievienot kameru*, izvēlieties
   *BitVision*, ievadiet NVR IP adresi un kanāla numuru (1, 2, …). Spiediet
   *Pārbaudīt savienojumu*, tad *Saglabāt*.
4. **Imou:** *Iestatījumi → Mākoņa konti → Pievienot kontu* (App ID, App Secret, datu
   centrs). Spiediet *Rādīt kameras* un pievienojiet katru kameru.
5. **Telefonā:** uzstādiet Tailscale (bez maksas) uz Pi un telefona, uz Pi palaidiet
   `sudo tailscale serve --bg 8080` un atveriet iegūto `https://…ts.net` adresi.
   Pievienojiet to sākuma ekrānam vai uzstādiet Android APK no GitHub sadaļas *Releases*.
6. Nekad neatveriet šo lietotni publiskajam internetam. Regulāri dublējiet datubāzi un
  0> un piesakieties ar administratora datiem no `.env`.
4. Attālinātai piekļuvei izmantojiet VPN (piemēram, Tailscale vai WireGuard). Nekad
   neatveriet šo lietotni publiskajam internetam.
5. Regulāri dublējiet datubāzi un `.env` failu (tajā ir šifrēšanas atslēga).
