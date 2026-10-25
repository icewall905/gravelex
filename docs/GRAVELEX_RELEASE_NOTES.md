GravelEx 0.1.5 exports every recorded workout session instead of only the seven known overlay types.

- Removes the known-type filter from the health data export. Sleep, deep sleep, naps, walk, run and open-workout sessions keep their existing names and behavior.
- A session the watch records with any other overlay type is now uploaded instead of being silently skipped, and is labelled "unknown" with the raw firmware overlay value retained alongside it for later identification.
- PH already accepts any session kind and stores it as a workout, so activity types such as strength reach the dashboard with their real start time and duration.
- Known sessions that predate the export cursor are still picked up by the daily correction sweep or the weekly reconciliation, so nothing recorded on the older build is lost.
- No pairing, export destination, token or firmware change is involved; the export path is otherwise unchanged.

Update GravelEx.apk over your existing installation through Obtainium. Package tdgs.gravel and the permanent signing key are unchanged; pairing, history and settings are retained. Keep Health Data Export enabled with your existing PH destination and token.
