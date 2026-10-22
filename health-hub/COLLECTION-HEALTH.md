# Collection health: what the server can and cannot establish

This view separates three questions:

1. **Did a message reach this server?** A receipt time is transport evidence, even if a batch contains no measurements. It does not establish that the watch was worn or that the phone finished transferring watch history.
2. **When was each sensor stream actually measured?** Minute HR, optical oxygen, saved HRV captures and sleep-session ends carry their own timestamps. Re-exporting old history must not make these appear newly measured.
3. **How much history is observed?** Daily minute coverage counts distinct timestamp buckets, with separate HR coverage. It is not beat coverage, proof of wear, an overnight completion guarantee, or confirmation that every workout was recorded.

## Daily coverage

Local calendar days use the configured IANA timezone. DST days may have 23 or 25 hours; today's denominator includes only elapsed minute buckets. Duplicate rows in a minute count once, null HR does not count as HR coverage, and future observations are excluded. A sampled minute is still only an observed bucket, not a continuous signal. Missing buckets remain unknown and never become confirmed rest.

## Night collection

A scheduler launch/status report is distinct from a saved measurement. Expected slots must be backed by a persisted schedule, not a hardcoded assumption. A scheduled capture can be stored yet still be excluded from qualified HRV because motion calibration or interval quality failed. A slot absent after a transfer grace period means “not received here,” not a proven watch measurement failure. Missing or incomplete scheduling evidence is shown as unknown.

## Limits and troubleshooting

The current server cannot directly inspect the phone's pending queue, battery restrictions, watch-to-phone database cursor, Bluetooth connection or the reason for a failed request it never received. Those states remain **unknown**, with practical checks. A stale sensor stream may reflect unworn hardware, skipped measurement, a delayed watch transfer or an upload gap. The overview must not select one explanation without telemetry.

- **Server receipt recent, sensor old:** check the watch sensor settings and watch-history transfer; uploading an empty batch cannot create a measurement.
- **No recent server receipt:** check GravelEx's saved server URL, export switch, connection test and token; then inspect phone network/background restrictions. This is a checklist, not an inferred diagnosis.
- **Night launch seen, no saved capture:** inspect the HRV collector quality/status and phone transfer; the launch alone is not a completed recording.
- **Capture stored, no HRV score:** inspect More → HRV measurement quality. Motion calibration and comparable-baseline requirements are separate from transport success.
- **Low coverage:** retain the gap; review training completeness explicitly rather than marking the day as rest.

F07's phone telemetry/durable retry work is needed to resolve unknown queue/connection states. F08 supplies the daily completeness review. This server-only view requires no new APK and sends no diagnostic requests to personal services.

Saved LLM briefings carry a facts-format version. Briefings written with older collection/quality rules are preserved but withheld as current guidance until regenerated. This prevents a cached assumption about night slots or upload freshness from contradicting current diagnostics.
