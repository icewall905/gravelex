GravelEx 0.1.4 fixes the watch battery export and stale health-summary path.

- Exports the connected watch's real Bluetooth battery reading and observation timestamp. It never substitutes phone battery or refreshes an old value using upload time.
- Refreshes the watch battery characteristic every five minutes while connected; invalid values stay unknown.
- Sends battery-only updates when no new health history is waiting. Multiple connected watches leave battery unknown rather than arbitrarily selecting one.
- PH resolves battery independently of historical backfills. Readings older than six hours become stale, with the dated last reading retained for diagnostics.
- Dashboard, API/HA and LLM context use the same battery source. Current activity uses canonical partial-day minute totals; the HR headline uses the latest dated observation.
- Includes the Home Assistant/HACS integration and optional PH Supervisor add-on in the release source.

Update GravelEx.apk over your existing installation through Obtainium. Package tdgs.gravel and the permanent signing key are unchanged; pairing, history and settings are retained. Keep Health Data Export enabled with your existing PH destination and token. Battery freshness requires this new app build; health-history uploads continue normally.
