"""Pulse elevation during recorded quiet waking periods, including sparse HR."""
from collections import defaultdict
from datetime import datetime, timedelta
from statistics import median
import math

METHOD = 'quiet_pulse_elevation_v2'
BUCKET_SECONDS = 900
MIN_BLOCKS = 3
MIN_BASELINE_DAYS = 3
QUIET_MINUTES = 5


def _valid(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _pulse(row):
    hr = row.get('hr')
    return hr if _valid(hr) and 35 <= hr <= 220 else None


def _blocks(samples):
    bins = defaultdict(list)
    for ts, pulse in samples:
        bins[ts // BUCKET_SECONDS * BUCKET_SECONDS].append((ts, pulse))
    return bins


def _median_pulse(samples):
    return median(pulse for _, pulse in samples)


def build(minutes, sleeps, workouts, now, zone):
    rows = {int(r['ts']): r for r in minutes if _valid(r.get('ts')) and r['ts'] <= now}
    blocked = [(s['start'], s['start'] + s['seconds']) for s in sleeps]
    blocked += [(w['start'], w['start'] + w['seconds'] + 900) for w in workouts if not w.get('ignored')]
    quiet, waking_hr = defaultdict(list), defaultdict(int)
    for ts, row in sorted(rows.items()):
        hr = _pulse(row)
        local = datetime.fromtimestamp(ts, zone)
        if hr is None or not 6 <= local.hour < 23:
            continue
        day = local.date().isoformat()
        if any(ts >= start and ts - (QUIET_MINUTES - 1) * 60 < end for start, end in blocked):
            continue
        waking_hr[day] += 1
        window = [rows.get(ts - i * 60, {}) for i in range(QUIET_MINUTES)]
        if all(_valid(r.get('steps')) and r['steps'] == 0 and r.get('active') == 0 for r in window):
            quiet[day].append((ts, hr))

    blocks = {day: _blocks(samples) for day, samples in quiet.items()}
    daily_pulse = {day: median(_median_pulse(group) for group in bins.values())
                   for day, bins in blocks.items() if len(bins) >= MIN_BLOCKS}
    today = datetime.fromtimestamp(now, zone).date().isoformat()
    daily, points = [], []
    for day in sorted(set(waking_hr) | {today}):
        date = datetime.fromisoformat(day).date()
        cutoff = (date - timedelta(days=28)).isoformat()
        prior = [pulse for d, pulse in daily_pulse.items() if cutoff <= d < day]
        baseline = median(prior) if len(prior) >= MIN_BASELINE_DAYS else None
        measured = blocks.get(day, {})
        scored = []
        if baseline is not None and len(measured) >= MIN_BLOCKS:
            for bucket, samples in measured.items():
                score = round(max(0, min(100, 25 + (_median_pulse(samples) - baseline) * 2.5)))
                points.append({'ts': bucket, 'score': score, 'observed_at': samples[-1][0]})
                scored.append(score)
        daily.append({'date': day, 'score': round(sum(scored) / len(scored)) if scored else None,
                      'quiet_minutes': len(quiet.get(day, [])), 'quiet_blocks': len(measured),
                      'waking_hr_minutes': waking_hr.get(day, 0), 'baseline_days': len(prior),
                      'baseline_bpm': baseline,
                      'measured_at': quiet[day][-1][0] if scored else None})
    last = daily[-1]
    latest = points[-1] if points else None
    fresh = latest and last['score'] is not None and now - latest['observed_at'] <= 3600
    reason = ('no_waking_pulse' if not last['waking_hr_minutes'] else
              'too_few_quiet_blocks' if last['quiet_blocks'] < MIN_BLOCKS else
              'building_baseline' if last['baseline_bpm'] is None else
              'current' if fresh else 'daily_only')
    return {'method': METHOD, 'estimated': True, 'score': latest['score'] if fresh else None,
            'measured_at': latest['observed_at'] if latest else None, 'status': 'current' if fresh else 'unavailable',
            'reason': reason, 'today': last, 'required_blocks': MIN_BLOCKS, 'daily': daily, 'points': points}


def sleep_pulse(minutes, nights, now):
    """Summarize pulse recorded inside actual watch-exported sleep intervals."""
    intervals = sorted((a, b, night['night']) for night in nights
                       if night.get('source') == 'sessions'
                       for a, b in night.get('sleep_intervals', []) if b <= now)
    by_night = defaultdict(list)
    index = 0
    for row in minutes:  # fitness supplies canonical minutes ordered by timestamp
        ts = row['ts']
        while index < len(intervals) and intervals[index][1] <= ts:
            index += 1
        if index == len(intervals):
            break
        start, end, night = intervals[index]
        hr = _pulse(row)
        if start <= ts < end and hr is not None:
            by_night[night].append((ts, hr))
    result = []
    for night, samples in sorted(by_night.items()):
        bins = _blocks(samples)
        result.append({'night': night, 'samples': len(samples), 'blocks': len(bins),
                       'pulse': round(median(_median_pulse(group) for group in bins.values()), 1)
                       if len(bins) >= MIN_BLOCKS else None, 'measured_at': samples[-1][0]})
    return result
