# Pulse, breathing, stress and overnight delivery

## Incident evidence (23 October 2026, Europe/Copenhagen)

The last completed HRV captures saved by the hub were 21 October at 02:00, 03:00 and 04:00 local. On 22 October all three scheduled launches reported phases 1 (launch) and 2 (capture started), but no completed measurements followed. For 23 October the server received neither collector launch reports nor completed captures. Thus scheduling was evidenced on 22 October; execution on 23 October is unknown. A phone upload/status receipt is not proof that a recording finished. Historical evidence cannot establish whether the failure happened inside capture, watch-to-phone transfer, PKJS lifetime, or phone network upload.

Phone inspection confirmed GravelEx v0.1.3/code2525 and its Pebble foreground service. Old filtered logs had no useful failure detail. Do not claim a proven single root cause from this evidence.

## Delivered fixes

HRV watch app 1.5.2 / collector152 has a dedicated 180-second AppTimer as well as the clock-tick finish path. Finish is idempotent. The quiet-run watchdog force-finishes a still-running capture, emits timeout status and exits; normal completion allows a bounded 35-second transfer window. Completion status is also sent independently after capture. Cleanup cancels timers. Firmware/app termination can still prevent callbacks; this requires actual-watch qualification.

PKJS retains up to128 queued captures on phone storage. ACK11 means the phone durably queued the matching timestamp; it already lets the watch clear that pending capture without waiting for HTTP success. ACK1 follows server upload. Transient network/timeout/408/429/5xx failures now retry with bounded exponential delays (5s to5min, up to8 scheduled retries per runtime). Authentication/permanent4xx failures preserve payloads and await repair. Retry counters/timers are runtime-only: Android terminating PKJS can suspend retries until the next ready/watch message. This is not a claim of WorkManager or Doze qualification. No pending payload is deliberately dropped.

## Three monitors

`monitor_observations.py` separates observations from qualified recovery scores:

- **Overnight pulse:** median direct reported-HR summaries from comparable scheduled captures. Firmware/collector/source identities remain separate. Actual capture dates and gaps are preserved. Counter/bound/rounding integrity checks apply. The UI calls this *overnight spot pulse*: it is not validated resting heart rate and cannot enter readiness by itself. Existing stored data is visible without inventing new measurements.
- **Breathing:** every received night capture is counted. A number still requires server interval qualification, explicitly eligible calibrated motion and a reliable spectral estimate. Rejected recordings show the actual exclusion reason and latest measurement time.
- **Daytime stress:** every received manual recording/day is counted; eligible records and authoritative same-method prior baseline days remain separate. Scheduled recordings cannot appear as daytime stress/spot checks. Uploaded claims of qualification are ignored. Fourteen elapsed days or fourteen rejected recordings do not qualify a baseline.

Summary and bounded LLM facts include monitor diagnostics, timestamps and unvalidated pulse observations. They do not upgrade diagnostic observations into readiness inputs or physiological claims.

## Remaining hardware acceptance

Install the published HRV watch package through GravelEx, preserve runtime pairing, confirm nights enabled and the next advertised slots. Verify one complete three-minute capture arrives with collector152 and its original timestamp. Verify a real overnight02/03/04 cycle; deliberate offline/reconnect should preserve queued captures. Receipt counts alone cannot prove loss-free collection.

Use the paired Garmin chest strap with the local reference recorder (reference/README.md), first confirming real RR-bearing notifications. Collect aligned quiet and movement examples plus held-out repeats before choosing motion thresholds or assessing reconstructed optical HRV. No default threshold is enabled by this delivery. If the optical tachogram fails comparison, use genuine strap RR for serious HRV; software cannot reconstruct unobserved beat timing. Stress baseline remains14 qualified prior comparable manual days; breathing remains gated. These gates are not closed until measurements support them.

Independent source review approved. Full backend/reference regression suite165passed; NodeVM upload retry tests and Pebble SDK4.33.1 build passed. On-device and overnight outcomes are tracked separately from source/build success.

Dashboard shell v20 now refreshes from network when online, with best-effort cache writes and offline/server-error navigation fallback. Seven Node regression cases cover freshness, quota failure and fallback. Facts version3 invalidates saved briefings made under older monitor rules; past advertised wakeups are never labeled next.
