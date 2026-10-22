# GravelEx

Personal health-export fork of Gravel. Android release identity: `tdgs.gravel`; label: **GravelEx**. Debug builds use `tdgs.gravel.debug` and a separate debug signer. Kotlin namespaces stay aligned with upstream.

## Install and update

Use the signed `GravelEx.apk` from this repository's `gravelex-v*` GitHub releases. Add `https://github.com/icewall905/pebble-app-degoogled` to Obtainium; its GitHub release source needs no secret for this public repository. Filter release titles/tags to GravelEx if older upstream releases appear, and select `GravelEx.apk`.

The new package is a full watch-management app, not a companion. It can coexist with Gravel, but only one should actively connect to the watch. Stop the old app before pairing with GravelEx. Legacy third-party PebbleKit clients that hardcode the original basalt provider or signature permissions need adaptation to this new identity. Built-in watchapp JavaScript uses the app’s own bridge. Its database and settings are separate; preserve the original installation until the new pairing and history sync work.

## Direct health export

In the watch's Health settings, open **Health data export**. Configure your own HTTPS hub URL and its history bearer token, enable export, and sync. The existing PebbleFit receiver routes records into the dashboard/history store and HA integration. Compatible destinations can implement the same authenticated JSON contract; arbitrary HA REST endpoints are not that contract.

Exports include minute HR (when present), steps, intensity, light intensity, active/resting kcal, distance metres and HR zone; sleep/deep sleep/naps and walk/run/open-workout sessions; SpO2 timestamp, percentage and unmodified quality byte. Missing readings stay absent. See [capability audit](docs/GRAVELEX_CAPABILITIES.md). Minute HR cannot yield HRV: retain the separate watch measurement path for beat intervals. No raw accelerometer, respiration or continuous beat stream is exposed by the inspected phone APIs.

## Signing secrets (maintainer)

Run from the repository, with `keytool`, `openssl`, and authenticated GitHub CLI installed:

```sh
./scripts/gravelex-signing.sh generate
gh auth login --hostname github.com --git-protocol ssh --web --scopes repo,workflow
./scripts/gravelex-signing.sh upload
./scripts/gravelex-signing.sh fingerprint
```

The script stores the permanent private key and password files under `~/.config/gravelex/signing` with restricted permissions, outside Git. Back up that entire directory securely: losing the signing key prevents compatible updates. Re-running generation retains the same key. `GRAVELEX_SIGNING_DIR`, `GRAVELEX_REPOSITORY`, and `GH_BIN` override paths/repository/CLI if needed. Never paste private keys/passwords into issues, chat, or committed files.

The public certificate digest is pinned in `docs/gravelex-signing-sha256.txt`; secret upload and CI verify it. This repository already pins the permanent GravelEx key generated on the maintainer machine. Restore that key on another machine; generating a different key will deliberately fail upload. For a genuinely new fork before its first release only, provision its own key and replace the public digest once. Never change the signing identity after users install a release.

The four repository Actions secrets are `GRAVELEX_KEYSTORE_BASE64`, `GRAVELEX_KEYSTORE_PASSWORD`, `GRAVELEX_KEY_ALIAS`, and `GRAVELEX_KEY_PASSWORD`. These sign releases; Obtainium itself uses the public release feed. CI builds unsigned first, signs in a temporary directory, verifies the pinned public certificate, and publishes only APK/checksum/public signature metadata.

## Release

Work on branch `gravelex`, retain full Git history/submodules, and run targeted parser/exporter tests plus release assembly. Version code is the Git commit count. Update `androidApp/version.properties` to the count of the release commit before tagging it `gravelex-v0.1.0` (then increment for later releases). Push the branch and tag; the GravelEx release workflow publishes the signed APK. The old upstream build matrix remains available manually. Do not use `LOCAL_RELEASE_BUILD=true` for public releases: that signs with a debug key.

## Blood oxygen troubleshooting

Version0.1.1 adds the missing `bloodOxygenPreferences` round trip. Phone Settings → Health → Blood Oxygen Monitoring controls the master switch on supported Time2 hardware. Its value remains unspecified until reported by the watch or deliberately set; saving unrelated settings does not turn it off. Sampling interval stays in watch Settings → Health.

The watch sends oxygen in version14 minute records. Zero means no measurement. SpO2 must merge independently from step-count priority because a later update to the same minute may supply oxygen without adding steps. Diagnostics `HEALTH_FORMAT` and `HEALTH_OXYGEN` show packet format and valid/missing sample counts through ADB logs.

The diagnostic Health Debug Stats refresh requests full history from the watch; the Health data export Sync button sends stored phone records to the HTTPS receiver. These are distinct steps. No supported public on-demand SpO2 SDK request was found; firmware background sampling can skip flat/off-wrist positions and attempts without accepted readings.

## Checking oxygen setup in the app

Version0.1.2 adds an SpO2 card to Health and a blood-oxygen setup/status view under Health settings. The card follows the selected day/week/month and shows observed readings with actual timestamps. Empty periods remain empty rather than zero. The setup view distinguishes the watch's reported monitoring switch, data stored on the phone, and the HTTPS export status. A switch not yet reported by the watch is shown as unknown, not assumed off.

Last successful upload time and acknowledged batch count are retained across app restarts. They describe server acknowledgment, not sensor measurement time, and reset if you change server or token. Token contents stay hidden.

## Deploy the complete hub

The matching receiver, Pebble Health PWA, analytics, optional integrations and watch-app sources are in [health-hub](health-hub/README.md). Deployment-specific URLs, wearer details and credentials come from private environment configuration. A fresh phone installation has no preset server; existing saved URLs are retained.
