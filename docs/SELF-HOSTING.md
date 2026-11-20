# Self-hosting guide: Pebble watch → GravelEx → health hub → apps

This guide sets up the whole stack from nothing. When you finish, a Pebble watch's health
data reaches your own server, and you can view it in a browser and in the Android app.

```
Pebble watch ──BLE──▶ GravelEx (Android, tdgs.gravel) ──HTTPS──▶ health hub (Docker)
     │                                                            │
     └─ HRV watch app (nightly pulse-interval recording) ─────────┤
                                                                  ├─▶ Dashboard PWA (browser)
                                                                  ├─▶ Pebble Health Android app
                                                                  └─▶ Home Assistant / API clients
```

| Component | Where | Purpose |
|---|---|---|
| GravelEx | this repo, GitHub releases | Pebble companion app. It also exports watch health data to the hub. |
| Health hub | [`health-hub/`](../health-hub/) | Receives uploads, stores them in SQLite, computes metrics, and serves the dashboard and API. |
| HRV watch app | [`health-hub/watchapps/hrv-watch`](../health-hub/watchapps/) | Records pulse intervals for 3 minutes each night. These recordings are the input for HRV. |
| Pebble Health app | [icewall905/pebble-health](https://github.com/icewall905/pebble-health) | Native Android client that reads the hub API. |

Read time: 10 minutes. Setup time: about 30 minutes. Overnight metrics fill in over the
following days (see [Timeline](#7-what-to-expect-and-when)).

## 1. Server requirements

- Any Linux host with Docker Engine and Compose v2 (x86-64 or arm64). 1 GB RAM is enough.
- Python 3, used only by the setup script.
- An HTTPS hostname that your phone can reach, served by a reverse proxy (Caddy, nginx,
  Traefik) or reached over a VPN such as Tailscale or WireGuard. The phone apps only accept
  HTTPS.

## 2. Install the hub

```sh
git clone https://github.com/icewall905/gravelex.git
cd gravelex/health-hub
./scripts/init-env.sh             # creates a mode-600 .env with generated secrets
$EDITOR .env                      # set the values below
docker compose up -d --build
docker compose ps                 # web (8790) and receiver (9998) should be healthy
cat data/bootstrap-password.txt   # initial admin password, shown once
```

Set these values in `.env`:

| Variable | Example | Why |
|---|---|---|
| `PEBBLE_TZ` | `Europe/Copenhagen` | IANA time zone. It sets day and night boundaries, the time of the nightly rollup, and DST handling. **Required.** |
| `PUBLIC_URL` | `https://health.example.net` | Used for links, pairing and the PWA. |
| `ALLOWED_HOSTS` | `health.example.net` | Host-header allow list. |
| `WEARER_NAME` | `Alex` | Display name of the first account. |
| `BIND_ADDRESS` | `127.0.0.1` | Keep this when using a reverse proxy on the same host. |

Every other variable, including Home Assistant, MQTT, external weight sources and the LLM
briefing, is optional. They are documented in [health-hub/README.md](../health-hub/README.md#configuration).

### Reverse proxy

Send everything to `127.0.0.1:8790`. Do **not** put an extra interactive login in front of
`/fitness/*` (phone uploads) or `/api/v1/*` (apps and Home Assistant). Both accept only
their own bearer tokens. A minimal Caddy example:

```
health.example.net {
    reverse_proxy 127.0.0.1:8790
}
```

Open `https://health.example.net` and sign in as `admin` with the bootstrap password. Then
change the password: `docker compose exec web python scripts/set-password.py --username admin`.

## 3. Install GravelEx and export data

1. Install [Obtainium](https://github.com/ImranR98/Obtainium) on the phone. Add
   `https://github.com/icewall905/gravelex` and install GravelEx. Check that the signing
   certificate matches [`docs/gravelex-signing-sha256.txt`](gravelex-signing-sha256.txt).
2. Pair the watch in GravelEx. Only one companion app should manage the watch at a time.
3. On the hub, open **More → Phone app · GravelEx → Health export setup and token**. Create a history
   upload token. It can upload only, and it expires after 30 days without use.
4. In GravelEx, open **Settings → Health → GravelEx health data export**. Enter the hub URL
   and the token, turn on automatic export, then tap **Save**, **Test** and **Sync**.
5. Turn off Android battery optimisation for GravelEx. Without that, uploads stall in the
   background.

### Watch settings (important)

These settings decide how much data there is to show. Change them on the watch under
**Settings → Health**, or in GravelEx's watch settings:

| Setting | Value | Effect |
|---|---|---|
| HR Monitoring | **5 min** | The watch measures heart rate only in short windows at each interval. With the default of 10 minutes, or 30–60 minutes, the heart-rate charts and resting HR stay sparse. See [FIRMWARE-2026-11.md](../health-hub/FIRMWARE-2026-11.md). |
| HR During Activity | **On** | Records heart rate every second during walks and runs. |
| SpO₂ | **On** (on the watch itself) | On firmware ≥ 4.42, GravelEx's SpO₂ toggle writes an old preference key that the watch no longer reads. |
| Sleep tracking | On, and wear the watch in bed | Sleep sessions feed sleep, readiness and resting HR. |

## 4. HRV: install the HRV watch app

Stock minute records do not contain beat intervals. The HRV watch app wakes at night and
records pulse intervals for about 3 minutes. The hub turns that recording into an
**estimated** nightly RMSSD (see [METRICS.md](../health-hub/METRICS.md#hrv)).

```sh
# Needs the Pebble SDK CLI (`pebble`). Builds four .pbw files into health-hub/dist/watchapps.
PUBLIC_URL=https://health.example.net ./scripts/build-watch-apps.sh
```

Install `pebblefit-hrv.pbw` through GravelEx. Open the app's settings to pair it with the
hub, then open the app once on the watch so it schedules its night-time wake-ups. The other
watch apps (history, today, legacy status) are optional.

## 5. Install the Android app (Pebble Health)

1. On the hub, open **More → API access**. Create a token with scopes `summary:read` and
   `history:read`, then copy it. It is shown only once.
2. In Obtainium, add `https://github.com/icewall905/pebble-health`. Check that the signing
   certificate matches `docs/signing-sha256.txt` in that repository.
3. Open the app, then enter the hub URL and the token.

To build and sign your own copy, see that repository's README.

## 6. Keep it running

| Task | Command (in `health-hub/`) |
|---|---|
| Update | `git pull && docker compose build && docker compose up -d` (rebuild **all** services, because web, receiver and briefing share one image) |
| Back up | `./scripts/backup.sh` (online SQLite backup, mode 600, contains health data and secrets) |
| Roll back | Before an update, run `docker tag gravelex-health-hub:local gravelex-health-hub:before-YYYYMMDD`. To roll back, retag it and run `up -d`. |
| Logs | `docker compose logs -f web receiver` |
| Health | `curl -fsS http://127.0.0.1:8790/healthz` |
| Reset password | `docker compose exec web python scripts/set-password.py --username USER` |

`docker compose down -v` deletes the `health-data` volume, which holds all of your history.

## 7. What to expect and when

| Metric | Appears after | Notes |
|---|---|---|
| Steps, calories, distance, minute HR | First sync | HR density depends on the HR Monitoring interval. |
| Sleep | First morning sync | Short watch sessions are replaced with longer stillness-based estimates where possible (see METRICS.md). |
| Resting HR | First night with ≥ 20 HR readings between 00:00 and 06:00 | |
| HRV last night | First scheduled HRV recording | |
| HRV status (balanced, low, …) | 3 nights this week + 14 baseline nights | Shows "Learning your usual range" until then. |
| Readiness | HRV baseline + last night's HRV + sleep | Until then, a stock-firmware estimate is used where possible. |
| Training load | 42 consecutive days confirmed in the dashboard | |
| SpO₂ | First valid watch reading | Spot readings only, not continuous monitoring. |

## 8. Troubleshooting

| Symptom | Check |
|---|---|
| Dashboard shows "waiting" or "no data" | **More → Collection health** shows upload receipts and coverage. In GravelEx, tap Test/Sync. Check that the upload token has not expired. |
| HR charts mostly empty | HR Monitoring is set to 30 or 60 minutes. Change it to 5 minutes. |
| HRV status stuck at "Learning" | Open the HRV card's detail view, or call `GET /api/v1/hrv-sessions` (`history:read`), to check for recordings. If there are none, the HRV watch app is not installed or not scheduled. Open it once on the watch. |
| No SpO₂ | Turn SpO₂ on in the watch's own Health settings (see above). |
| App shows "401" | The token was revoked or lacks a scope. Create a new one with `summary:read` and `history:read`. |
| Slow dashboard or 500 errors | Check `docker compose logs web`. The image runs gunicorn with 3 workers and a 120 s timeout. Large histories are fine. |
