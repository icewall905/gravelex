# Portable Pebble Health handover

This directory contains the self-hosted GravelEx health stack: the PWA, SQLite receiver, analytics, timestamped SpO2, HRV/history/daily watch apps, optional HA/MQTT bridges, and optional LLM briefing. Deploy with the adjacent README. No personal records, server hostnames, credentials or signing keys are distributed.

## Goals and boundaries

Replace as much of the Garmin daily overview as available Pebble measurements support: training load and history, recovery/readiness with explicit baseline requirements, stationary HRV/stress trends, steps, sleep, heart rate, oxygen, and optional weight/composition. Preserve actual timestamps, unknown periods, confidence and device quality. Minute heart rate cannot substitute for consecutive beat intervals; HRV remains a separate watch measurement. Oxygen is experimental and sparse gaps are not continuous monitoring.

## Deployment and extension

Run scripts/init-env.sh, edit .env, then docker compose up -d --build. HTTPS and dashboard authentication are deployment responsibilities; ports default to loopback. Pair scoped upload tokens in the dashboard and enter the destination in GravelEx. Optional integrations are off until configured. Runtime public configuration exposes only PUBLIC_URL and SOURCE_URL.

Legacy watch status uploads use a paired history token at /health and retain HA forwarding. The obsolete master-token-in-query download route was removed. Watch packages contain a configured public URL but acquire credentials through runtime pairing. The Android default destination is blank for new installations; existing saved settings are retained.

## Validation, 2026-10-22

Clean Docker build and isolated startup succeeded. All seven backend tests passed inside the built image with temporary databases, covering empty history/assets, allowlisted public config, host restrictions, scoped upload/deduplication, preserved watch snapshots, and legacy scoped/master authentication with HA forwarding. JavaScript and shell syntax checks passed; independent security/portability review approved. Four watch sources were successfully built with Pebble SDK 4.33.1 during packaging.

The Android native oxygen Health card and Settings diagnostics were previously built, tested and checked on-device in release 0.1.2. Actual watch oxygen reached the phone, hub and HA. GitHub-hosted Android release CI was not verified successful; signed release APKs were built separately.

## Outstanding operational checks

A phone is not connected to ADB at the final packaging check, so Obtainium refresh to the published 0.1.2 release could not be checked again. Each new deployment should verify its own phone upload, HA credentials/forwarding if enabled, HTTPS authentication, and backup restore. Production history and infrastructure are deliberately excluded.

## Fitness roadmap follow-up

See FITNESS-ROADMAP.md for the full audit and 30 ordered improvement tickets. F01 protects minute data against sparse replays (including legacy HR-zero sentinels); F02 excludes stale/future/undated load from current readiness. Independent review approved both; the complete backend suite passes 34 tests in the dependency image. The roadmap delivery ledger records rollout status.

## HRV quality follow-up

F03 software gates and F04 stress freshness deployed: exact server-owned motion calibration matching, diagnostic-only uncalibrated recordings, comparable source/metric/algorithm recovery and briefing series, current-observation timestamp guards, and 4h/36h stress freshness. Field calibration remains pending; see MOTION-CALIBRATION.md. Independent review approved; all 58 backend tests pass. More contains the HRV measurement quality panel; shell cache v13. Raw history is retained and no default motion threshold is assumed.
