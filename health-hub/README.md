# GravelEx Health hub

The self-hosted companion to the GravelEx Android app (`tdgs.gravel`): a Pebble Health PWA, durable receiver and analytics service. It stores your own watch data in SQLite and works without Google services, Home Assistant, an external database or a cloud LLM. Optional integrations are configured separately. GravelEx Android releases are published through the project GitHub releases and can be tracked with Obtainium.

The API contract is documented in [API.md](API.md). Stock-firmware pulse, strain and readiness outputs are estimates with explicit missingness and low-confidence limits; they are not medical measurements.

## Start a new instance

Requirements: Docker Engine with Compose v2, and Python 3 for the setup script.

```sh
cd health-hub
./scripts/init-env.sh
# Edit .env: choose your IANA PEBBLE_TZ and optional WEARER_NAME.
docker compose up -d --build
docker compose ps
```

Read your initial administrator password with `cat data/bootstrap-password.txt`, then open `http://localhost:8790` and sign in with `PH_ADMIN_USERNAME` (default `admin`). Initialization creates `data/household.sqlite3`; the original `fitness.sqlite3`, history and tokens remain that administrator's data. Additional accounts use separate `data/people/<server-id>.sqlite3` databases and see only their own history. More → Household management lets administrators add, reset, disable and re-enable accounts and manage devices. Disabling invalidates sessions and enrolled credentials; re-enabling requires new tokens. To reset before initialization, run `python3 scripts/set-password.py --bootstrap`. Afterwards run `docker compose exec web python scripts/set-password.py --username USERNAME`; this updates the registry and invalidates that account's sessions. `init-env.sh` creates a fresh receiver credential in a mode 600 `.env`, never prints it, and retains an existing file. `.env`, downloads, databases and backups are Git-ignored. The named `health-data` volume holds SQLite and survives container replacement.

Both published ports bind to 127.0.0.1 by default. On another machine you can initially use SSH port forwarding. To use your phone or install the PWA, provide a reachable HTTPS hostname through your reverse proxy, set `PUBLIC_URL` to that URL and add its hostname to `ALLOWED_HOSTS`. The built-in username/password login protects your dashboard; it fails closed until the session secret and registry are configured. `BIND_ADDRESS` is configurable when an authenticated LAN/VPN deployment needs a different bind.

The browser's `/fitness/*` routes accept scoped bearer tokens themselves; allow these through the proxy without interactive browser authentication so the phone can upload. The built-in login protects dashboard APIs, settings and pairing pages. `/api/v1/*` accepts its own read-only bearer tokens; if you add another proxy login, allow this prefix through to the application so Home Assistant can authenticate. Optional legacy `/health` uploads go to the receiver on 9998 and accept its `AUTH_TOKEN` or a paired history token. Do not publish an unauthenticated dashboard merely because upload routes have tokens.

## Connect GravelEx

1. Install the GravelEx APK (`tdgs.gravel`) from the project's GitHub release repository. You can track that repository in Obtainium.
2. In the hub, open More → Phone app → Health export setup and token, then create a history upload token. It grants upload access, not history reads, and expires after 30 days without use.
3. On the phone, open Settings → Health → GravelEx health data export. Enter this hub's HTTPS URL and token, enable automatic export, then Save/Test/Sync.
4. Health → Blood Oxygen shows actual stored samples; Settings → Health → Blood Oxygen Setup & Status distinguishes the watch preference, local observations and last acknowledged server batch.

The hub's base URL is supplied through public configuration or derived from its browser origin. No deployment hostname is baked into its scripts. A new phone build has no preset destination; existing saved phone settings remain valid.

For an APK download button on your own hub, populate the ignored downloads directory:

```sh
    GRAVELEX_REPOSITORY=OWNER/REPOSITORY ./scripts/fetch-apk.sh
```

Choose your own owner/repository if you maintain a fork. This helper verifies the release checksum before replacing the APK. APK signing remains in the Android release workflow; the hub never receives that private signing key. Set optional `SOURCE_URL` to the public source/instructions URL you want the PWA to link to.

## Watch apps and HRV

GravelEx exports minute HR, steps, movement, calories, distance, sleep/activity sessions and recorded SpO2. Minute HR does not contain the beat intervals needed for HRV. The watch-app source packages under `watchapps/` supply the separate measurement/history/daily-summary paths. Build them with your own `PUBLIC_URL` using `scripts/build-watch-apps.sh`, then install and pair through their watchapp settings. Build output goes into the ignored downloads directory. Authentication is paired at runtime rather than compiled into a watch app.

A watch-history request transfers stored watch data to the phone. Upload now transfers data already stored on the phone to the hub. These are separate actions; SpO2 only appears when the firmware produces a valid measurement. Sparse readings remain gaps and retain their real measurement timestamp and raw device quality.

