# How the hub computes its metrics

This document covers every number the dashboard, API and Android app show: what feeds it,
how it is calculated, and when it stays empty. All values come from a wrist sensor and are
estimates, not medical measurements. Missing data stays missing and is never filled in.
Code references are under `backend/`.

## Inputs

| Stream | Source | Stored in |
|---|---|---|
| Minute records (steps, HR, intensity, light, SpO₂) | Pebble datalog tag 81 (v14), exported by GravelEx | `minutes`, `minute_observations` |
| Activity and sleep sessions (sleep, restful sleep, nap, restful nap, walk, run, open workout) | tag 84 | `sleep_sessions`, `workouts` |
| Nightly pulse-interval (PPI) recordings | HRV watch app (`watchapps/hrv-watch`) | `hrv_sessions` |
| Watch battery | GravelEx BLE status | `watch_battery_readings` |
| Weight and body composition | optional SQL or scale API | `weights` |

A "local day" uses `PEBBLE_TZ` and handles DST. The browser's time zone is never used to
assign data to a day.

## Daily totals (`daily.py`)

The hub totals minute records into one row per local day: steps, active minutes, active
and resting kcal, distance, the number of minutes with HR, and HR min/avg/max. The dashboard
charts and `/api/v1/daily` read these rows, so long ranges (up to a year) are cheap.

**Resting HR**: the 10th percentile of HR readings between 00:00 and 06:00. It needs at
least 20 readings, which in practice means HR Monitoring set to 5 minutes. Otherwise it is
empty.

## Sleep (`recovery.py`)

1. Watch sleep sessions are assigned to a night by their **midpoint**. A night belongs to
   the morning it ends on, and sessions between 14:00 and 18:00 are not night sleep.
   Nap sessions (tag-84 types 3 and 4) are stored as `nap` or `restful_nap` and never
   count toward a night.
2. **Stillness estimate**: the firmware sometimes exports only fragments of a night. The
   hub then looks for still blocks in the minute records. Within a 30-minute window at
   least 80 % of minutes must have intensity ≤ 50. Stirrings up to 45 minutes are bridged,
   and a block must last at least 3 hours. A watch night shorter than 4 hours is replaced
   by an overlapping estimate that is at least 2 hours longer. Estimated nights are labelled
   `source: estimated_minutes`, and they have no restful-sleep split.
3. **Sleep score**: duration compared with the sleep need (8 h by default), plus regularity
   of sleep timing.

## HRV

The HRV watch app records about 3 minutes of pulse intervals each night, scheduled after
midnight. Pebble's public API delivers the **latest** interval about once per second,
whatever the heart rate. So consecutive values are not guaranteed to be consecutive beats.
Below 60 bpm some beats repeat; above 60 bpm some beats are skipped.

`hrv.estimate_rmssd()` (algorithm `hrv-v4-ppi-estimate`, metric `ppi_rmssd_estimate`):

1. Keep intervals of 300–2000 ms.
2. Drop exact repeats, which are the same beat reported twice.
3. Reject intervals that differ by more than 20 % from the median of their 7-sample
   neighbourhood. These are artifacts or missed beats.
4. Take the RMSSD of adjacent accepted pairs. At least 60 pairs are required.

Skipped beats cause a known bias: values are somewhat inflated at higher heart rates. The
estimate is consistent from night to night, so it works for personal-baseline comparisons.
It is not validated against an ECG. Manual (daytime) recordings never count.

**Nightly HRV** is the geometric mean of that night's scheduled sessions. Nights are
compared only within one series (same metric, source and algorithm), so a future change of
method starts a fresh baseline instead of mixing values.

**HRV status**, Garmin-style:

| Field | Rule |
|---|---|
| Weekly value | Mean of ln(RMSSD) over the last 7 nights. Needs ≥ 3 nights. |
| Usual range | The 28 nights before this week. Needs ≥ 14. The range is mean ± max(0.5 SD, 0.04) in ln space. |
| Status | `balanced` (in range), `unbalanced_low` / `unbalanced_high` (outside the range), `low` (more than 1.5 SD below). `baseline_building` until 14 baseline nights exist. |

## Readiness

`recovery.readiness()` combines whichever of these components are available. Each scores
0–100, and 50 means "usual":

| Component | Weight | Score |
|---|---|---|
| HRV (last night) | 0.30 | 50 + 20·z against the 28-night baseline |
| Resting HR from the HRV recording | 0.20 | 50 − 20·z |
| Sleep | 0.25 | sleep score |
| Training load | 0.25 | 50 + 100·(chronic − acute)/chronic; needs 42 confirmed days |

The score is the weighted mean of the available components. It needs at least 2
components, including HRV or sleep. While that HRV model cannot produce a score, for example
during the first weeks, the hub falls back to the stock-firmware estimate (`stock_estimates.py`:
sleep, overnight pulse and training load). `formula_version` says which model produced it.
Setting `RECOVERY_MODE=strict_hrv` disables the fallback.

## Stress

- **Daytime stress** (`daytime_stress.py`): compares heart rate during quiet, low-motion
  periods with your overnight baseline, and excludes workouts. See [STRESS.md](STRESS.md).
- **Overnight strain** (`stock_estimates.py`): scheduled physiological load from stock
  overnight pulse. It is not mental stress.

## Training load (`training.py`, `training_ledger.py`)

Heart-rate-based load per workout and per day (`load_method`, default `hr`), from HR zones (set `hr_max` in settings), with
acute (7-day) and chronic (42-day) averages. Load needs 42 consecutive days confirmed in the
dashboard, so that gaps are never read as rest days.

## Other

- **SpO₂**: spot readings from the watch with their raw quality byte, shown as a daily mean
  and range. Not continuous monitoring.
- **Watch battery**: the most recent BLE reading, withheld when older than 6 hours. Runtime
  is estimated only from at least 2 hours of real discharge.
- **Body composition**: as measured on the date of each weigh-in. Nothing is interpolated.
