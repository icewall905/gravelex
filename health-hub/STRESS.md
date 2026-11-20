# Daytime stress estimate

Garmin's all-day stress engine combines HR and beat-to-beat HRV and excludes
high activity. It uses a 0–100 scale; this does not make arbitrary pulse-based
scores equivalent to Garmin scores. Sources accessed 2026-10-26:

- https://www.garmin.com/en-CA/garmin-technology/health-science/stress-tracking/
- https://support.garmin.com/en-HK/?faq=WT9BmhjacO4ZpxbCc0EKn9

Pebble's currently unverified PPI delivery cannot establish physiological HRV.
`quiet_pulse_elevation_v1` uses canonical minute pulse plus movement instead.
It is an unvalidated physiological arousal proxy; it cannot identify emotional
stress. It does not feed readiness, HRV qualification or briefing scores.

Eligibility requires 10 consecutive minute records with zero steps and active=0,
valid pulse (35–220 bpm) for the scored minute, local time 06:00–23:00, and no
recorded sleep or workout overlap. A 15-minute cooldown follows workouts.
Unknown movement is excluded. Unrecorded sleep, static exertion, posture,
caffeine, illness and optical errors remain confounders.

Each day uses the median of earlier daily quiet pulse medians in the preceding
28 calendar days. At least three prior days, each with 30 eligible minutes, are
required. Five-minute bins need three eligible pulse observations. Score is
clipped to 0–100 from `25 + 2.5 * (bin median pulse - baseline pulse)`.
These constants are heuristics, not validated clinical or Garmin thresholds.
Daily averages weight scored bins equally and describe quiet observed periods
only. Missing bins and days remain gaps. The last score expires after one hour
or at the local date boundary, also when rendering cached data. The default
query retains at least 60 days of minute evidence for baseline warmup; longer
requested history extends the query. Earliest historical days can lack baseline.

The front-page Stress tile replaces Sleep debt and links to the Stress details
page, with today's chart, selectable daily history, formula and Garmin source.
Existing overnight strain and diagnostic stress details remain available there.

Deployment uses remote backups and rollback images; the server's flattened
Dockerfile has an explicit module list, which must include daytime_stress.py.
The repository Dockerfile copies backend/ and includes it automatically.
