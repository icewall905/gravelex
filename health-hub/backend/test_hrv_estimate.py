import json, math, random
from datetime import datetime, timedelta

import hrv
import recovery


def _ppi(seed, rr=1000, sd=35, n=180):
    rnd = random.Random(seed)
    beats = [rr + rnd.gauss(0, sd) for _ in range(n)]
    # ~1 Hz updates repeat a beat sometimes and contain an artifact.
    out = []
    for b in beats:
        out.append(round(b))
        if rnd.random() < 0.05:
            out.append(round(b))
    out[50] = 400
    return out


def test_estimate_dedupes_and_rejects_artifacts():
    est = hrv.estimate_rmssd(_ppi(1))
    assert est is not None and 30 < est < 70
    assert hrv.estimate_rmssd([1000] * 200) is None or hrv.estimate_rmssd([1000] * 200) == 0
    assert hrv.estimate_rmssd([900, 950] * 10) is None


def test_batched_nights_feed_hrv_status(monkeypatch):
    tz = recovery.TZ
    today = datetime(2026, 11, 20, 8, tzinfo=tz)
    analysed = []
    for d in range(1, 25):
        ts = (today - timedelta(days=d - 1)).replace(hour=1).timestamp()
        ppi = _ppi(d)
        payload = {"ppi": ppi, "offsets_ms": [i * 960 for i in range(len(ppi))],
                   "stream_semantics": "latest_ppi_updates", "context": "scheduled", "firmware": f"4.4{d % 3}"}
        analysed.append((ts, hrv.analyze_session(payload)))
    nights = recovery.nightly_hrv(analysed)
    assert len(nights) == 24 and all(n["estimated"] for n in nights)
    st = recovery.hrv_status(nights, today.date())
    assert st["status"] in {"balanced", "unbalanced_low", "unbalanced_high", "low"}
    assert st["last_night_rmssd_ms"] is not None
