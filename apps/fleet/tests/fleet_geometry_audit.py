"""Fixed-floor audit; run in the fleet image, never alter production geometry."""
from collections import Counter, deque
import json
import math
from pathlib import Path
import platform
import statistics
import time

from fleet.navigation import Navigation, intersects
from fleet.worker import Worker

ROOT = Path('/app/contracts')


def service_bounds(nav, endpoint, pose):
    x, _, z = endpoint['position']
    a, b, c, d = nav._rectangle(pose)
    return min(a, x - .55), min(b, z - .58), max(c, x + .55), max(d, z + .58)


def outside(rect, bounds):
    return any((rect[0] < bounds[0], rect[1] < bounds[1], rect[2] > bounds[2], rect[3] > bounds[3]))


def audit():
    topology = json.loads((ROOT / 'fleet/v1/navigation.json').read_text())
    locations = json.loads((ROOT / 'handling/v1/facility.json').read_text())['locations']
    nav = Navigation(topology)
    worker = object.__new__(Worker)
    worker.navigation = nav
    worker.catalog = {e['id']: e for e in locations}
    issues = []
    for endpoint in locations:
        pose = worker.service_pose(endpoint)
        body = nav._rectangle(pose)
        sweep = service_bounds(nav, endpoint, pose)
        blocked = [o['id'] for o in topology['obstacles'] if intersects(body, o['bounds'])]
        # Loading intentionally reaches into its own rack/truck target. Report
        # this separately: absence of a validated fork opening is still a gap.
        x, _, z = endpoint['position']
        target = [o['id'] for o in topology['obstacles'] if endpoint['id'].startswith(o['id'] + '.') and o['bounds'][0] <= x <= o['bounds'][2] and o['bounds'][1] <= z <= o['bounds'][3]]
        foreign = [o['id'] for o in topology['obstacles'] if intersects(sweep, o['bounds']) and o['id'] not in target]
        if blocked or foreign or outside(body, nav.bounds) or outside(sweep, nav.bounds) or not nav._safe(pose) or not nav._safe(pose, True):
            issues.append({'endpoint': endpoint['id'], 'service_pose': pose, 'body_obstacles': blocked,
                           'fork_foreign_obstacles': foreign, 'target_obstacles': target,
                           'body_outside_floor': outside(body, nav.bounds), 'fork_outside_floor': outside(sweep, nav.bounds),
                           'navigation_safe': nav._safe(pose)})
    parking = topology['parking']
    parking_issues = [{'id': p['id'], 'pose': p['pose']} for p in parking if not nav._safe(tuple(p['pose']))]
    parking_conflicts = [(a['id'], b['id']) for i, a in enumerate(parking) for b in parking[i+1:]
                         if intersects(nav._rectangle(a['pose']), nav._rectangle(b['pose']))]
    names = [e['id'] for e in locations]
    choose = lambda prefix: next(n for n in names if n.startswith(prefix))
    cases = [('inbound', choose('logistics.inbound.truck01.'), choose('logistics.inbound.dock01')),
             ('shelving', choose('logistics.inbound.dock01'), choose('storage.raw.')),
             ('manufacturing', choose('storage.raw.'), choose('manufacturing.cell01.input')),
             ('outbound', choose('shipping.outbound.staging.'), choose('logistics.outbound.truck01.'))]
    timings = []
    for kind, origin, destination in cases:
        a, b = (worker.service_pose(worker.catalog[n]) for n in (origin, destination))
        samples = []
        route = None
        for trial in range(3):
            started = time.perf_counter()
            route = nav.plan(a, b)
            samples.append((time.perf_counter() - started) * 1000)
        timings.append({'kind': kind, 'origin': origin, 'destination': destination,
                        'reachable': route is not None, 'distance': None if route is None else route.distance,
                        'milliseconds': samples, 'p95_ms_nearest_rank': sorted(samples)[math.ceil(.95*len(samples))-1]})
    placement_conflicts = []
    minimum_gap = math.inf
    for index, a in enumerate(locations):
        ax, ay, az = a['position']
        first = (ax-.4, ay, az-.43, ax+.4, ay+.72, az+.43)
        for b in locations[index+1:]:
            bx, by, bz = b['position']
            second = (bx-.4, by, bz-.43, bx+.4, by+.72, bz+.43)
            gap = math.sqrt(sum(max(first[k]-second[k+3], second[k]-first[k+3], 0)**2 for k in range(3)))
            minimum_gap = min(minimum_gap, gap)
            if gap < .15-1e-8:
                placement_conflicts.append([a['id'], b['id'], gap])
    machine_load_conflicts = []
    for endpoint in locations:
        x, _, z = endpoint['position']
        for obstacle in topology['obstacles']:
            if obstacle['id'].startswith('manufacturing.cell') and intersects((x-.4,z-.43,x+.4,z+.43),obstacle['bounds']):
                machine_load_conflicts.append([endpoint['id'],obstacle['id']])
    return {'endpoints': len(locations), 'invalid_endpoints': len(issues),
            'invalid_by_owner': dict(Counter(i['endpoint'].split('.')[0] for i in issues)),
            'issues': issues, 'parking_count': len(parking), 'parking_issues': parking_issues,
            'parking_conflicts': parking_conflicts, 'planner': timings,
            'placement_conflicts': placement_conflicts, 'minimum_load_gap': minimum_gap,
            'machine_load_conflicts': machine_load_conflicts,
            'service_pose_count': len(topology.get('service_poses', {})),
            'environment': {'python': platform.python_version(), 'machine': platform.machine()},
            'limitations': ['Fork target intersections require explicit validated openings; this audit only exempts the target obstacle from foreign collisions.',
                            'Representative single-route timings are not a 16-robot/256-job scheduler benchmark.']}




