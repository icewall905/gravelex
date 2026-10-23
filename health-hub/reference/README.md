# Local chest-strap RR reference

This workstation tool reads the standard Bluetooth Heart Rate Measurement characteristic. It preserves every notification (including multiple RR intervals per packet), native 1/1024-second RR values, contact flags and host receipt timestamps. It never uploads data or automatically qualifies/calibrates Pebble scores.

A known HRM Pro/Pro+ may advertise the service, but **RR availability must be verified from actual notifications**. A service UUID alone is not proof of RR output. No device address is baked into source. Follow the [Bluetooth SIG Heart Rate Service specification](https://www.bluetooth.com/wp-content/uploads/Files/Specification/HTML/HRS_v1.0/out/en/index-en.html).

```sh
python3 -m venv reference/.venv
reference/.venv/bin/pip install -r reference/requirements.txt
reference/.venv/bin/python reference/capture.py --scan
mkdir -m 700 -p reference-data
reference/.venv/bin/python reference/capture.py --address YOUR_STRAP_ADDRESS \
  --label connection-check --duration 30 --output reference-data/connection-check.jsonl
```

The strap must be awake and worn with good electrode contact. This tool does not pair, trust, unpair or change adapter settings. If it cannot connect, check whether another application occupies the strap's available connection slots. Existing Bluetooth settings are preserved.

Outputs are mode 0600, exclusively created and Git-ignored under `reference-data/`. They include private biometric data and the connected device address. Keep all recordings/labels private. A disconnection stops the run rather than reconnecting and pretending continuous beats. Detected contact gaps, invalid RR values, missing RR fields, parse errors and notification gaps split diagnostic segments. Raw packets remain present for audit. Undetected packet loss is still possible; reference qualification is always false until reviewed.

## Paired validation protocol

1. First verify actual RR-bearing notifications with a short connection check. Confirm units, contact, clock and file integrity.
2. Predefine capture conditions and acceptance targets before viewing comparative errors. Start with several quiet seated paired captures, then separately labeled natural movement captures. Collect held-out repeats and separate overnight evidence; one successful recording cannot close a validation study.
3. Record the exact Pebble collector/firmware version and run the normal three-minute watch capture. Use a slightly longer reference recording so both can be trimmed to the same actual capture window after the watch warm-up. Retain host/phone/watch clock offsets and transport latency uncertainty.
4. Do not treat host Bluetooth arrival time as a beat timestamp. Intervals are oldest-first within a notification; absolute beat timing remains approximate unless a device timebase is independently aligned. Never compare reconstructed watch beats as if they were measured reference ECG beats.
5. Review artifacts/contact/packet loss, compare HR and RR distributions, then compute repeatability, paired-window RMSSD error and missingness. Do not interpolate across rejected spans. Document which data were used for threshold tuning versus held-out evaluation.
6. Follow [MOTION-CALIBRATION.md](../MOTION-CALIBRATION.md). A quiet/moving mean-delta threshold requires actual separation and reference evidence; no threshold is automatically inferred or enabled by this recorder.

Passing decoder fixtures or receiving a few RR intervals does not validate motion filtering, reconstructed HRV, sleep, stress, readiness or medical accuracy. F03/F14/F16/F30 remain field-gated as documented in the roadmap.
