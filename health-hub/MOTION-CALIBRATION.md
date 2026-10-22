# HRV motion calibration and eligibility

The backend now distinguishes “motion samples exist” from “motion passes a known calibration.” No production threshold ships with this project. A synthetic test threshold is not a real calibration and must never be copied into production settings.

## What is measured

The current collector sums `abs(dx)+abs(dy)+abs(dz)` between adjacent accelerometer samples. The backend divides by **N−1 transitions**, not N samples. This is a whole-capture movement summary, not an RMS acceleration, a guarantee of continuous stillness, or a validated physiological quality measure. Firmware, collector implementation and raw/processed sources may differ. Requested rate is 25 Hz; sample count versus elapsed capture time is checked only against an explicitly matched calibration.

[The Pebble accelerometer API](https://developer.rebble.io/docs/c/Foundation/Event_Service/AccelerometerService/) distinguishes raw/processed sample types and sampling rates. [The SDK guide](https://developer.repebble.com/guides/events-and-services/accelerometer/) describes processed axis units. These do not establish a universal threshold for our derived adjacent-delta aggregate. Do not convert collector units into clinical stillness claims.

## Current behavior

- Raw PPI, offsets and motion summaries stay stored; analyses can be reproduced.
- Without exactly one matching server-owned calibration, status is `motion_uncalibrated` and eligibility is false. Diagnostic reconstructed variation remains available as `diagnostic_rmssd_ms`; it is not a qualified HRV score.
- Source, firmware and collector version must match exactly. Uploaded thresholds or claims of calibration are ignored.
- Insufficient/inconsistent sample coverage, excessive aggregate motion, reported vibration or invalid policy excludes the capture from HRV recovery/stress. Raw captures lack vibration flags, so `unknown` remains visible rather than being relabeled vibration-free.
- Compatible baselines are keyed by metric, firmware/collector source and analysis algorithm. True beat RMSSD, reconstructed tachogram RMSSD and legacy provenance never silently mix. A nightly majority series is selected deterministically; excluded groups/counts remain visible.
- Current stress expires after **4 hours for manual spot checks** and **36 hours for scheduled overnight recovery proxies**. These are conservative interface freshness policies, not physiological validation claims. Values are historical after expiry; missing/future observations cannot supply a current score.

## Required field work before enabling a policy

1. Preserve firmware/collector versions and inspect the exact installed collector source. A packaged collector with a different version requires separate characterization.
2. Predefine capture conditions, repetitions, reference device and acceptance criteria. Include multiple quiet seated captures, labeled natural movement, vibration/notifications, interrupted sampling and overnight captures across different nights. Separate development/tuning captures from held-out evaluation captures.
3. Align reference RR/ECG or suitable chest-strap RR with watch timestamps; compare artifact rejection, repeated quiet recordings, missingness and HRV error. Collect independent labels for motion. Do not infer quiet labels merely because a value is low or the session was scheduled.
4. Check aggregate movement separation and sample coverage on held-out data. If quiet/moving distributions overlap, a whole-capture mean cannot establish stillness: extend the collector to emit window-level movement/timestamps (plus peak/burst and vibration evidence) before enabling recovery eligibility.
5. Record the evidence, applicable source/units/version, chosen limits, observed error and failure conditions in a private study record. Hardware changes or a different algorithm invalidate applicability until retested.
6. Only then configure `HRV_MOTION_POLICIES` in the private `.env` and recreate affected services. A policy requires `id`, `evidence`, exact `source`, `firmware`, integer `collector_version`, positive `sample_hz`, `min_coverage` in (0,1], and nonnegative `max_mean_delta`. No example numerical threshold is supplied intentionally. JSON must be a list; empty `[]` keeps qualified scores disabled.
7. Verify the More → HRV measurement quality card and fresh actual uploads. Retain raw data and the previous configuration so interpretation can be audited or rolled back.

A motion policy only qualifies the collection heuristic. Reconstructed 1 Hz RR does not become genuine beat timing, nor does passing these checks independently validate readiness, stress, breathing or a clinical measure. F03 remains open for field calibration; F16 covers reference HRV validation.
