GravelEx 0.5.1 fixes the watch clock drifting away from the phone's time and merges Gravel 0.5.0.

- Watch time stays in sync: the hourly re-sync now runs by the wall clock even while the phone is in deep sleep, the app checks the watch's clock every 15 minutes and corrects drift of 2 seconds or more, opening the app syncs when a sync is overdue, and a timezone change sends the new zone instead of occasionally the old one.
- Gravel 0.5.0: recording into the Notebook from a Pebble Index 01 ring (early beta), with Import again for a damaged sync position.
- Gravel 0.5.0: weather is off until you agree to what it sends to Core Devices' weather server; Current Location is sent as a nearby town, and place search uses a built-in town list instead of Android's geocoder.
- Gravel 0.5.0: removes the auto-verified cloud.repebble.com link claim, so installing no longer triggers a lookup of that host.
- Manual weather coordinates are kept and labelled "Manual Location"; automatic backlight sunrise/sunset times need weather on, and setting a time by hand turns them off.

Update GravelEx.apk over your existing installation through Obtainium. Package tdgs.gravel and the permanent signing key remain unchanged. Core Devices 1.18 changes are not included yet.

Validated with the Android host and JVM unit suites (libpebble3, pebble, composeApp, util, androidApp) and a debug compile. Physical phone/watch behavior has not been tested for this release because no device was attached.
