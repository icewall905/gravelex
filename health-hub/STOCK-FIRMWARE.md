# Stock-firmware fitness estimates

Stock firmware is now the default development and daily-use path. Custom firmware remains shelved; no watch/phone installation or flashing is required for this dashboard update.

## What is measured and what is estimated

| Output | Inputs | Interpretation |
| --- | --- | --- |
| Overnight pulse | Direct filtered BPM summaries from scheduled watch captures | Dated sparse pulse observation, not proven resting HR or continuous sleep HR |
| Estimated readiness | Sleep score, overnight pulse relative to earlier nights, available confirmed training state | Custom low-confidence guidance; no HRV dependency |
| Estimated overnight strain | Overnight pulse deviation from its earlier personal baseline | Custom overnight physiological-strain proxy, not psychological stress or a live daytime measurement |
| Pulse variability detail | Adjacent delivered PPI variation, source/context separated | Delivery-dependent diagnostic trend; not validated HRV/RMSSD, never an input to readiness or strain |
| Training load | Existing HR zone load or session duration × effort | Existing separate load scales and explicit recording/rest confirmations remain |
| Breathing | Existing strict qualified interval path only | Missing when timing/signal cannot support an estimate; no guessed normal value |

The [official Pebble HRM guide](https://developer.repebble.com/guides/events-and-services/hrm/) documents filtered/raw BPM and the PPI callback. Filtered BPM can be several minutes old. Our observation timestamp is the capture/read timestamp, not proof that every reported HR event was a fresh independent sensor measurement. PPI continuity remains unverified.

Published studies support [session effort/duration and HR-based training-load methods](https://pubmed.ncbi.nlm.nih.gov/19193951/) and [short HRV recordings when valid intervals exist](https://pubmed.ncbi.nlm.nih.gov/26414314/). They do **not** validate this watch's PPI timing or our readiness/strain formulas. The parameters below are transparent engineering choices for personal tracking, not published clinical thresholds or Garmin-equivalent algorithms.

## Pulse provenance and qualification

- Use scheduled captures within the local 18:00–14:00 night window. Reject future/invalid timestamps, unknown/zero/nonfinite pulse, records shorter than 120 seconds, fewer than 60 valid HR callbacks, inconsistent counters and explicitly reported vibration.
- Those callback/duration rules establish minimal collection evidence, not sixty independent measurements or a validated quiet/resting state. Motion and vibration uncertainty remain reasons for low confidence.
- Calculate each night's median of accepted direct pulse summaries; one night contributes one baseline value regardless of how many sessions it contains.
- Keep firmware/method identities separate. Unknown firmware/collector identity cannot qualify a baseline.
- Collector 150–153 has a narrow compatibility contract **only** for `mean_reported_hr` with matching `hr_sum / hr_valid`. The filtered-BPM accumulation callback is unchanged in the packaged collector150 source (`71e3783a`), recorder152 (`3404ebcc`) and recorder153 (`c3ca055e`); collector151 exported the same checked counter/mean contract. This is a deliberate approximate pulse contract, not proof that sensor accuracy is unchanged. Individual collector versions remain recorded.
- Unknown future collector versions use their own series. No pooling is applied to HRV/PPI or motion calibration.
- Minimum baseline: three earlier distinct comparable nights, within 28 days, excluding the current night. Use all eligible prior nights in that window. The baseline is provisional until 14 nights; the model remains low confidence thereafter.

## Explicit custom formulas

Let `P` be the current night's pulse, `B` the median of earlier comparable nightly pulses, and `MAD` their median absolute deviation. Scale `S = max(3 bpm, 1.4826 × MAD)`.

- Pulse recovery component: `clip(50 − 20 × (P − B) / S, 0, 100)`.
- Overnight strain: `100 − pulse recovery component`, rounded to a whole-number index. An observation expires after 36 hours. It retains its actual observation date and is never described as current psychological stress.
- Readiness weights: sleep 50%, pulse component 30%, confirmed training 20%. Renormalise only the weights of available components. Require sleep plus at least one other component. With sleep alone, show separate **sleep-only guidance**, not overall readiness.
- Only the current night's pulse may enter today's readiness. Missing nights are never carried forward. Cached earlier-day readiness and expired strain are suppressed in the browser as well as on the server.
- Training contributes only when the existing model has its confirmed 42-day history, a fresh confirmed date and a valid chronic load. Its score remains `clip(50 + 100 × (chronic − acute) / chronic)`. Recorded workout loads remain useful before that gate; missing/unconfirmed days are never invented as rest.

Model identity is `readiness-stock-v1`; input composition and pulse provenance are part of its comparison key. Append-only history preserves this separately from `readiness-v2`/strict HRV methods. PPI changes cannot change stock readiness or strain. The old strict HRV readiness result remains available as `recovery.hrv_readiness`.

## Dashboard, watch summary and LLM context

The API exposes `stock_estimates` with pulse observations, dated strain, rejected-record counts and separate diagnostic variability. The default readiness field uses the stock model. It says **Estimated**, reports available inputs and weight coverage, and preserves nulls.

The compact watch summary includes readiness method/estimated metadata. The watch app is not reinstalled by this update. Detailed labels, source limitations and graphs are in the web dashboard.

LLM facts version 5 includes the stock readiness method, low confidence, direct pulse observations and dated strain. The prompt forbids diagnosing causes, calling overnight strain mental stress, treating sleep-only guidance as overall readiness, or using delivered PPI variation as physiological HRV. Older briefing facts are marked for refresh.

Set `RECOVERY_MODE=strict_hrv` to retain the old HRV readiness model; `stock_firmware` is the default. Neither mode bypasses physiological HRV qualification or activates a motion calibration.

## Validation and limits

Regression tests include missing/future/stale records, distinct-night baselines, source changes, unknown identities, inconsistent counters, bool/NaN/oversized values, monotonic score direction, PPI independence, history provenance, and cached-observation expiry. A real-data preview uses a private SQLite backup, never synthetic production measurements.

No new accuracy claim follows from a passing test. Future work is repeatability/field validation, direct chest-strap RR ingestion, contextual daytime measurements, collection reliability and breathing only when defensible. Your Garmin HRM Pro remains the preferred reference route for actual consecutive RR intervals without modifying the watch firmware.
