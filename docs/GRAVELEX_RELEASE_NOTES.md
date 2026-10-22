GravelEx 0.1.1 fixes two missing pieces in SpO2 support:

- Sync the watch's Blood Oxygen Monitoring preference correctly and expose it in phone Health settings for Pebble Time 2 on firmware 4.41.1 or newer. An unknown setting stays unknown until reported or explicitly changed.
- Preserve valid SpO2 readings when minute records are replayed with equal/lower step counts, and prevent newer movement-only records from erasing oxygen.
- Add format and oxygen-count diagnostics for real watch packets without logging payloads or credentials.

Install GravelEx.apk over GravelEx 0.1.0, or update through Obtainium. Package and permanent signing key are unchanged. Existing settings and data are retained.

After updating, open Settings → Health → Blood Oxygen Monitoring and enable it. Set the sampling interval on the watch. Experimental background sampling may skip flat/off-wrist positions and can produce no valid result; transfer success alone does not prove an oxygen measurement. HRV continues through the existing watch measurement app.
