# PebbleOS health data, firmware 4.41.1 → 4.47.x (checked 2026-11-19)

Source: coredevices/pebbleos `main` @ 2026-11-18 (latest tag v4.47.2). The watch reports 4.47.1.

## Why minute heart rate is sparse

Background HR is not continuous. Every *HR Monitoring* interval the HRM runs a window of at
most 60 s (`activity.c`, `ACTIVITY_DEFAULT_HR_ON_TIME_SEC`), closing early after 10
high-confidence samples or after 40 s without a valid reading. A minute record (tag 81) only
carries `hr_bpm` when samples fell inside that minute, so 1–2 minutes per interval have HR.

| HR Monitoring | Expected minutes with HR |
|---|---|
| 5 min (shortest; fw ≥ 4.39) | ~20–40 % |
| 10 min (default) | ~10–20 % |
| 30 min / 1 h | ~2–6 % (observed here: ~1 reading/hour) |

*HR During Activity* (off by default) samples at 1 Hz during detected walks/runs.
Both are set on the watch (Settings → Health) or in GravelEx's watch settings
(`hrmPreferences`: `{enabled, interval, activity_tracking}`; intervals 0=10 min, 1=30 min,
2=1 h, 3=off, 4=5 min).

## Formats

- Tag 81 minute record: version 14 is current (adds SpO₂ percent + quality); header 9 bytes,
  ≤15 samples of `sample_size` bytes. No v15 exists.
- Tag 84 activity session v3 (26 bytes): `version u16, size u16, type u16, utc_to_local i32,
  start u32, elapsed u32, steps u16, active_kcal u16, resting_kcal u16, distance_m u16`.
  Active calories precede resting; distance is metres. Types 1 Sleep, 2 RestfulSleep,
  3 Nap, 4 RestfulNap, 5 Walk, 6 Run, 7 Open.
- Tag 85: protobuf log of individual HR samples (`Payload.measurement_sets[].measurements[]`
  with BPM and HRQuality, time = `time_utc + offset_sec`), 300-byte items prefixed by a u16
  length. GravelEx discards it. It comes from the same HRM windows as the minute median, so
  decoding it adds per-second detail but not more minutes of coverage.
- Tags 82 (raw accel, debug), 83 (legacy sleep, unused), 86 (retired), 87 (analytics).

## Changes since 4.41.1 relevant to the hub

- HR: confidence-weighted minute median; BPM only at high confidence; sampling continues on a
  resting wrist; off-wrist readings invalidated.
- SpO₂: recorded during workouts, windows end on a high-confidence reading, deferred while
  walking. Preference renamed `bloodOxygenPreferences` (1 byte) → `spo2Preferences`
  (3 bytes `{enabled, interval, activity_tracking}`, commit 5507eafca). **GravelEx still
  writes the old key, so its SpO₂ toggle has no effect on 4.42+; set SpO₂ on the watch.**
- Workouts: HR-zone times in workout snapshots. Sleep: new van Hees classifier option
  (2026-11-17).
- No new datalogging tags or session types; no HRV/RR/stress export.

## Hub handling

- Naps (overlay types 3/4) are stored as `nap`/`restful_nap` and excluded from nights.
- Nights with no exported sleep session, or only a short fragment, fall back to an estimate
  from quiet minutes (`estimated_minutes`, no restful split).
