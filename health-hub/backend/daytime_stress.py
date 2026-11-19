"""Experimental pulse elevation during observed quiet waking minutes."""
from collections import defaultdict
from datetime import datetime, timedelta
from statistics import median
import math

METHOD = 'quiet_pulse_elevation_v1'


def build(minutes, sleeps, workouts, now, zone):
    def valid(v):
        return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)

    rows = {int(r['ts']): r for r in minutes if valid(r.get('ts')) and r['ts'] <= now}
    blocked = [(s['start'], s['start'] + s['seconds']) for s in sleeps]
    blocked += [(w['start'], w['start'] + w['seconds'] + 900) for w in workouts]
    quiet = defaultdict(list)
    for ts, row in sorted(rows.items()):
        if not valid(row.get('hr')) or not 35 <= row['hr'] <= 220:
            continue
        # Require ten consecutive observed quiet minutes; unknown movement stays unknown.
        window = [rows.get(ts - i * 60, {}) for i in range(10)]
        if any(not valid(r.get('steps')) or r['steps'] != 0 or r.get('active') != 0 for r in window):
            continue
        if any(ts >= start and ts - 540 < end for start, end in blocked):
            continue
        local = datetime.fromtimestamp(ts, zone)
        if not 6 <= local.hour < 23:
            continue
        quiet[str(local.date())].append((ts, row['hr']))
    daily, points = [], []
    for day, values in sorted(quiet.items()):
        date = datetime.fromisoformat(day).date()
        prior = [median(v for _, v in samples) for d, samples in quiet.items()
                 if date - timedelta(days=28) <= datetime.fromisoformat(d).date() < date and len(samples) >= 30]
        baseline = median(prior) if len(prior) >= 3 else None
        scored = []
        # Five-minute medians damp isolated optical spikes without filling data gaps.
        bins = defaultdict(list)
        for ts, hr in values:
            bins[ts // 300 * 300].append((ts, hr))
        for bucket, samples in sorted(bins.items()):
            score = round(max(0, min(100, 25 + (median(h for _, h in samples) - baseline) * 2.5))) if baseline is not None and len(samples) >= 3 else None
            points.append({'ts': bucket, 'score': score, 'observed_at': max(t for t, _ in samples)})
            if score is not None:
                scored.append(score)
        daily.append({'date': day, 'score': round(sum(scored) / len(scored)) if scored else None,
                      'quiet_minutes': len(values), 'baseline_days': len(prior), 'baseline_bpm': baseline})
    latest = next((p for p in reversed(points) if p['score'] is not None), None)
    fresh = bool(latest and 0 <= now - latest['observed_at'] <= 3600 and datetime.fromtimestamp(latest['observed_at'], zone).date() == datetime.fromtimestamp(now, zone).date())
    return {'method': METHOD, 'estimated': True, 'score': latest['score'] if fresh else None,
            'measured_at': latest['observed_at'] if latest else None, 'status': 'current' if fresh else 'unavailable',
            'daily': daily, 'points': points}
