"""Bluetooth SIG Heart Rate Measurement decoder; RR units are 1/1024 second."""
import math

HEART_RATE_SERVICE='0000180d-0000-1000-8000-00805f9b34fb'
HEART_RATE_MEASUREMENT='00002a37-0000-1000-8000-00805f9b34fb'


def decode_measurement(packet):
    data=bytes(packet)
    if not data:
        raise ValueError('Empty heart rate measurement')
    flags=data[0]
    if flags & 0xe0:
        raise ValueError('Unsupported reserved flag bits')
    offset=1
    def take(length):
        nonlocal offset
        if offset+length>len(data):
            raise ValueError('Truncated heart rate measurement')
        value=int.from_bytes(data[offset:offset+length],'little')
        offset+=length
        return value
    bpm=take(2 if flags & 1 else 1)
    energy=take(2) if flags & 8 else None
    rr=[]
    if flags & 16:
        if len(data)-offset<2 or (len(data)-offset)%2:
            raise ValueError('Invalid RR interval field length')
        while offset<len(data):
            rr.append(take(2))
    elif offset!=len(data):
        raise ValueError('Unexpected trailing measurement bytes')
    return {'flags':flags,'heart_rate_bpm':bpm,'contact_supported':bool(flags&4),
            'contact_detected':bool(flags&2) if flags&4 else None,
            'energy_kj':energy,'rr_ticks':rr,'rr_ms':[v*1000/1024 for v in rr],
            'rr_order':'oldest_first','rr_unit':'1/1024 second'}


def rr_diagnostics(intervals):
    """Raw adjacent RR variation; never silently filter/interpolate artifacts."""
    if not isinstance(intervals,list) or any(isinstance(v,bool) or not isinstance(v,(int,float))
            or not math.isfinite(v) or v<=0 for v in intervals):
        raise ValueError('RR intervals must be finite positive milliseconds')
    return {'count':len(intervals),'mean_rr_ms':sum(intervals)/len(intervals) if intervals else None,
            'raw_rmssd_ms':math.sqrt(sum((b-a)**2 for a,b in zip(intervals,intervals[1:]))/(len(intervals)-1)) if len(intervals)>1 else None,
            'note':'Raw reference diagnostic; artifacts, packet loss and rhythm irregularity require review. No interpolation.'}


def segmented_diagnostics(segments):
    """Never form adjacent RR pairs across a detected transport/contact gap."""
    details=[rr_diagnostics(values) for values in segments if values]
    pairs=sum(max(0,item['count']-1) for item in details)
    squares=sum((item['raw_rmssd_ms'] or 0)**2*max(0,item['count']-1) for item in details)
    return {'segments':len(details),'count':sum(item['count'] for item in details),
            'adjacent_pairs':pairs,'raw_rmssd_ms':math.sqrt(squares/pairs) if pairs else None,
            'note':'Raw within-segment diagnostic only. Unobserved packet loss can still occur.'}
