# Diagnostic firmware preflight

Status: **offline preparation passed; live watch checks pending; not yet cleared to flash**.

Updated 2026-10-24. The user authorised preparation and checks, explicitly excluding flashing. No firmware transfer, update, reboot into recovery, reset or watch setting change was performed. ADB returned no connected phone; the user declined reconnecting, so no further device access was attempted.

## Completed

- Pinned PebbleOS v4.41.1 source and pinned target submodules; official SDK 0.1.11 archive verified against its published SHA-256.
- Both `obelix@pvt` slot 0 and slot 1 diagnostic builds compile, link, pass resource/memory/syscall/log-format checks and bundle successfully.
- Both use the same source patch and version (`v4.41.1-dirty`). Each slot has its own matching hashed-log dictionary with seven PPI diagnostic formats.
- Dual-slot PBZ assembled with upstream `tools/merge_pbz.py`. Each manifest targets `obelix_pvt`; slots are distinct, and firmware version/commit agree.
- ZIP integrity, firmware/resource sizes and Pebble STM32 CRCs verified. A deliberately corrupted firmware payload with a valid ZIP CRC was rejected.
- Official normal **dual-slot** 4.41.1 rollback bundle and official recovery bundle saved privately, along with slot-specific official dictionaries. Every download matched its GitHub release asset SHA-256. Downloading the recovery file does not authorise installing or replacing recovery firmware.
- Offline PPI decoder uses the exact seven reviewed formats, preserves unsigned 32-bit result IDs/ticks and signed off-wrist quality/invalid PPI, rejects malformed dictionary formats, and writes a new private file without modifying raw captures.
- Receiver/backend, reference analysis and diagnostic tool regression suite: **273 passed**. This is software validation, not watch measurement accuracy or live transport validation.
- Existing interpretation policy remains: result identity is not beat identity; no readiness, stress, breathing or conventional RMSSD is qualified from an unverified PPI stream.

Private artifacts are under the ignored `health-hub/reference-data/firmware-diagnostics-20261023/`, including both builds, the merged bundle, official rollback files, configurations, dictionaries, logs and hashes. No firmware binary/vendor sources or health captures are published to GitHub.

## Slot selection and compatibility

GravelEx derives the current slot from live watch metadata and targets its opposite. Running slot 0 requires installing slot 1; running slot 1 requires slot 0. Its updater checks board, target slot and payload CRC. The merged package permits slot selection when a valid running slot is known. It does **not** establish hardware compatibility with a disconnected watch.

For an unknown/null slot, Gravel requires exactly one manifest; it cannot choose from a dual-slot package. Recovery is therefore a separate procedure requiring fresh identity/state inspection and the appropriate single-slot file. Do not bypass the updater's safety checks or guess a slot.

The prepared target is PVT (`obelix_pvt`, protocol platform 18), not BB2 or DVT. Those revisions require different builds. `v4.41.1-dirty` correctly identifies a modified build, and the installed watch's current numeric version must be read again before proceeding. Do not assume it still runs 4.41.1.

## Recovery caveat

Pinned PebbleOS `fw/main.c` invalidates both normal firmware slots when booting PRF recovery. Recovery must not be treated as a harmless reboot that preserves the previous normal image. GravelEx may enter recovery for a numeric downgrade. Avoid any downgrade/recovery transition until its behavior, matching official normal bundle and connection path are confirmed.

The official normal rollback files are available locally and validated, but rollback has **not** been exercised on this watch. Do not replace its bootloader or recovery firmware for this experiment. A historical upstream [Time 2 report](https://github.com/coredevices/PebbleOS/issues/1411) also documents the importance of choosing the opposite slot; its older CLI commands are not the current installation procedure. Target variants are documented in the [official configuration guide](https://developer.repebble.com/pebbleos/docs/development/options/).

## Remaining live prerequisites

1. Read the live watch hardware platform/revision, normal/recovery state, firmware version and active slot through GravelEx. Confirm PVT and choose the compatible path; preserve the evidence privately.
2. Read battery/charging status and verify the watch/phone connection remains stable. These are time-sensitive and must be checked immediately before any later installation.
3. Export current watch health measurements/settings as available and confirm they reach the history store. Archive the phone configuration/export and note any data that cannot be backed up. This was not possible offline.
4. Verify how the installed GravelEx build exports watch logs. Source review confirms its LogDump service and app delegate can gather logs; that does not prove the installed app's export UI, permissions or end-to-end operation.
5. Confirm the normal rollback path and recovery controls for the actual watch; do not test them by rebooting/resetting during preflight.
6. Only after these pass, obtain explicit authorisation for the separate flashing step. The current request explicitly excludes it.

## Log processing after a separately authorised experiment

Preserve the original capture unchanged. Use the dictionary for the **installed** diagnostic slot/build, not the official dictionary or the other slot. Flash and log dictionaries contain different identifiers across builds; do not guess by whichever decoder produces output.

```sh
python3 decode_ppi_logs.py RAW_CAPTURE MATCHING_LOGHASH_DICT DECODED_PPI_LOG
python3 ../reference/parse_ppi_diagnostics.py DECODED_PPI_LOG REPORT_JSON
```

Run from `health-hub/firmware-diagnostics/`, replacing arguments with private file paths. Output files must not already exist; they are created with mode 0600. The decoder outputs only matched PPI records and reports skipped counts to stderr, so always retain raw input and decoder statistics. Missing records may reflect logging loss, filtering or transport gaps; they are not proof of dropped physiological beats.

The first hardware experiment should be a short stationary HRV run, followed promptly by log export. Compare `rid/index` across result, interval, manager and app stages; inspect wear, rejection reasons, count clamping and tick-wrap ambiguity. Logging can change timing/battery use. Calibration, beat continuity and sensor accuracy remain separate questions even when all four stages correlate.
