# Index 01 support in GravelEx

Investigation: 2026-10-24. Source inspection only; no ring paired or APK changed.

## Result

Feasible as a focused ring-to-Notebook/local-STT integration, but not a hidden switch. Current GravelEx cannot scan, pair or collect recordings from an Index 01. Re-enabling the whole official experimental module would also reintroduce dependencies intentionally removed by Gravel.

## Repositories checked

- GravelEx current master.
- Fork parent `david-cant-code/pebble-app-degoogled`, master `b9729fadb20b02557be272732555fadb4fe96353`. Its README still marks ring recording into Notebook as planned and ring runtime as disabled.
- Official `coredevices/mobileapp`, master `721670d282538415985474e36ab8aa65b32ae04d`. Contains working ring feature implementation, BLE/device plumbing, recording pipeline, webhooks and newer plugin features. Source availability does not establish compatibility with our build or phone.

## Why it is disabled

- `settings.gradle.kts`: `experimental` excluded; Haversine dependency globally substituted with `haversine-stubs`.
- `composeApp/.../di/ringStubsModule.kt`: `NoOpLibIndex` replaces the real runtime.
- `composeApp/.../ExperimentalDevices.kt` and related stand-ins replace feature UI/entry points. Merely enabling the module causes duplicate classes.
- `experimental/build.gradle.kts`: upstream feature depends on Firebase auth/Firestore/storage and additional account/integration machinery.
- `libindex` remains compiled for shared types, but its presence does not mean functional ring support.

## Important dependency distinction

The official BLE collection-transfer implementation uses `io.github.coredevices.haversine:haversine`. Gravel's pinned coordinate is `c11a7b6`; inspected official master uses `3df7911`. Gravel deliberately replaces its prebuilt native AAR to retain source-build/F-Droid properties.

A Google-free build is not the same as an entirely source-built build. It may be possible to use this vendor binary without Google Play services, but that must be confirmed by dependency, license, initialization and runtime-network audits. Do not promise it is offline or telemetry-free before inspecting the artifact and testing it.

The vendor confirms the client-side library is closed source in [mobileapp issue #333](https://github.com/coredevices/mobileapp/issues/333). The advertised source repository is not publicly accessible. The issue remains open; upstream's stated focus is webhook integrations. A fully independent source-built transfer implementation therefore requires protocol publication or a separate interoperability project, not only Kotlin UI work.

## Recommended scope

Create a small opt-in Index recorder feature:

`Index 01 -> BLE transfer -> durable local recording -> Notebook queue -> local/on-phone or configured self-hosted STT -> note or optional authenticated webhook`

Reuse pairing/scanning/collection code and metadata contracts from `libindex` and `experimental/.../service/RingSync.kt`. Feed the existing Notebook recording pipeline instead of importing the full cloud Index agent. Preserve recording timestamp, ring ID, transfer identity, sample rate, contiguity and gesture. Keep phone/watch recordings working independently.

The existing `IndexPairing.kt` success path can erase satellite collections. Audit and adapt this before any real pairing test with valuable recordings; do not copy it blindly. The existing Notebook watch adapter calls `CaptureIngest.ingest(wav, "wav", capturedAtMillis, fromWatch=true)` after decoding; a ring adapter should use an explicit ring source and deliberate queue policy rather than impersonating a watch.

No health sensors are implied by this voice-recorder integration. Better ring microphone recognition than watch recognition requires a real paired recording comparison.

## Implementation tasks, in order

- [ ] **I01 — Audit vendor transport.** Resolve the pinned Android AAR/POM and native libraries, license, supported ABIs, min SDK, transitive Google/Firebase dependencies, initialization and update/network behavior. Choose an explicit optional vendor-binary flavor or await a source/protocol path. Do not silently replace the stub in existing builds.
- [ ] **I02 — Minimal runtime and pairing.** Add a dedicated module/DI binding, ring scan/pair/status/settings, Android BLE permissions and locked-phone/background lifecycle. Remove only the conflicting facade for that flavor; preserve default build and Google-free checks.
- [ ] **I03 — Safe recording ingestion.** Adapt completed ring transfers to Notebook capture storage, with stable IDs, bounded audio, format checks, sample-rate conversion and gap/contiguity labels. Verify transfer acknowledgement/deletion semantics before enabling collection: never lose the only ring copy before durable phone storage; support replay/dedup and crash recovery.
- [ ] **I04 — STT and destinations.** Reuse existing local/self-hosted speech choice; configurable signed/authenticated webhook for HA or a local assistant. Avoid the command-specific prompt/vocabulary filter for general notes. No external uploads enabled by default.
- [ ] **I05 — Hardware acceptance.** Ring pairing and reconnection, locked screen, phone reboot, offline capture/backfill, duplicate transfers, interrupted ingestion, watch+ring coexistence, GrapheneOS without Play services, recording quality and battery behavior. Source/build tests cannot replace these.

## Alternative available upstream

The official app supports recording-only webhooks, allowing ring audio to reach a self-hosted endpoint without cloud transcription. This is the quickest existing integration path, but its behavior on this GrapheneOS phone without Google services and coexistence with GravelEx still need validation; no installation or pairing was attempted.

[Official Index overview](https://developer.repebble.com/index-01/) · [Webhook contract](https://developer.repebble.com/index-01/webhooks/) · [Official mobile app](https://github.com/coredevices/mobileapp) · [Gravel parent](https://github.com/david-cant-code/pebble-app-degoogled)
