# PebbleFit SpO₂ export

This branch adds recorded blood-oxygen observations from Pebble Time 2 to Gravel without a Health Connect or Google Play Services dependency. It extends Gravel's existing firmware data-logging decoder; it does not change watch firmware.

## What it adds

- Decode percentage and raw device-quality bytes from ActivityMinuteData v14, keeping each sample's original UTC timestamp.
- Preserve existing health history with an additive Room 45 → 46 migration.
- Configure a PebbleFit server and an encrypted upload-only token under watch settings → Health → **PebbleFit oxygen export**.
- Automatically upload on health updates and app resume, with Test and Sync now controls.
- Retry failed requests, paginate history, and replay the preceding 14 days to catch delayed readings. The receiver must deduplicate repeated samples.
- Keep zero/missing percentages as unmeasured. Accept percentages 1–100 and retain the raw quality byte 0–255 without inventing its interpretation.

## Try the test build

The debug variant is named **Gravel PebbleFit**, package `com.anopticlabs.gravel.pebblefit`. It installs alongside ordinary Gravel; it is not an update signed by F-Droid. The release variant retains upstream identity and is not the deployment target for this branch yet.

Keep the original app and back up its settings. Pause/force-stop it while connecting the watch to the separate test app; do not uninstall it. Leave SpO₂ enabled in the watch's Health settings. In Gravel PebbleFit, enter the server's HTTPS base URL and a history-upload token, then Save, Test, and Sync now.

For the configured deployment, APK and token setup are available at <https://ph.tdgs.org/#d/oxygen>. The APK is at <https://ph.tdgs.org/download/gravel-spo2>. No token, private signing key, or user health history is embedded in this repository or the APK.

## Receiver contract

Send `Authorization: Bearer <history-upload-token>` to `POST /fitness/records` on the configured HTTPS server. Redirects are disabled for authenticated requests.

```json
{
  "source": "phone-oxygen",
  "ts": 1792670400,
  "oxygen": [{"ts": 1792670340, "percent": 97, "quality": 80}]
}
```

The values above are synthetic protocol examples. Timestamps use Unix seconds. Upload batches contain at most 3,000 samples; acknowledge only after durable storage and return HTTP 2xx. `GET /fitness/records` validates the upload token. Other response codes leave pending history available for retry.

## Build and validate

Use the Java and Android SDK versions documented by upstream. Clone with full Git history: version-code verification uses the commit count. Initialize the pinned native sources:

```sh
git submodule update --init --recursive
./gradlew :libpebble3:jvmTest --tests '*HealthDataParserTest*' --tests '*HealthRecordFormatsTest*'
./gradlew :pebble:testAndroidHostTest --tests coredevices.pebble.health.PebbleFitOxygenExportServiceTest
./gradlew :androidApp:assembleDebug --max-workers=4 --no-configuration-cache
```

The APK is produced under `androidApp/build/outputs/apk/debug/`. Parser/format tests, all six exporter regression tests, and the full Android assembly passed before this branch was published. Room schema 46 is checked in.

Compatible app updates require the same package identity and signing key. The existing build host has a persistent development keystore. Keep signing keys outside Git; a new machine's default debug key will not update an APK signed by another machine. Configure managed release signing before treating this as a long-term release channel.

## Boundaries

These are experimental optical spot measurements, not continuous monitoring or a diagnostic assessment. Missing samples remain unknown. SpO₂ does not contribute to readiness, stress, or training-load scores. Old samples already discarded by a previous phone decoder cannot be recovered through the ordinary watch minute-history API.

Server ingestion, HA sensor, both web dashboards and LLM-context changes are maintained separately from this phone-app repository. Device installation, pairing, and a first real watch-to-server SpO₂ sync remain to be verified on hardware.
