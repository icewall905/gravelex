# Personal Pebble validation study

Status: development study, not validated physiology. No production calibration enabled by this document.

## Preserved evidence, 23 October 2026

Raw BLE packets, host receipt timestamps, native RR ticks, recorder lifecycle and raw paired watch arrays are stored privately under `reference-data/` (Git-ignored, directory0700/files0600). A SHA-256 inventory and verified archive preserve the original16files. New derived reports and labels are separate files; never overwrite raw captures. This is a local archive, not evidence of an independent off-site backup. Biometric payloads and device identifiers must not enter public Git history.

Watch source: PebbleOS4.41.1, collector152/watch1.5.2. Optical data are a roughly1Hz latest-PPI tachogram, not consecutive measured ECG beats. Existing analysis reconstructs intervals and labels its variation diagnostic-only. Its method must stay separate from chest-strap beat RMSSD.

| Capture | Outcome | Use |
| --- | --- | --- |
| quiet-seated3 | Full240s window; duplicate notifications; disconnect-stage EOF | Transport debugging only; no HRV accuracy claim |
| single-subscriber check | Full30s; no rapid duplicate notifications;26RR; disconnect-stage EOF | Connection evidence only |
| quiet-seated4 | Disconnected during recording after70s | Incomplete reference; preserve, exclude from full paired validation |
| quiet-seated5 | Full360s;370RR; no decoding errors; disconnect-stage EOF | First complete paired candidate; one gap outside the paired window and missing-RR packets require conservative segment review |

The initial paired audit found a close pulse comparison but a difference between reconstructed optical variation and conservative reference variation. Exact biometric values and per-session reports stay in private reference-data. Packet batches may contain intervals predating receipt/window boundaries; receipt times are not beat timestamps. Full analysis reports uncertainty instead of treating boundaries as exact synchronization.

## What each validation requires

| Component | Existing evidence | Missing evidence / task |
| --- | --- | --- |
| Upload reliability | Manual collector152 captures saved; completion telemetry | Real scheduled02:00/03:00/04:00 local-time execution, durable phone retry through offline/Doze/reboot |
| Pulse | Direct reported pulse and one paired quiet comparison | Repeated labeled quiet/overnight/movement comparisons; spot pulse is not validated resting heart rate |
| HRV | Raw RR and optical tachogram preserved | Aligned repeat recordings, artifact review, bias/error and repeatability; development and held-out evaluation |
| Motion | Whole-session axis-delta mean and sample count | Labeled quiet/movement/notification captures, separation on held-out runs; per-window evidence if aggregate overlaps |
| Breathing | RR-oscillation candidate algorithm | Independently counted breaths or respiration sensor, timed to same window; awake and overnight validated separately |
| Stress | Context-matched log-variation percentile prototype | Qualifying HRV/motion,14distinct prior context-matched days, contemporaneous labels, held-out evaluation and confound checks |

The breathing algorithm currently accepts only scheduled context after motion/interval gates. Do not forge scheduled context on a manual run to make a card populate. A sharp spectral peak alone does not prove it is breathing. A paced target is a requested rate, not independently observed breathing. Chest-strap-derived respiration compared against watch-derived respiration is method agreement, not independent respiratory validation.

Stress_before/stress_after0–10 labels can support a personal association study; they are subjective, not a medical reference. Do not define stressed labels from the same HRV values being tested. Quiet does not imply low psychological stress. Note posture, movement, breathing, recent exercise/caffeine, symptoms/illness and time-of-day voluntarily; unknown stays unknown. No forced stress or breath-holding challenge is needed.

## Next capture protocol (prospective)

1. Keep current recordings development-only: their results have already been viewed. Record exact watch source, collector, analysis revision, fit, condition, clock checks and interruption notes.
2. Repeat three-minute quiet seated paired runs on separate occasions. Start the strap before the watch, leave other strap subscribers closed, and verify live RR. Preserve failures rather than reconnecting across a gap.
3. For breathing, an observer counts actual breaths and marks start/end during an uninterrupted window of at least60s inside the watch capture. Alternatively use an independent respiratory sensor. Record natural breathing first; paced breathing trials must retain actual observed counts. Awake validation cannot authorize overnight claims.
4. Separately label normal arm movement and notification/vibration runs. Never tune a whole-capture threshold from a single quiet mean. If quiet/moving aggregate distributions overlap, add timestamped/windowed movement and vibration evidence to the collector first.
5. For stress, record optional0–10 ratings before/after normal daily situations, same posture/context where possible. Build14distinct qualifying prior days only after the HRV/motion gates can legitimately pass. A baseline is necessary for this algorithm, not evidence of accuracy by itself.
6. Before any new evaluation captures, freeze the algorithm, proposed operating range, error targets and coverage targets in a dated private manifest. Engineering targets are personal product goals, not clinical standards. Report every attempted capture and exclusion. Reserve later sessions/days entirely for held-out evaluation.
7. Summarize paired errors (including signed bias, absolute error, dispersion), coverage, artifact exclusions and method boundaries. One pair cannot estimate reliable limits of agreement. Compare pulse over like-for-like windows/statistics. Do not silently delete duplicated packets or interpolate rejected spans.
8. Enable a narrowly scoped motion policy only after evidence meets frozen criteria and exact source/version matching. Keep HRV/breathing/stress validation decisions separate; a motion policy does not validate them all. Retain previous configuration for rollback.

## Reproducibility tools

`reference/capture.py` preserves raw capture lifecycle. `reference/analyze_pair.py` produces private offline overlap/quality diagnostics; it never qualifies a reference or modifies production. `reference/annotate_session.py` stores independent observed labels without rewriting captures. See their `--help` and `reference/README.md`. Keep derived reports, labels and future inventories private alongside the originals.

## Primary references

- [Bluetooth SIG Heart Rate Service](https://www.bluetooth.com/wp-content/uploads/Files/Specification/HTML/HRS_v1.0/out/en/index-en.html): Heart Rate Measurement flags and RR units. RR notifications do not supply absolute beat timestamps.
- [BIDMC PPG and Respiration Dataset](https://physionet.org/content/bidmc/1.0.0/): independent breath annotations derived from impedance respiratory signals illustrate respiratory reference validation. ICU waveform results do not automatically transfer to this personal wrist tachogram.
- [Towards a Robust Estimation of Respiratory Rate from Pulse Oximeters](https://pmc.ncbi.nlm.nih.gov/articles/PMC6051482/): reference respiration, quality assessment and evaluation methodology. This is not validation of our implementation.

## First paired audit outcome

Missing-RR notifications conservatively split the reference into segments. Such packets can occur between slow heartbeats and do not themselves prove lost beats; without independent continuity evidence the audit avoids joining across them. Reference segmented RMSSD and optical reconstructed diagnostics therefore use different retained adjacency information. Their numerical difference cannot establish an unbiased paired error or justify a correction factor. Pulse agreement alone is insufficient to enable HRV/stress.

A full-reference receipt gap occurs outside the watch comparison window; report full-run and paired-window flags separately. Default2s latency uncertainty is an assumed sensitivity parameter, not a measured guarantee. Private reports retain exact outcomes and failed attempts for future continuity-aware analysis.
