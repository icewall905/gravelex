# PPI delivery research: PebbleOS4.41.1

Research date:23October2026. The source investigation is followed by a software correction documented below; no physiological qualification or motion policy is enabled.

## Finding

The former backend interpretation was not established by the API: `stream_semantics=latest_ppi_updates` forced every event into a uniformly sampled1Hz tachogram. That tag is written by our bridge, not supplied as a physiological contract by the watch. Approximately1s positive arrival gaps describe batch delivery, not the spacing of every PPI value. A flattened list with multiple values per delivery cannot be assigned an evenly spaced clock just because sampling was requested with period1.

Different PPI values at equal arrival offsets are legitimate delivered records and must not be silently deduplicated. Our collector reads once synchronously in each HRV event handler. Existing captures remain raw and reproducible. Do not relabel them validated beat intervals or calculate a correction factor from counters.

## Pinned primary sources

Watch firmware reports4.41.1. The corresponding public source tag resolves to `3e8d77c21d7188cfe873e8aa6312bf703f2566e3`; the pinned Goodix integration submodule is `d8ce9fc9bcc527094554bffc00822fb24d7907c1`. Newer main-branch code is not substituted for this release.

1. [SDK HRM guide](https://developer.repebble.com/guides/events-and-services/hrm/): a requested sample period and an HRV event subscription do not establish a uniform physiological PPI clock.
2. [Goodix HRV result adapter](https://github.com/coredevices/pebbleos-nonfree/blob/d8ce9fc9bcc527094554bffc00822fb24d7907c1/gh3x2x/demo_code/demo_algo_code/goodix_algo_call/src/gh3x2x_demo_algo_call_hrv.c#L161-L175): calls the result hook on `GX_HRV_ALGO_UPDATE`, not merely `GX_HRV_ALGO_OK`; forwards four result slots, confidence and valid count. Thus the open wrapper responds to algorithm output updates rather than an app polling the latest scalar. The binary algorithm still determines what each output means.
3. [Vendor hook](https://github.com/coredevices/pebbleos-nonfree/blob/d8ce9fc9bcc527094554bffc00822fb24d7907c1/gh3x2x/demo_code/demo_algo_code/goodix_algo_application/src/gh3x2x_demo_algo_hook.c#L143-L153): passes result slots0–3, confidence slot4 and valid-count slot5 to Pebble. Its frame identifier is explicitly unused.
4. [Pebble driver](https://github.com/coredevices/PebbleOS/blob/3e8d77c21d7188cfe873e8aa6312bf703f2566e3/drivers/hrm/gh3x2x.c#L212-L247): caps count at4, forwards surviving array entries individually in array order, skips invalid/nonpositive/out-of-range entries, and maps confidence to internal quality. The driver configures the HRV input rate at100Hz. This is separate from the requested app subscription period and result-delivery cadence.
5. [HRM manager](https://github.com/coredevices/PebbleOS/blob/3e8d77c21d7188cfe873e8aa6312bf703f2566e3/fw/services/hrm/hrm_manager.c#L664-L679): posts one health event for each driver output, carrying PPI and internal quality.
6. [Health service handler](https://github.com/coredevices/PebbleOS/blob/3e8d77c21d7188cfe873e8aa6312bf703f2566e3/fw/applib/health_service.c#L757-L791): updates the app's cached PPI immediately before invoking each synchronous user callback. One peek inside each delivered callback therefore reads that event's value. Polling outside the callback can miss intermediate events; that is not how this collector reads them.
7. [Public API contract](https://github.com/coredevices/PebbleOS/blob/3e8d77c21d7188cfe873e8aa6312bf703f2566e3/fw/applib/health_service.h#L386-L400): public peek returns PPI only; public callback receives event type/context. Internal quality, result grouping, frame ID, sequence, beat timestamp and loss counters are not returned by this API. Internal raw-HRM subscriber drop counters are a different delivery path and cannot be claimed as public health-event loss accounting.

## What the recordings show

Private audit reports preserve exact results, source hashes and capture hashes. Some captures have multiple different PPI values at one arrival time. Positive delivery gaps remain close to1s while regression of arrival offset against flattened sample index changes substantially with batch size. At slower reported pulse rates, delivered-PPI sums can exceed capture duration; faster-rate captures can have sums closer to duration. Reported HR is a sampled/filtered summary and cannot independently count beats.

These observations and the source trace establish batching and invalidate the blanket1Hz interpretation. They do not prove physiological chronological ordering within a vendor result, absence of missing intervals, or that each output represents one new consecutive beat. Equal numeric intervals are also not evidence of duplicated beats. Neither deleting equal values nor selecting the value that makes totals match duration is defensible.

## Consequences for earlier interpretations

- A failed fixed-clock check is not by itself evidence that a quiet sensor recording is unusable; the model may be wrong.
- Conversely, passing that check does not establish a fixed1Hz tachogram.
- Earlier reconstructed RMSSD and breathing comparisons are exploratory outputs of an unverified clock model. The approximate counted-breath comparison is retained, not promoted to validation.
- Motion windows and frozen motion-candidate tests use accelerometer data and remain separate from PPI clock/beat validity.
- No study counter or motion-policy success establishes HRV, stress or overnight breathing validity.

## Next implementation and evidence

1. Introduce a source/algorithm-versioned `batched_ppi_unverified` interpretation. Preserve legacy analyses for audit; do not silently mix old reconstructed tachogram baselines with a new method.
2. Separate arrival-batch diagnostics from physiology. Record raw event order, arrival groups, counters and source version. Leave genuine beat RMSSD and trusted breathing/stress unavailable unless continuity/clock evidence supports them.
3. Add a firmware-side diagnostic at the vendor result boundary: frame ID, monotonic receive time, result ordinal, algorithm return/update state, valid count, array index/value, confidence, wear state and available queue diagnostics. Preserve public-health delivery versus raw-HRM queue distinctions.
4. If extending the public API, expose result identity, quality and loss/sequence evidence without substituting callback receipt time for a beat timestamp. Batch IDs should be supplied at the driver boundary, not guessed from equal arrival offsets.
5. Compare recorded vendor batches and app events with an aligned chest-strap run across lower/higher pulse rates. Test novelty, array ordering, repeat/overlap and missingness explicitly. Instrumentation does not itself validate the vendor algorithm.
6. Revisit numerical HRV/breathing analysis only after those contracts are characterized. Vendor algorithm internals remain a binary dependency; headers alone do not prove the missing semantics. No custom firmware was flashed during this research.

## Reproduce the offline audit

```sh
python3 reference/audit_ppi_delivery.py reference-data reference-data/ppi-delivery-audit-new.json
python3 -m pytest reference/test_audit_ppi_delivery.py
```

The audit does not modify recordings or production settings. Outputs are private and exclusively created; use a new filename for each report. Keep biometric summaries and raw captures out of public Git history.

## Software correction delivered

Tagged latest_ppi_updates/batched_ppi_unverified recordings now use algorithmhrv-v3-batched-ppi and methoddelivered_ppi_variation_unverified. Equal-arrival records remain intact; no uniform interpolation or physiological clock is assigned. Optional delivered-adjacent variation is a separate diagnostic and cannot become RMSSD, respiration, HRV/stress baseline or readiness. Source identity retains firmware/collector. New untagged watch uploads project to the unverified method while the raw observation journal retains the original input. Existing raw database records are not rewritten.

Delivery groups are inferred from equal callback arrival offsets, not claimed as original vendor batch IDs. UI and LLM facts explain the source block; motion diagnostics and direct overnight pulse remain independent. Legacy analysis code and explicit synthetic fixtures remain separate for reproducibility. Earlier actual watch records with a legacy latest_ppi_updatestag are reinterpreted through the corrected method on read, with a new algorithm identity; previous private reports remain archived. Source continuity instrumentation is still required before any genuine-beat HRV promotion.

## Diagnostic source package — 2026-10-23

The next investigation is prepared in [firmware-diagnostics](firmware-diagnostics/README.md): a version-pinned, default-off PebbleOS patch, a hash-verified vendor-hook transformer, an offline four-stage log parser, and an isolated driver forwarding harness. The patch preserves normal forwarding behavior and traces algorithm result identity through driver, manager and app boundaries. Result identity is not beat identity.

The patch applies cleanly and host checks pass. The CMSIS and other target dependencies were resolved, and the full Obelix PVT slot-0 diagnostic firmware now compiles, links and bundles with the official SDK 0.1.11. Its matching dictionary contains all seven diagnostic log formats. No firmware has been flashed. Before a device experiment, complete the target build, verify hardware revision, preserve the matching hashed-log dictionary and official rollback image, and review installation/recovery. Sensor accuracy and consecutive-beat provenance remain unresolved; diagnostic variability must remain excluded from readiness/stress/breathing calculations.

## Stock firmware 4.42.0 check — 2026-10-24

A collector-153 capture tagged by the watch as firmware 4.42.0 was successfully
received and compared with the prior 4.41.1 capture. Batched callback delivery
persists, including multiple distinct PPI values at the same arrival offset.
There is no demonstrated improvement in beat-continuity evidence or respiratory
accuracy from this comparison. Exact capture identifiers and delivery statistics
are saved privately in `reference-data/firmware-442-delivery-audit.json`; the raw
recording remains in the immutable ingest journal/database.

The public HRV interface still does not expose beat sequence, beat timestamp or
loss metadata. Broad release comparisons can be truncated, so the check also
compared the actual HealthService header/implementation and HRM-manager files
between release tags. Driver/plumbing changes are not physiological validation.
Upstream follow-up: [PebbleOS #2558](https://github.com/coredevices/PebbleOS/issues/2558).
