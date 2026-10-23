"""Server-owned motion calibration contracts; no universal stillness threshold.

The collector sums L1 adjacent-axis deltas across N-1 transitions, not absolute
acceleration. Raw and processed streams cannot share a calibration. Policies
must be supported by reference/labeled captures before deployment.
"""
import json
import math
import os


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _uint(value, maximum, name):
    if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= maximum:
        raise ValueError(f'{name} must be an integer in range')
    return value


def validate_windows(data, globalmotion, globalsamples):
    """Validate and normalize the Watch153 callback-receipt motion contract."""
    if not isinstance(data, dict) or not isinstance(data.get('version'), int) or isinstance(data.get('version'), bool) or data.get('version') != 1 \
            or not isinstance(data.get('window_ms'), int) or isinstance(data.get('window_ms'), bool) or data.get('window_ms') != 5000 \
            or data.get('clock') != 'callback_receipt' or not isinstance(data.get('windows'), list) \
            or len(data['windows']) != 36:
        raise ValueError('motion_windows must contain exactly 36 Watch153 windows')
    gm = _uint(globalmotion, 4294967295, 'global motion')
    gs = _uint(globalsamples, 100000, 'global samples')
    windows = []
    sample_sum = transition_sum = total_sum = 0
    for i, item in enumerate(data['windows']):
        if not isinstance(item, dict):
            raise ValueError('motion window must be an object')
        start = _uint(item.get('start_ms'), 4294967295, 'window start_ms')
        samples = _uint(item.get('samples'), 65535, 'window samples')
        transitions = _uint(item.get('transitions'), 65535, 'window transitions')
        total = _uint(item.get('total_delta'), 4294967295, 'window total_delta')
        maximum = _uint(item.get('max_delta'), 4294967295, 'window max_delta')
        if start != i * 5000:
            raise ValueError('motion windows must be ordered at 5 second starts')
        if transitions > samples or (samples == 0 and transitions != 0):
            raise ValueError('motion window transitions are inconsistent with samples')
        if maximum > total or (transitions == 0 and total != 0) or (transitions and total > maximum * transitions):
            raise ValueError('motion window delta bounds are invalid')
        windows.append({'start_ms': start, 'samples': samples, 'transitions': transitions,
                        'total_delta': total, 'max_delta': maximum})
        sample_sum += samples; transition_sum += transitions; total_sum += total
    if sample_sum != gs or total_sum != gm:
        raise ValueError('motion windows do not reconcile with global motion totals')
    # Global transition accounting is exact; the first bucket may encode its
    # boundary transition as either samples or samples-1.
    if transition_sum != max(gs - 1, 0):
        raise ValueError('motion windows do not reconcile with global transitions')
    if gs == 0 and transition_sum:
        raise ValueError('zero-sample capture cannot contain transitions')
    if windows[0]['transitions'] not in (windows[0]['samples'], max(windows[0]['samples'] - 1, 0)):
        raise ValueError('first motion window transitions are inconsistent')
    return {'version': 1, 'window_ms': 5000, 'clock': 'callback_receipt', 'windows': windows}


