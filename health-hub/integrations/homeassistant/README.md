# Optional Home Assistant bridge

The hub runs independently of Home Assistant. Its WebSocket forwarding targets the public [Pebble Watch integration](https://github.com/megageek/pebble-ha-integration).

Install that integration following its README. The included `spo2.patch` adds timestamped blood-oxygen state and raw device quality to its existing status sensor implementation. Apply it to a checkout of the integration before copying `custom_components/pebble_ha_integration` into your HA configuration:

```sh
git -C /path/to/pebble-ha-integration apply --check /path/to/this/repo/health-hub/integrations/homeassistant/spo2.patch
git -C /path/to/pebble-ha-integration apply /path/to/this/repo/health-hub/integrations/homeassistant/spo2.patch
```

The patch was built against integration version0.1.2. Check it again before applying to a newer upstream version; do not force failed hunks. Restart HA after installation and add the Pebble Watch integration.

In the hub's private `.env`, configure `HA_WS_URL` with your HA WebSocket URL, `HA_TOKEN` with your own long-lived token, and `HA_REPORT_SERVICE=pebble_dashboard/report_status`. Restart the receiver. These values stay on your server, not in the APK, PWA or repository. The oxygen bridge retries stored readings after HA restarts; the sensor's measurement timestamp stays the watch timestamp. Missing oxygen remains unknown.

`MQTT_ENABLED=true` offers the existing activity discovery bridge when you supply your broker settings. It does not replace the custom integration's full oxygen/status interface.
