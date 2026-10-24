# Health hub API contract

This is the read-only versioned API for local clients and Home Assistant. It is separate from the phone upload receiver and from the browser dashboard. Requests use `Authorization: Bearer <token>`. The API must be reachable through `/api/v1/` even when an interactive proxy login protects the dashboard; the bearer token remains mandatory. Never bypass bearer checks for `/api/settings/`, dashboard pages, or upload routes.

Initialization migrates the shared password into the bootstrap administrator named by `PH_ADMIN_USERNAME` (default `admin`), using `WEARER_NAME` for its display name. `PH_PASSWORD_HASH` is bootstrap-only; `PH_SESSION_SECRET` remains required. Login uses a JSON `{username,password}` body at `POST /auth/login`, with `GET /login` and `POST /auth/logout`. Settings requests require the current `ph_session` cookie and `X-PH-Request: 1` CSRF protection. Password or status changes bump the account's session version.

## Endpoints and scopes

| Endpoint | Scope | Result |
| --- | --- | --- |
| `GET /api/v1/summary` | `summary:read` | Current compact metrics |
| `GET /api/v1/minutes` | `history:read` | Bounded minute history |
| `GET /api/v1/workouts` | `history:read` | Bounded workouts |
| `GET /api/v1/sleep` | `history:read` | Bounded sleep records |
| `GET /api/v1/oxygen` | `history:read` | Bounded oxygen records |
| `GET /api/v1/weights` | `history:read` | Bounded weight records |
| `GET /api/v1/hrv-sessions` | `history:read` | Session summaries |
| `GET /api/v1/hrv-sessions/<id>/raw` | `raw:read` | One raw session payload |

Summary returns `{api_version: "1", generated_at, timezone, metrics}`. Each metric is either a value object or `null`; a value object carries `value`, `unit`, `status`, `estimated`, and `observed_at` when applicable. The metric keys are `readiness`, `sleep_score`, `sleep_hours`, `overnight_pulse`, `overnight_strain`, `spo2`, `weight`, `steps`, `watch_battery`, `training_load`, `acute_load`, `chronic_load`, `hrv_rmssd`, and `breathing_rate`.

History uses half-open UNIX-second bounds: `start` is inclusive and `end` is exclusive. Weight records use their calendar dates converted to the configured timezone before filtering. Without a range, the last seven days are returned; a requested window may span at most 365 days. `hrv_rmssd` and `breathing_rate` remain null while stock PPI physiology is unvalidated; diagnostic recordings require the raw scope. Health API responses are never cached for offline access.

Every history response is bounded by `limit` (default 100, maximum 1000) and an opaque `cursor`; clients must send the returned cursor unchanged and must not construct one. The response envelope is:

```json
{
  "api_version": "1",
  "generated_at": 1710000000,
  "items": [],
  "pagination": {"limit": 100, "next_cursor": null}
}
```

## Password and token separation

API bearer tokens cannot manage dashboard settings. Before the registry exists, set the bootstrap password with:

```sh
python3 scripts/set-password.py --bootstrap
```

After initialization, reset an existing username inside the web container: `docker compose exec web python scripts/set-password.py --username USERNAME`. The script updates the registry row and bumps `session_version`; it refuses unknown users and does not rewrite `PH_PASSWORD_HASH` or rotate the global session secret. Initialization writes a one-time password to the ignored `data/bootstrap-password.txt` with mode 600. Never paste passwords, session secrets, bootstrap files, or bearer tokens into Git, issues, chats, or screenshots.

API tokens are named, scoped to `summary:read` by default, optionally granted `history:read` and `raw:read`, expiring, revocable and bound to their account. Members' tokens access only their own history; account administration does not grant default health-history access to others. Existing watch upload tokens remain separate and are not API read tokens.

Pairing is account and device scoped. `/pair` uses the first active device by default; clients may select `/pair?kind=history&device=<device-id>` or use `/api/pair`. Disabling a device invalidates its pairing credentials and re-enabling requires repair. Labels identify enrollment records and are not verified hardware bindings. Multiple devices aggregate into one person's history database; simultaneous-device duplicate claims are not deduplicated.

For private deployments, keep the default localhost bind or use an authenticated VPN/reverse proxy. Use HTTPS for any reachable host. This API exposes health history and raw recordings; treat tokens and backups as private credentials.

## Home Assistant summary coverage

`/api/v1/summary` also returns `account: {id, username, display_name}` for the authenticated token owner, so clients can pin account identity across token renewal. Passwords, hashes, roles and tokens are never included. `metrics` is additive; clients should discover its keys instead of assuming a fixed count. Daily canonical-minute totals are labelled `observed_partial_day` and include `observed_minutes` and `elapsed_minutes`. Missing days are not filled. Body composition retains its measured calendar date and remains account-scoped. See the [sensor integration](integrations/homeassistant/README.md) for the complete metric categories and historical-data limits.

### Watch battery provenance

Battery is independent of health-history uploads. Current battery is selected by its
measurement timestamp across direct GravelEx BLE observations and legacy watch-app
snapshots. A backfill's upload time never makes a cached battery measurement newer.
Values must be whole percentages from 0 through 100; zero is a real reading.
Measurements older than six hours are withheld from the current `watch_battery`
metric (unknown in HA). PH keeps the dated last reading for diagnostics.

GravelEx uploads `watch_status` alongside health records, or in a status-only batch
when there is no new health history. Its fields are `battery_percent`, `observed_at`
(Unix seconds from the actual watch GATT read/notification), `source: gravelex_ble`,
and the selected watch's `device_id`. It never exports phone battery as watch battery.
Dashboard/HA/LLM context share the same resolved observation. Account credentials
continue to determine storage ownership; `device_id` is provenance, not authority.

Current steps/activity and the latest-heart-rate headline use canonical dated minute
observations, not the last legacy watch-app status packet. Daily totals are partial:
unsynced minutes remain unknown. Explicit `snapshot_*` API metrics retain their
original dates and are historical snapshots, not today's totals. Server receipt age
includes GravelEx batches, independently of each measurement's observation time.
