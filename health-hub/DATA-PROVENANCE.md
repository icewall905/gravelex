# Observation provenance and minute reconstruction

## Delivered F06 slice

New health uploads, HRV captures and collector status payloads are retained in an append-only raw ingestion journal. Minute observations additionally retain normalized HR/steps/activity, reported source, first receipt time, first report timestamp, reconciliation algorithm and original acceptance sequence. Each canonical field identifies its winning observation, and canonical changes create an audit revision in the same transaction as ingest. Exact replay does not create another observation or promote an older value. Invalid batches roll back their journal and canonical writes together.

Database migration is additive and transactional. A fresh bootstrap is serialized across threads/processes; established schemas do not take a writer lock just to read. Existing canonical minutes are seeded once as **legacy-canonical**, with unknown original receipt (`NULL`). This is a migration baseline, not reconstructed original sensor evidence. Previously overwritten observations and device details cannot be recovered.

The More collection card provides **Source evidence for the latest HR minute**. The protected dashboard endpoint `/api/provenance/minute?ts=<epoch-seconds>` returns a bounded projection of values, observation identifiers and winners. It does not return raw batch payloads or arbitrary metadata. It shares the dashboard's external authentication boundary; upload-only tokens do not gain history-read access.

## Reconciliation contract: minute-source-v1

For each timestamp and each non-null field, prefer:

1. Reported `gravelex` source (priority 30).
2. Reported `watch-history` (20).
3. Reported `phone-history` (10).
4. Other reported sources (0).
5. The migrated `legacy-canonical` baseline (-100).

Within equal priority, prefer the observation's **first accepted report timestamp**, then lexical source identity for otherwise tied sources, then the persisted acceptance sequence for same-source/same-second corrections. Content hash identifies an exact replay. Missing/null fields do not delete known values; numeric HR zero is the existing firmware missing-value sentinel, while explicit zero steps/activity remains a valid correction. Different fields may be supplied by different observations.

This is a compatibility policy, not proof of quality, clinical validity or authenticated device identity. Sources are uploader-supplied. Known-source precedence makes cross-source arrival order independent under the stated policy. Same-source timestamp ties intentionally use recorded acceptance order; reconstructing from the same journal preserves that order. Replays retain their original rank even when resent in a newer batch.

An actual correction that returns to exactly the same original payload cannot be distinguished from a replay without a producer revision. A future producer must provide a stable revision/device identity to disambiguate it; do not claim receipt time is a sensor correction version. Optional device/firmware fields supplied by uploaders remain preserved in the raw payload but are not yet verified or structured per-field identifiers.

## Safe preview and controlled application

Preview uses a read-only source and an isolated temporary SQLite copy. It prints only counts and canonical fingerprints, never health payloads. No preview mutates the original. Rebuilding currently covers **minutes only**, preserving workout records/RPE, settings, confirmations, sleep, oxygen and HRV canonical tables.

```sh
# Local source checkout:
python3 scripts/rebuild-minutes.py --database /path/to/fitness.sqlite3

# Or inside the deployed web image:
docker compose exec -T web python scripts/rebuild-minutes.py --database /data/fitness.sqlite3
```

Review the before/after fingerprint and retain a private full database backup. Only apply during a planned maintenance window (pause automatic uploads/services as appropriate); reconstruction takes a write reservation until completion. Applying requires a **new** backup path, refuses to overwrite an existing backup and uses mode 0600. The online backup includes committed WAL data and is captured before canonical changes while concurrent writes are reserved. On failure, canonical changes roll back; the backup remains available.

```sh
# This writes the named database; choose a private backup directory you own.
python3 scripts/rebuild-minutes.py --database /path/to/fitness.sqlite3 \
  --apply --backup /private/backups/before-rebuild.sqlite3
```

Do not replace production history using a preview export or a test database. Automatic ingestion migration seeds existing minutes; it does not perform a full canonical rebuild. A new higher-priority upload may deliberately change the canonical fields at its own timestamps according to the documented policy.

## Limits and remaining F06 work

- Canonical reconstruction for oxygen, sleep sessions, workouts and HRV is not implemented. Raw future uploads are journaled, but these streams keep their current canonical ingestion behavior.
- Verified device identity, structured firmware/source revisions and cross-device conflict policies are pending; unknowns must not be inferred from source labels.
- Workout manual RPE/ignored edits survive **minute reconstruction**. This is not a claim that every future workout editing/re-ingestion case is solved (F09).
- The journal begins at deployment; only legacy canonical minute snapshots are backfilled. Existing historical raw reports are not misrepresented as a complete source journal.
- Append-only safeguards protect normal application SQL, including replacement attempts. A database owner can deliberately change schema/triggers; these are not tamper-proof forensic storage.
- Journals and backups contain private health data. Retention, encryption-at-rest and migration/restore lifecycle improvements remain F28. Never publish raw production journals in GitHub.

F06 remains unchecked in the roadmap until its device/revision and other-stream acceptance criteria are met. This slice establishes a tested recovery and auditing foundation without claiming those remaining capabilities.
