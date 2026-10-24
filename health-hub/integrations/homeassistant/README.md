# Home Assistant: GravelEx Health

This repository contains two separate Home Assistant packages:

- **HACS integration** (`custom_components/gravelex`): polls an existing PH hub and creates sensors. Install this if your data already lives on a PH server.
- **Supervisor app/add-on** (`homeassistant-addon`): hosts the PH web/API and receiver inside Home Assistant OS. Optional; a fresh add-on starts with empty history. It is installed through the app/add-on store, not HACS.

No Google services, MQTT broker or legacy Pebble integration is required for the HACS integration.

## Install the sensors through HACS

1. In PH, sign in to the person whose data you want. Under **More → API access**, create a token with **summary:read**. Copy it once. Use a separate token for each household member; do not use a phone upload token or PH password.
2. In Home Assistant, open **HACS → ⋮ → Custom repositories**. Add `https://github.com/icewall905/gravelex`, category **Integration**.
3. Find **GravelEx Health** and download it. The first compatible integration release is **health-v0.1.0**. If HACS still reports that `gravelex-v0.1.3` has a non-compliant structure, refresh HACS and retry adding the repository; that older Android tag predates the integration. The repository's default branch contains both the extended Android app and PH.
4. Restart Home Assistant, then open **Settings → Devices & services → Add integration → GravelEx Health**.
5. Enter the PH base URL (for example, `https://health.example.org`, without `/api/v1/summary`), the read-only token, a display name, and polling interval. Default polling is every five minutes; minimum one minute.
6. Repeat for another person with that person's token. Each entry is bound to the account ID returned by PH. Renewing a token cannot silently switch an entry to another household member.

PH account isolation does not change Home Assistant permissions: once imported, sensor visibility follows your HA instance's access rules.

For manual installation, copy only `custom_components/gravelex` from this repository into your HA configuration's `custom_components` directory, restart HA, and follow steps 4–6. Keep API tokens in HA's private configuration; do not include them in screenshots or issues.

## What becomes a sensor

Every published summary metric gets an entity, including metrics currently without data. Categories include:

| Category | Measurements |
| --- | --- |
| Heart/recovery | Latest observed HR, estimated overnight pulse/strain, estimated readiness; HRV and breathing remain unknown while unvalidated |
| Activity | Observed steps/active minutes, watch-reported distance and active/resting energy; raw movement/light intensity and watch HR zone |
| Sleep | Duration, restful duration, configured target, experimental sleep score and timing variability |
| Training | Seven-day recorded load, acute/chronic estimates, balance, baseline/known-day counts, latest workout type and duration |
| Body composition | Weight, 7/28-day weight change, fat, muscle, bone, water, fat-free/fat mass and BMI when available for that account |
| Oxygen | Latest measured SpO₂, raw device quality and stored sample count |
| Fitness | Explicitly estimated VO₂max, basal energy and intensity minutes where the hub has sufficient inputs |
| Diagnostics | Watch battery, upload age, stored record counts and missed scheduled night slots |

A missing reading is **unknown**, not zero. An outage makes entities **unavailable**. A measured zero is retained. Attributes preserve the original `observed_at`, `status`, `estimated` and `source`; partial-day totals additionally include observed/elapsed minute counts. Old scale readings retain their actual date. Collection receipt time is not a measurement time. Raw device quality/intensity units are not calibrated physiological measures.

This integration reads the latest summaries and HA starts recording those states from installation onward. It does **not** import all past minute records into HA Recorder or place raw PPI arrays in entity attributes. Full bounded minute/workout/sleep/oxygen/weight/HRV history remains available through the [PH API](../../API.md) with `history:read`; raw recordings require `raw:read`. PH retains the detailed source of truth. Historical HA statistics import is separate roadmap work.

For existing owner-only external scale/SQL/legacy HA forwarding settings, PH still restricts that bridge to its original owner. Creating another household account does not grant it someone else's scale readings.

## Token renewal and troubleshooting

Use the integration's **Reconfigure** or reauthentication prompt to replace an expired/revoked token. The account must match. Options change the polling interval. If setup says it cannot connect, check that the hub is updated to the version that returns account identity from `/api/v1/summary`, that HA can reach the URL, and that any reverse proxy allows bearer-authenticated `/api/v1/*` without a separate browser login. Redirects are deliberately rejected so tokens cannot be forwarded to another destination. HTTPS certificates are verified; use HTTP only on a trusted local connection.

## Host PH inside Home Assistant (optional)

1. Home Assistant OS/Supervisor: open **Settings → Apps / Add-ons → Store → ⋮ → Repositories**.
2. Add `https://github.com/icewall905/gravelex`, then install **GravelEx Health Hub**.
3. Set `admin_username`, an initial password of at least 12 characters, your IANA `timezone`, and the hostname/LAN IPv4 address you use in `allowed_hosts`. Configure `public_url` if using an HTTPS reverse proxy.
4. Start the add-on and open its web UI on port **8790**. Its own username/password login remains enabled. Create the account's `summary:read` token and install the HACS integration above.
5. Point GravelEx's phone exporter at this hub with a separately paired **history upload** token. Add-on port 9998 is optional for legacy uploads; modern phone/watch routes share port 8790.

Ingress is not enabled because PH currently requires a root URL. This add-on requests no Supervisor authentication privileges. Supervisor cold backups preserve the entire `/data` volume, including account/device registry, all histories, options and secrets. See the [add-on guide](../../../homeassistant-addon/DOCS.md) before migrating existing data. Keep your existing PH server if you only want sensors; do not create a second empty hub accidentally.

The Docker image is tested independently; installation, cold backup and restore through a live Supervisor still need verification on the target Home Assistant host. The add-on is marked experimental until that field verification is complete.

## Alternative REST / legacy bridges

For YAML-only polling use [`rest.yaml`](rest.yaml) with a private `summary:read` token. It reads the compact summary independently of the HACS integration.

The optional WebSocket bridge targets the external [Pebble Watch integration](https://github.com/megageek/pebble-ha-integration). [`spo2.patch`](spo2.patch) was prepared for version 0.1.2; check it against the exact upstream checkout before applying. Configure only the original owner's private `HA_WS_URL`, `HA_TOKEN`, and `HA_REPORT_SERVICE=pebble_dashboard/report_status`. MQTT discovery remains optional. These older bridges are not required for new HACS installations.

## Development checks

Use Python 3.14 and the pinned fixture dependencies:

```sh
python3 -m venv /tmp/gravelex-ha-tests
/tmp/gravelex-ha-tests/bin/pip install -r tests/homeassistant/requirements.txt
PYTHONPATH=. /tmp/gravelex-ha-tests/bin/python -m pytest -c tests/homeassistant/pytest.ini tests/homeassistant
```

These tests use real Home Assistant classes and synthetic account data; they never access your live HA instance or real health records. Source-only syntax checks do not establish Supervisor installation compatibility.

## Release compatibility

HACS validates the most recently published regular release before offering installation. `health-v*` releases package the integration from `master`; they do not contain an Android APK and are not marked as GitHub's latest release. Android updates remain on `gravelex-v*` releases. In Obtainium, use the release-tag filter `^gravelex-v` to select Android releases explicitly. Future Android releases must also include `custom_components/gravelex` and root `hacs.json`; do not publish them from a branch that predates the integration.
