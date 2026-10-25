# HRV firmware research readiness — 2026-10-25

Status: archived fallback only. User decision: target PebbleOS 4.42.0 if future independent firmware work becomes necessary; do not start reverse engineering, rebasing, building or flashing now.

Scope: Pebble Time 2 HRV/PPI investigation, not Index 01. No flashing, reboot, reset or watch change authorised or performed by this audit. Concurrent dashboard edits were left untouched.

## Available and checked

- Diagnostic source patch, pinned source/vendor revisions, vendor-hook transformer, driver verifier, log decoder and analysis tools in this directory and `../reference/`.
- Private 4.41.1 Obelix PVT builds for both normal slots: ELF, BIN, HEX, configuration, logs, exact log dictionaries and dual-slot PBZ.
- Official 4.41.1 normal rollback and recovery bundles and dictionaries, retained privately.
- Seven manifest-listed saved build/rollback files matched their SHA-256 records. Both diagnostic dual-slot and official normal rollback bundles passed archive, payload size and STM32 CRC verification again.
- Diagnostic decoder/transformer/delivery-audit tests passed during the audit; this is software verification only.
- Goodix integration sources and compiled HRV/DSP algorithm archives present in the pinned nonfree dependency. This is not possession of the proprietary algorithm's complete source code.
- Existing private watch/chest-strap recordings and study archives are retained under ignored `../reference-data/`; these are not raw sensor PPG or proof of consecutive beat timing.

## Preservation

The working firmware checkout and installed SDK were under `/tmp`, which is not durable. A private checkout archive (including Git metadata, pinned dependencies and local diagnostic modifications) and the verified SDK 0.1.11 distribution are preserved in ignored `../reference-data/firmware-research-preservation-20261025/`. The completed source archive was traversed successfully (59,794 members); SHA-256 hashes and artifact verification ledger are recorded in its private inventory. The SDK distribution includes the GCC/toolchain components required to reinstall the build and binary-analysis tools. Python build requirements and SDK installation instructions are documented in `README.md`.

Private source/vendor artifacts, SDK, ELF files and health recordings must not be added to GitHub. Local preservation is not an independently verified off-machine backup.

## What this does not establish

- Current watch hardware revision, active slot, battery state or a tested rollback procedure.
- That the 4.41.1 diagnostic image is appropriate for the currently installed 4.42.0 watch. Rebase/rebuild and preserve matching official 4.42.0 artifacts before planning an experiment on that version.
- Live stage-by-stage diagnostic logs from an installed instrumented image. The prepared firmware was not flashed.
- Raw PPG, true beat timestamps, sequence/loss metadata or access to the complete proprietary algorithm source. Result/frame IDs are not necessarily physiological beat IDs.
- That disassembly or instrumentation can recover trustworthy consecutive beats or validate HRV/respiration.

Conclusion: sufficient material for meaningful offline source/binary investigation of the existing baseline, but not “everything required” for guaranteed algorithm recovery or a safe current-watch installation. The live prerequisites in `PREFLIGHT.md` remain mandatory. The user's preference to avoid custom firmware on their only watch remains in force.