HRV motion eligibility and the required field study are documented in [MOTION-CALIBRATION.md](MOTION-CALIBRATION.md). Uncalibrated recordings remain diagnostic-only; no universal stillness threshold is supplied.

See [COLLECTION-HEALTH.md](COLLECTION-HEALTH.md) for the More diagnostics panel: upload receipts, actual sensor times, DST-aware daily HR coverage, historical night-slot evidence and unknown phone queue/transfer states.

See [DATA-PROVENANCE.md](DATA-PROVENANCE.md) for immutable ingestion evidence, per-field minute source inspection and the preview-first rebuild tool. Device verification and canonical reconstruction of other streams remain pending.

## Configuration

Every deployment setting is listed in `.env.example`:

| Purpose | Variables |
| --- | --- |
| Private receiver credential | `AUTH_TOKEN` generated by init script |
| Bootstrap administrator username | `PH_ADMIN_USERNAME` |
| Bootstrap password hash (first initialization only) | `PH_PASSWORD_HASH` |
| Dashboard session secret | `PH_SESSION_SECRET` |
| Network and public links | `BIND_ADDRESS`, `WEB_PORT`, `RECEIVER_PORT`, `PUBLIC_URL`, `SOURCE_URL`, `ALLOWED_HOSTS` |
| Motion calibration (optional, evidence required) | `HRV_MOTION_POLICIES` |
| Wearer/local day boundaries | `WEARER_NAME`, `PEBBLE_TZ` |
| Optional HA WebSocket bridge | `HA_WS_URL`, `HA_TOKEN`, `HA_REPORT_SERVICE` |
| Optional MQTT discovery | `MQTT_ENABLED`, `MQTT_HOST`, `MQTT_PORT`, `MQTT_USER`, `MQTT_PASS`, `DISCOVERY_PREFIX` |
| Optional weight/profile SQL | `WEIGHT_PG_DSN`, `WEIGHT_PG_QUERY`, `PROFILE_PG_QUERY` |
| Optional existing scale dashboard API | `HEALTH_DASHBOARD_URL`, `HEALTH_SCALE_USER` |
| Optional local/OpenAI-compatible briefing | `LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY`, `BRIEFING_TIME` |

HA integration and the timestamped oxygen sensor are documented in [integrations/homeassistant](integrations/homeassistant/README.md). The external SQL weight source expects `(date, weight_kg)` rows; the optional profile query expects `(sex, birthdate, height_cm)`. The optional scale dashboard source expects `/api/scales` and `/api/daily` with `user` and `range` query parameters. Omit these integrations when you only want Pebble data.

The API is local-first and read-only. Scoped API tokens are account-bound and members can read only their own history; account administration does not grant default access to other members' health data. Keep API tokens separate from phone upload tokens and dashboard sessions. See [API.md](API.md) for scopes, bounded history queries, login/logout routes, pairing and token handling.

For an LLM briefing, configure both endpoint and model; a local endpoint is supported. Then start the optional service:

```sh
docker compose --profile briefing up -d
```

The LLM receives compact computed facts, including timestamped oxygen samples. It does not calculate training load or invent missing measurements. No endpoint is contacted unless configured.

## Back up, restore and update

```sh
./scripts/backup.sh
# Later, after updating source:
docker compose up -d --build
```

The backup script uses SQLite's online backup API while briefly locking the registry, owner database and all member databases, so committed WAL data is included consistently. It writes a mode-600 outer `health-UTC.tar.gz` containing `data.tar.gz` (the manifest plus `fitness.sqlite3`, `household.sqlite3` and every `people/*.sqlite3`), `deployment.env` and `compose.yaml`. These files contain private health records and credentials; retain the archive privately.

To restore, stop the services and extract the outer archive into a private staging directory, then extract `data.tar.gz`. Retain the original volume and backup until the restored history is verified. Restore the extracted database tree into the named volume with a helper container, for example `docker compose run --rm --no-deps --user 0 --entrypoint sh -v "$PWD/staging/data:/restore:ro" web -c 'cp -a /restore/. /data/ && chown -R 10001:10001 /data'`; remove old SQLite `-wal`/`-shm` sidecars only when replacing a database with its extracted snapshot, then restart. Do not run `docker compose down -v` on data you want to retain.

## Development and checks

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt pytest
python -m pytest backend
node --check web/app.js
node --check web/sw.js
docker compose config --quiet
```

The tests use temporary databases and synthetic fixture observations, never production data. Container health endpoints are `/healthz`; JSON/PWA routes run on the web service, while the receiver supplies the legacy authenticated upload and optional HA/MQTT forwarding. For end-to-end checks, create a scoped token through the dashboard and inspect an actual phone upload and its measurement timestamp.

This source is distributed with the repository's GPLv3 license. The optional third-party HA integration keeps its own upstream license; its source is linked rather than silently vendored.

The legacy status watch app uses a paired history token for `/health`, preserving Home Assistant forwarding. Its token-free package is available at `/download/status` after building the watch apps.
