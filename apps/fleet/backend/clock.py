"""Authorize movement from committed departmental clocks, never wall time."""
import math


def finite(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def authorized_time(run, observations, now):
    times = []
    for name, expected in run['sources'].items():
        current = observations.get(name)
        if not isinstance(current, dict):
            return run['committed'], f'{name}: unavailable'
        if any(current.get(field) != expected[field] for field in ('run_id', 'epoch')):
            return run['committed'], f'{name}: epoch mismatch'
        if (not finite(current.get('received_at')) or not 0 <= now - current['received_at'] <= 5 or
                current.get('state') != 'running'):
            return run['committed'], f'{name}: stale or held'
        committed, granted = current.get('committed'), current.get('granted')
        if not finite(committed) or not finite(granted) or committed > granted or not isinstance(current.get('cursor'), str):
            return run['committed'], f'{name}: invalid clock'
        previous = run.get('observations', {}).get(name)
        if previous and (committed < previous['committed'] or
                         (current['cursor'] == previous['cursor'] and committed != previous['committed'])):
            return run['committed'], f'{name}: reversed or changed clock cursor'
        times.append(committed + expected['offset'])
    if not times or min(times) < run['committed']:
        return run['committed'], 'Awaiting committed source clock'
    return min(times), None
