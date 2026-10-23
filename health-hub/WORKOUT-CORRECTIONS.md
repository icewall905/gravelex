# Audited workout corrections

Use **Training → Workouts → Edit** to correct activity/start/duration, split a recording, or explicitly merge overlapping/adjacent recordings. A merge retains the selected keeper's activity and effort; its duration is the union of connected intervals. Gaps cannot become invented exercise time. Split children retain the parent's effort, so their total session-effort load preserves the original duration. Overlapping active recordings remain excluded from load until explicitly reconciled.

The correction history shows before/after and supports undo while none of the touched records has changed. Imported source rows and the immutable upload journal are preserved. Effective overlays, including excluded parent/duplicate records and generated split children, feed analytics and every day-review path. HR coverage and load are recomputed from corrected intervals. Load remains assigned to the wearer's local start day; every calendar date touched by old/new intervals loses its previous completeness confirmation and must be reviewed again.

New or effectively changed imported workouts also clear affected confirmations. Exact replays and raw updates masked by explicit corrections preserve them. New manually logged workouts have unique operation identities, including when two recordings start together; retrying the same create request cannot duplicate a workout.

## Storage and API contract

`workout_edits.py` owns additive numbered schema migrations. `workout_overlays` stores effective fields and monotonically increasing edit revisions. `workout_edit_audit` stores operation/request hashes, original facts, resulting facts and invalidated dates; database guards reject update/delete/replacement. Completed read paths do not create schema or acquire a writer lock.

`POST /api/workout-edits` accepts edit/split/merge/undo and requires a unique `operation_id`, `expected_revisions` and `expected_fingerprints` for all touched records. Fingerprints cover effective session facts, so a fresh import can invalidate an open form even if no manual edit occurred. The web app supplies these from its displayed snapshot; conflicts return HTTP 409 and require refresh. Retrying an identical acknowledged operation returns the original result without clearing newly confirmed days again. The caller owns the transaction; failures roll back the full operation.

`GET /api/workout-edits?id=...` returns at most 20 recent correction summaries. This follows the existing authenticated-proxy/LAN dashboard boundary; it is not a new public or scoped-upload API. Generated children are retained as excluded audit identities when undone rather than deleted.

## Limits

Upstream workouts currently derive their identity from start/type. An upstream export that changes either can create another source identity; the system cannot prove that it represents the same session. Review and explicitly merge/exclude duplicates. There is no automatic fuzzy matching. Watch/phone source-revision metadata remains F06 work. Correction history does not retrospectively change previously saved readiness snapshots: those retain the facts used at observation time.
