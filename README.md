# GravelEx

GravelEx is the de-Googled, Android-only Pebble companion app for GrapheneOS, LineageOS, and similar phones. Its Android application id is `tdgs.gravel`. Install releases from the project GitHub repository and track them with [Obtainium](https://github.com/ImranR98/Obtainium).

This is the combined project repository: the extended GravelEx phone app and the Pebble Health dashboard/backend, maintained together on `master`. The self-hosted health hub lives under [`health-hub/`](health-hub/). The phone exports watch data to the hub, which stores it in a private SQLite volume and serves a local PWA and read-only API. The hub works without Google services or Home Assistant.

## Next development priorities

Moving backend-independent health views and calculations into the phone app, phone-assisted GPS workouts, and an audit of additional watch metrics are planned features. The current hub remains necessary for its existing server analytics and household dashboard.

## Home Assistant

Install the [GravelEx Health HACS integration](health-hub/integrations/homeassistant/README.md) to create account-scoped sensors from an existing PH server. The optional [Supervisor app/add-on](homeassistant-addon/README.md) hosts PH inside Home Assistant OS; it is installed through the app/add-on store, not HACS. Both packages use this repository: `https://github.com/icewall905/gravelex`.

## Health hub quick start

1. Install GravelEx from the project GitHub release using Obtainium.
2. Run `cd health-hub && ./scripts/init-env.sh`.
3. Set `PEBBLE_TZ` and review the generated private environment.
4. Start the hub with `docker compose up -d --build` and open `http://localhost:8790`.
5. In the hub, create a phone export token under More → Phone app.
6. Enter the hub HTTPS URL and token in GravelEx Health export settings, then run Save/Test/Sync.

The hub binds to localhost by default. Use an authenticated VPN or HTTPS reverse proxy before allowing LAN access. Home Assistant is optional; no Google service is required. Read [the health-hub guide](health-hub/README.md), [the API contract](health-hub/API.md), and [the Home Assistant REST example](health-hub/integrations/homeassistant/rest.yaml).

## Dashboard and API authentication

The first start uses `PH_PASSWORD_HASH`, `PH_ADMIN_USERNAME` (default `admin`) and `PH_SESSION_SECRET` to create the bootstrap administrator in `health-hub/data/household.sqlite3`; `WEARER_NAME` supplies its display name. The original `fitness.sqlite3`, its history and existing tokens remain owned by that administrator. New household accounts receive their own `data/people/<server-id>.sqlite3` history database. Sign in with a username and password, then use More → Household to manage accounts and devices.

The initial password is written once to the ignored `health-hub/data/bootstrap-password.txt` with mode 600. Before the registry exists, choose a bootstrap password with `python3 scripts/set-password.py --bootstrap`. After initialization, reset an existing account inside the web container: `docker compose exec web python scripts/set-password.py --username admin`. The command bumps that account's session version and does not rewrite bootstrap environment variables. Never put passwords, session secrets, bearer tokens, or bootstrap files in Git or chat.

The versioned `/api/v1/` endpoints use scoped bearer tokens and remain separate from dashboard login. Dashboard settings require the current `ph_session` cookie plus `X-PH-Request: 1` CSRF protection. API bearer tokens cannot manage settings. See [API.md](health-hub/API.md) for scopes, bounded history, and token handling.

## Data limits and firmware

Stock-firmware pulse, overnight strain, and readiness are explicitly estimated and low-confidence. Pulse is a sparse filtered overnight summary, not validated resting heart rate. Strain is a scheduled physiological load proxy, not mental stress. PPI variability remains diagnostic-only. Missing history is not fabricated.

Firmware diagnostics are opt-in and experimental. See [the diagnostics package](health-hub/firmware-diagnostics/README.md) and [preflight status](health-hub/firmware-diagnostics/PREFLIGHT.md). Historical maintainer reports are labelled as such and are not installation approval or a shipping claim. No firmware flashing is part of this documentation workflow.

## Backups and attribution

The `health-data` volume and backups contain private health data. Use `health-hub/scripts/backup.sh`, retain backups privately, and verify restores before removing the original volume. Project source is GPLv3 unless a directory or dependency states otherwise. The previous long upstream-oriented Gravel document is retained as [`UPSTREAM-GRAVEL.md`](UPSTREAM-GRAVEL.md) for attribution and historical detail.
