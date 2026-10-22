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
