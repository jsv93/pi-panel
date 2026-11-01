"""Bounded, per-device telemetry. Missing measurements remain missing, never zero."""
import math
import time
from . import db

FIELDS = {'cpu_usage_pct': (0, 100), 'cpu_temp': (-40, 150),
          'ram_used_pct': (0, 100), 'ram_used_mb': (0, 1e9), 'ram_total_mb': (0, 1e9),
          'net_rx_kbps': (0, 1e10), 'net_tx_kbps': (0, 1e10),
          'disk_write_kbps': (0, 1e10), 'load_1m': (0, 1e6), 'cpu_cores': (1, 4096)}
RANGES = {'live': (300, 5), '15m': (900, 5), '1h': (3600, 15), '24h': (86400, 300)}
_last_prune = 0


def clean(values):
    if not isinstance(values, dict):
        return {}
    return {k: round(float(v), 3) for k, v in values.items() if k in FIELDS
            and type(v) in (int, float) and math.isfinite(v) and FIELDS[k][0] <= v <= FIELDS[k][1]}


def record(panel_id, values):
    import json
    global _last_prune
    now = time.time()
    values = clean(values)
    if not values:
        return
    with db.conn() as c:
        # A faulty agent cannot fill storage faster than the sampling cadence.
        row = c.execute('SELECT MAX(at) FROM performance WHERE panel_id=?', (panel_id,)).fetchone()
        if row[0] is not None and now - row[0] < 4:
            return
        c.execute('INSERT INTO performance(panel_id,at,metrics) VALUES(?,?,?)',
                  (panel_id, now, json.dumps(values)))
        if now - _last_prune >= 60:
            c.execute('DELETE FROM performance WHERE at<?', (now - 25 * 3600,))
            _last_prune = now


def history(panel_id, period):
    import json
    duration, bucket = RANGES[period]
    end = time.time()
    with db.conn() as c:
        rows = c.execute('SELECT at,metrics FROM performance WHERE panel_id=? AND at>=? AND at<=? ORDER BY at',
                         (panel_id, end-duration, end)).fetchall()
    groups = {}
    for row in rows:
        b = int(row['at'] // bucket)
        group = groups.setdefault(b, {'at': row['at'], 'values': {}})
        group['at'] = row['at']
        for k, v in clean(json.loads(row['metrics'])).items():
            group['values'].setdefault(k, []).append(v)
    samples = [{'at': g['at'], **{k: round(sum(v)/len(v), 3) for k, v in g['values'].items()}}
               for g in groups.values()]
    return {'period': period, 'start': end-duration, 'end': end,
            'sample_interval_s': 5, 'bucket_s': bucket, 'samples': samples,
            'latest': ({'at': rows[-1]['at'], **clean(json.loads(rows[-1]['metrics']))} if rows else None)}