def assess(payload):
    samples, total = payload.get('motion_samples'), payload.get('motion_total')
    source = payload.get('motion_source', 'unknown')
    firmware = payload.get('firmware', 'unknown')
    collector = payload.get('collector_version')
    offsets = payload.get('offsets_ms', [])
    duration = max(offsets) / 1000 if offsets and all(finite(x) and x >= 0 for x in offsets) else None
    out = {'available': False, 'status': 'missing', 'eligible': False,
           'samples': 0, 'normalized_mean': None, 'coverage_fraction': None,
           'source': source, 'firmware': firmware, 'collector_version': collector,
           'units': 'collector_axis_delta_per_transition',
           'vibration_status': payload.get('vibration_status', 'unknown'),
           'reason': 'Motion samples are missing or invalid'}
    if not finite(samples) or samples != int(samples) or samples < 2 or not finite(total) or total < 0:
        return out
    out.update(available=True, samples=int(samples), normalized_mean=total/(samples-1),
               status='uncalibrated', reason='No matching validated motion calibration; diagnostic values only')
    raw_windows = payload.get('motion_windows')
    has_windows = 'motion_windows' in payload
    windows = None
    if has_windows:
        try:
            windows = validate_windows(raw_windows, total, samples)
        except ValueError as error:
            out.update(status='invalid_windows', reason=str(error))
            return out
        hz = payload.get('sample_hz')
        out['windows'] = []
        for window in windows['windows']:
            transitions = window['transitions']
            mean = window['total_delta'] / transitions if transitions else 0
            coverage = window['samples'] / (5 * hz) if finite(hz) and hz > 0 else None
            out['windows'].append({**window, 'normalized_mean': mean,
                                   'nominal_coverage': coverage})
        out['max_window_mean'] = max((w['normalized_mean'] for w in out['windows']), default=0)
        out['max_window_delta'] = max((w['max_delta'] for w in out['windows']), default=0)
    elif finite(collector) and collector >= 153:
        out.update(status='missing_windows', reason='Watch153 motion windows are required')
        return out
    try:
        policies = json.loads(os.environ.get('HRV_MOTION_POLICIES', '[]'))
        if not isinstance(policies, list):
            raise ValueError()
        matching = [p for p in policies if isinstance(p, dict) and p.get('source') == source
                    and p.get('firmware') == firmware and p.get('collector_version') == collector]
        if len(matching) != 1:
            if len(matching) > 1:
                out.update(status='invalid_policy', reason='Ambiguous motion calibration configuration')
            return out
        policy = matching[0]
        maximum, hz, minimum = policy.get('max_mean_delta'), policy.get('sample_hz'), policy.get('min_coverage')
        if has_windows:
            if not isinstance(policy.get('motion_window_version'), int) or isinstance(policy.get('motion_window_version'), bool) or policy.get('motion_window_version') != 1 \
                    or not isinstance(policy.get('window_ms'), int) or isinstance(policy.get('window_ms'), bool) or policy.get('window_ms') != 5000 \
                    or not finite(policy.get('max_window_mean_delta')) or policy['max_window_mean_delta'] < 0 \
                    or not finite(policy.get('max_transition_delta')) or policy['max_transition_delta'] < 0 \
                    or not finite(policy.get('min_window_coverage')) or not 0 < policy['min_window_coverage'] <= 1:
                raise ValueError()
        # Coverage range is a collection policy, not a claim of physiology.
        if (not isinstance(policy.get('id'), str) or not policy['id'].strip()
                or not isinstance(policy.get('evidence'), str) or not policy['evidence'].strip()
                or not finite(collector) or collector != int(collector)
                or source not in ('raw_accelerometer', 'processed_accelerometer')
                or firmware in ('', 'unknown')
                or not finite(maximum) or maximum < 0 or not finite(hz) or not 1 <= hz <= 1000
                or not finite(minimum) or not 0 < minimum <= 1):
            raise ValueError()
    except (ValueError, TypeError):
        out.update(status='invalid_policy', reason='Invalid motion calibration configuration')
        return out
    out['calibration_id'] = policy['id']
    if has_windows:
        # The configured sample rate is the source of nominal callback
        # coverage; it is deliberately not inferred from callback receipts.
        for window in out['windows']:
            window['nominal_coverage'] = window['samples'] / (5 * hz)
        out['max_window_mean'] = max((w['normalized_mean'] for w in out['windows']), default=0)
        out['max_window_delta'] = max((w['max_delta'] for w in out['windows']), default=0)
        out['max_delta'] = out['max_window_delta']
        if any(w['nominal_coverage'] is None or w['nominal_coverage'] < policy['min_window_coverage'] or w['nominal_coverage'] > 1.2
               for w in out['windows']):
            out.update(status='coverage_inconsistent', reason='Motion window coverage is outside policy bounds')
            return out
        if out['max_window_mean'] > policy['max_window_mean_delta'] or out['max_window_delta'] > policy['max_transition_delta']:
            out.update(status='excessive', reason='Motion window exceeds the matched calibration threshold')
            return out
    if not duration or duration <= 0:
        out.update(status='coverage_unknown', reason='Capture duration is unavailable')
        return out
    out['coverage_fraction'] = samples/(duration*hz)
    if out['coverage_fraction'] < minimum:
        out.update(status='coverage_insufficient', reason='Too few motion samples for capture duration')
    elif out['coverage_fraction'] > 1.2:
        out.update(status='coverage_inconsistent', reason='Motion count exceeds calibrated sample-rate tolerance')
    elif out['normalized_mean'] > maximum:
        out.update(status='excessive', reason='Motion exceeds the matched calibration threshold')
    elif finite(payload.get('vibration_samples')) and payload['vibration_samples'] > 0:
        out.update(status='vibration', reason='Capture includes reported vibration samples')
    else:
        out.update(status='quiet', eligible=True, reason='Motion passes matched calibration and coverage checks')
    return out
