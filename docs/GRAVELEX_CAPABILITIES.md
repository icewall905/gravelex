# GravelEx (`tdgs.gravel`) watch-data capability audit

Scope: read-only inspection of the fork at `pebblefit/gravel`, branch `pebblefit-spo2`. This describes what the phone-side `LibPebble` health API and Room database can provide after the watch has synced data. It does not assert that a connected watch/firmware has populated every field. No live phone database or watch was queried for this audit.

## Capability matrix

| Dataset | What the phone can supply | Classification and limits |
|---|---|---|
| Steps / minute movement | `health_data` rows with epoch-second timestamps, per-minute steps, orientation, intensity, light intensity, active-minute flag; range query and daily/whole-range totals. | Directly stored and queriable. Step rows are minute slots, not raw accelerometer streams. `intensity` is a watch-computed scalar. There is no raw triaxial acceleration in this entity/API, so VMC (vector magnitude counts) cannot be reconstructed faithfully. |
| Calories | Resting and active calories are stored per minute as integer grams of kcal; daily/range aggregates sum these columns. Activity overlays separately store integer kcal. | Directly stored/queriable, but beware units: movement-row `*GramCalories` is divided by 1000 for kcal in app summaries; overlay calorie columns are already named kiloCalories. Older firmware versions leave these as zero. |
| Distance | Per-minute `distanceCm`; walk/run overlays may carry steps, distance cm, and active/resting kcal. | Directly stored/queriable. Firmware before the parser's 3.11 layout provides none (zero defaults). Treat as watch estimates, not route/GPS distance. |
| Minute heart rate | `heartRate` byte per minute (0 means absent), with HR zone and weight fields on newer firmware; API exposes range rows, mean over nonzero rows, most recent nonzero reading, and zone-minute counts. | Directly stored/queriable at minute resolution only. It is sparse/quantized minute HR, not continuous beat-to-beat data. A standalone HR tag is explicitly ignored because HR is embedded in step samples. |
| HRV / raw PPI / tachogram | No PPI/IBI/tachogram column in the database entity; no raw-PPI accessor or parser found in the fork's health ingestion/API path. | Not currently exposed through Gravel's phone health database/API. Firmware/watch-app capability elsewhere does not imply these values reach this ingest path. Do not calculate HRV from minute BPM. |
| SpO₂ | `spo2Percent` and `spo2Quality` on minute health rows; API `getSpo2DataAfter()` and GravelEx oxygen exporter select values 1–100 and send timestamp, percent, quality. | Directly stored/queriable when firmware sends v14+ sample layouts (comment identifies firmware 4.41.1); intermittent availability expected. Quality is retained as raw 0–255. This is an occasional reading, not continuous oximetry. |
| Sleep | Overlay rows encode Sleep, DeepSleep, Nap, DeepNap with start, duration, UTC offset. Queries expose sleep entries and daily session grouping. | Directly stored/queriable as coarse overlay intervals. The distinction is the firmware's sleep/deep-sleep classification, not polysomnography or validated sleep staging. |
| Workouts / activity sessions | Overlay types Walk, Run, OpenWorkout with time/duration; walk/run may also include steps, distance, kcal. | Directly stored/queriable as session overlays, separate from minute rows. Generic workout overlay does not include rich exercise metrics or route. |
| Respiration | No respiration field or API in the health row, overlay, parser, or health data API inspected. | Unavailable from this path; do not infer a measured respiratory rate from HR/SpO₂. |
| Battery | Live connected-device battery watcher reads a battery level and publishes connection/device state. | Current/connection-state data only; not a historical health-table dataset or time series exposed through `HealthDataApi`. |
| Stress / readiness / training load | No direct stress, readiness, or training-load measurement in the health entity. | Derived estimates only. A limited training-load estimate could use workout duration and minute HR, but minute sampling and missing HR make it coarse. Readiness/stress should not be presented as watch measurements. |

## Exact phone-side path

- `libpebble3/.../connection/LibPebble.kt` defines `HealthDataApi`: raw minute rows, aggregates, sleep/activity overlays, SpO₂ pagination, HR summaries, and debug stats.
- `libpebble3/.../database/entity/HealthDataEntity.kt` and `OverlayDataEntity` define the persisted fields. The primary table is `health_data`; overlays are `overlay_data`.
- `libpebble3/.../health/parsers/HealthDataParser.kt` parses firmware-versioned minute rows. v6/3.11 adds calories/distance, v7/4.0 HR, v12/4.1 HR weight, v13/4.3 HR zone; v14 / firmware 4.41.1 appends SpO₂ percent and quality. Samples are assigned timestamps in 60-second increments.
- `libpebble3/.../datalogging/HealthDataProcessor.kt` accepts health payloads only from the system app, persists steps and overlays, and emits `healthDataUpdated`. Tag 85 standalone HR is a no-op because the implementation expects HR embedded in step records.
- `libpebble3/.../database/dao/HealthDao.kt` supplies SQL range/aggregate queries. Housekeeping deletes health and overlay rows older than 90 days (`libpebble3/.../Housekeeping.kt`).
- `pebble/src/commonMain/.../health/PebbleFitOxygenExportService.kt` is an existing export example for SpO₂: paged query, timestamp/percent/quality, bearer auth, HTTPS-only URL, encrypted token storage. It does not establish that an export is configured or has successfully run.
- Battery is separate from health ingest: `libpebble3/.../connection/bt/ble/pebble/BatteryWatcher.kt` consumes current battery notifications.

## Safe export recommendations

1. Export the minimum useful fields: UTC epoch seconds, steps, minute HR (nullable/omit zero), HR zone, activity overlays (type/start/duration), sleep overlays (type/start/duration), and SpO₂ (percent/quality). Include source (`tdgs.gravel`), watch model/firmware if available, units, and exporter/schema version.
2. Keep minute records and interval overlays distinct; do not expand a sleep/workout interval into synthetic minute samples. Preserve original timestamps and raw firmware values where useful.
3. For calories label minute fields as gram-kcal or convert to kcal explicitly; distance is centimeters. Record missingness separately from a measured zero where the receiver schema allows it. Older firmware writes zero defaults for fields it does not provide.
4. Keep PPI/IBI as a separate optional dataset only if an upstream API later exposes actual beat intervals. Store each interval in milliseconds plus timestamp/quality/source; do not fabricate a tachogram from 60-second BPM samples. HRV metrics require sufficiently continuous, quality-screened beat intervals and should be labeled experimental until that feed is verified on-device.
5. Minimize identifiers and retention, use HTTPS and a scoped bearer token, and make sync idempotent on `(source, timestamp, type)` or a stable record key. The existing SpO₂ exporter is a useful pattern, but transport success alone does not validate sensor coverage or values.

## Interpretation boundary

This is a code-path capability audit, not a measurement-quality validation. It confirms schema, parser, API, and exporter behavior in this fork. It cannot confirm watch model support, firmware settings, sample completeness, HR accuracy, SpO₂ clinical validity, or whether a live phone has synced data. Verify coverage from real rows before enabling downstream charts or calculations.
