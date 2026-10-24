# Health hub API contract

This is the read-only versioned API for local clients and Home Assistant. It is separate from the phone upload receiver and from the browser dashboard. Requests use `Authorization: Bearer <token>`. The API must be reachable through `/api/v1/` even when an interactive proxy login protects the dashboard; the bearer token remains mandatory. Never bypass bearer checks for `/api/settings/`, dashboard pages, or upload routes.

The dashboard uses a shared password session. `PH_PASSWORD_HASH` and `PH_SESSION_SECRET` are required; the dashboard fails closed if either is unset. Login routes are `GET /login`, `POST /auth/login` with a JSON password body, and `POST /auth/logout`. Settings requests require the current `ph_session` cookie and `X-PH-Request: 1` CSRF protection.

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

API bearer tokens cannot manage dashboard settings. Set or rotate the dashboard password from your own terminal with:

```sh
python3 scripts/set-password.py
```

Initialization writes a one-time password to the ignored `data/bootstrap-password.txt` with mode 600, unless you choose the password yourself with the script. The script stores only `PH_PASSWORD_HASH` and rotates `PH_SESSION_SECRET`. Never paste passwords, session secrets, bootstrap files, or bearer tokens into Git, issues, chats, or screenshots.

API tokens are named, scoped to `summary:read` by default, optionally granted `history:read` and `raw:read`, expiring, and revocable. Store only a hash and show the secret once at creation. Existing watch upload tokens remain separate and are not API read tokens.

For private deployments, keep the default localhost bind or use an authenticated VPN/reverse proxy. Use HTTPS for any reachable host. This API exposes health history and raw recordings; treat tokens and backups as private credentials.
