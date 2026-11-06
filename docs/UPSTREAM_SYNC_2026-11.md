# Core Devices Android sync, November 2026

Target: `coredevices/mobileapp` master `f127b2aff16fc5b7bb59f75881a62d3d62f158bd` (November 5), including tag `1.17.0.1` and the subsequent twelve commits. Gravel 0.4.2 remains the fork baseline.

The sync carries the optional preview Android watch plugin framework, declarative permissions and permission-use screens, store charts and battery information, configurable navigation, multiple language packs, notification dismissal synchronization, watch settings and temperature units, config-page messaging and external links, microphone streaming to authorized companions, Bluetooth lifecycle fixes, and the Android health/file-opening fixes.

## GravelEx adaptations

- Package `tdgs.gravel`, GravelEx branding, permanent signing identity, Notebook, direct health export, SpO2, and watch battery observations are retained.
- The existing permission table and global/per-app network and location controls remain effective alongside the new granular permissions. Plugin requests cannot bypass a GravelEx network denial. Location watches observe both permission systems.
- Database version 51 upgrades directly from GravelEx version 46. It retains the original permission table and health columns instead of following the official migration that removes the old table. `scripts/test_android_upgrade.py` executes Room's generated SQL against disposable databases and checks preservation and schema compatibility.
- Native Speex code is shared by mobile targets; JVM library tests use an unsupported-codec adapter. The existing dictation coordinator continues to own deadlines, supersession and debug captures; authorized audio streams share its supersession boundary.
- Whisper and llama.cpp remain source-built. Cactus, proprietary Ring dependencies, real Firebase/GMS, push registration, Memfault and telemetry remain excluded. Ring/Index-only changes stay outside the supported Android product. iOS is unmaintained and its sources are preserved.
- Public verified firmware downloads and release-channel checks remain in place, including for the optional automatic-update setting. Core-account OTA and cloud-account features remain unavailable in the signed-out fork. This release does not flash watch firmware.
- User-selected units are preserved during weather migration. Notebook remains available in the configurable navigation.

## Validation

The Android/JVM host suites completed 4,933 test executions with zero failures and four skipped tests. The three generated-SQL database migration checks passed. Release lint passed with three existing warnings (target API and exported providers). Adding direct dependencies for the KMP libraries referenced by the app manifest resolved lint's class visibility errors.

The minified APK was inspected across 13,450 class definitions: no Firebase, Google Play Services, or Play SDK references; the PebbleKit provider is defined and the debug firmware sideload receiver is absent from the release manifest. The packaging task rejects those Google SDK namespaces on every build and retains the existing isolation/export checks. Health Connect remains optional, and direct health export runs independently of its availability and permissions.

No phone was attached over ADB, so physical de-Googled-phone/watch Bluetooth and UI acceptance remains unverified. No watch firmware or health-hub deployment was performed.