def connectivity():
    """Exhaustive directed-state reachability using Navigation's actual edge test.

    Empty-floor baseline: parked robot contention is measured separately. Shelf
    levels share poses but every endpoint receives its own result.
    """
    topology = json.loads((ROOT / 'fleet/v1/navigation.json').read_text())
    endpoints = json.loads((ROOT / 'handling/v1/facility.json').read_text())['locations']
    nav = Navigation(topology)
    worker = object.__new__(Worker)
    worker.navigation = nav
    snap = lambda p: (round(p[0] / nav.cell) * nav.cell, round(p[1] / nav.cell) * nav.cell, p[2])
    parking = [tuple(p['pose']) for p in topology['parking']]
    seeds = [snap(p) for p in parking if nav._edge(p, snap(p), frozenset()) is not None]
    seeds = seeds[:1]
    goals = {e['id']: worker.service_pose(e) for e in endpoints}
    targets = {snap(p) for p in goals.values() if nav._edge(snap(p), p, frozenset()) is not None}
    targets.update(snap(p) for p in parking)
    directions = ((0, -1), (1, 0), (0, 1), (-1, 0))
    results = []
    for reverse in (False, True):
        deadline = time.perf_counter() + 10
        exhausted_budget = False
        found = set(seeds)
        queue = deque(seeds)
        remaining = targets - found
        while queue and remaining:
            if time.perf_counter() >= deadline:
                exhausted_budget = True
                break
            pose = queue.popleft()
            x, z, h = pose
            dx, dz = directions[h]
            direction = -1 if reverse else 1
            neighbors = ((x + direction * dx * nav.cell, z + direction * dz * nav.cell, h),
                         (x, z, (h + 1) % 4), (x, z, (h - 1) % 4))
            for candidate in neighbors:
                if candidate in found:
                    continue
                a, b = (candidate, pose) if reverse else (pose, candidate)
                if nav._edge(a, b, frozenset()) is not None:
                    found.add(candidate)
                    remaining.discard(candidate)
                    queue.append(candidate)
            if len(found) % 2048 == 0:
                nav._cells.cache_clear()
        invalid = []
        for name, pose in goals.items():
            connector = (pose, snap(pose)) if reverse else (snap(pose), pose)
            if snap(pose) not in found or nav._edge(*connector, frozenset()) is None:
                invalid.append(name)
        results.append({'direction': 'return_to_first_parking' if reverse else 'from_first_parking',
                        'states_visited': len(found), 'unreachable': invalid, 'budget_exhausted': exhausted_budget,
                        'unreachable_parking': [p for p in parking if snap(p) not in found]})
    print("CONNECTIVITY_REPORT " + json.dumps(results, sort_keys=True))
    return results


def alternatives():
    topology = json.loads((ROOT / 'fleet/v1/navigation.json').read_text())
    endpoints = json.loads((ROOT / 'handling/v1/facility.json').read_text())['locations']
    nav = Navigation(topology)
    original = audit()
    invalid = {i['endpoint'] for i in original['issues']}
    results = []
    for endpoint in endpoints:
        if endpoint['id'] not in invalid:
            continue
        x, _, z = endpoint['position']
        ax, _, az = endpoint['access']
        documented = (1 if ax >= x else -1, 0) if abs(ax-x) >= abs(az-z) else (0, 1 if az >= z else -1)
        candidates = []
        for dx, dz in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            if endpoint['kind'] == 'shelf' and (dx, dz) != documented:
                continue
            pose = (x + dx*1.5, z + dz*1.5, 0 if dx else 1)
            bounds = service_bounds(nav, endpoint, pose)
            target = [o['id'] for o in topology['obstacles'] if endpoint['id'].startswith(o['id'] + '.') and o['bounds'][0] <= x <= o['bounds'][2] and o['bounds'][1] <= z <= o['bounds'][3]]
            foreign = [o['id'] for o in topology['obstacles'] if intersects(bounds, o['bounds']) and o['id'] not in target]
            candidates.append({'pose': pose, 'distance': 1.5, 'documented_access_side': (dx,dz)==documented,
                               'body_and_turn_safe': nav._safe(pose) and nav._safe(pose, True),
                               'foreign_fork_obstacles': foreign, 'target_obstacles': target,
                               'fork_within_floor': not outside(bounds, nav.bounds),
                               'valid': nav._safe(pose) and nav._safe(pose, True) and not foreign and not outside(bounds, nav.bounds)})
        results.append({'endpoint': endpoint['id'], 'kind': endpoint['kind'], 'candidates': candidates,
                        'has_valid_alternative': any(c['valid'] for c in candidates)})
    return {'invalid_original': len(invalid), 'alternatives': results,
            'unserviceable': [r['endpoint'] for r in results if not r['has_valid_alternative']],
            'limitations': ['A target-obstacle exemption is not proof of a validated machine/truck fork opening.',
                            'Candidates use full loaded body and full-turn swept clearance, 1.5m bounded fork reach; no production geometry is changed.']}


if __name__ == '__main__':
    import sys
    if '--alternatives' in sys.argv:
        result = alternatives()
    elif '--connectivity' in sys.argv:
        result = connectivity()
    else:
        result = audit()
    print(json.dumps(result, indent=2))
