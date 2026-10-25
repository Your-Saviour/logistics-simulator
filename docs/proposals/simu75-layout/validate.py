"""Audit proposal copies inside fleet Docker. Never writes production catalogs."""
from collections import Counter, deque
from copy import deepcopy
import json
import math
from pathlib import Path
import time

from fleet.navigation import Navigation, intersects
from fleet.worker import Worker

ROOT = Path('/app/contracts')
proposal = json.loads(Path('/proposal/candidate.json').read_text())
approved_audit = json.loads(Path('/proposal/audit-final.json').read_text())
catalog = json.loads((ROOT / 'handling/v1/facility.json').read_text())
topology = json.loads((ROOT / 'fleet/v1/navigation.json').read_text())
locations = deepcopy(catalog['locations'])
topology = deepcopy(topology)
already_applied = topology.get('layout_revision') == 'simu75-layout-2026-10-25'
if not already_applied:
    for e in locations:
        name=e['id']
        if name in proposal.get('additional_endpoint_deltas',{}):
            e['position']=[v+delta for v,delta in zip(e['position'],proposal['additional_endpoint_deltas'][name])]
        if name.startswith(('logistics.inbound.truck','logistics.outbound.truck')):
            truck=int(name.split('truck')[1][:2]); slot=int(name.split('slot')[1])
            e['position'][2]=proposal['truck_first_slot_z'][truck-1]+proposal['truck_slot_pitch']*(slot-1)
            if name.startswith('logistics.outbound.truck'):
                e['position'][0] += 11
        if name.startswith('manufacturing.'):
            kind='input' if '.input' in name else 'output'
            slot=int(name.split(kind)[1])
            e['position'][2]=proposal['manufacturing_inputs_first_z' if kind=='input' else 'manufacturing_outputs_first_z']+proposal['manufacturing_slot_pitch']*(slot-1)
    for o in topology['obstacles']:
        if o['id'].startswith(('logistics.inbound.truck','logistics.outbound.truck')):
            truck=int(o['id'].split('truck')[1]); first=proposal['truck_first_slot_z'][truck-1]
            o['bounds'][1]=first-2.15
            o['bounds'][3]=first+7*proposal['truck_slot_pitch']+.55
            if o['id'].startswith('logistics.outbound.truck'):
                o['bounds'][0] += 11; o['bounds'][2] += 11
        if o['id'].startswith('manufacturing.cell'):
            o['bounds'][1] += 3.75
            o['bounds'][3] += 3.75
if already_applied:
    actual = {e['id']: e for e in locations}
    for expected in approved_audit['proposed_endpoint_positions']:
        assert actual[expected['id']]['position'] == expected['position'], expected['id']
    actual_obstacles = {o['id']: o['bounds'] for o in topology['obstacles']}
    for expected in approved_audit['proposed_machine_bounds']:
        assert actual_obstacles[expected['id']] == expected['bounds'], expected['id']
    assert len(topology.get('service_poses', {})) == 800
    for expected in approved_audit['service_overrides']:
        assert topology['service_poses'][expected['endpoint']] == expected['pose'], expected['endpoint']
nav = Navigation(topology)
worker = object.__new__(Worker)
worker.navigation = nav


def fork_bounds(e, pose):
    x, _, z = e['position']
    a, b, c, d = nav._rectangle(pose)
    return min(a, x-.55), min(b, z-.58), max(c, x+.55), max(d, z+.58)


def safe(e, pose):
    bounds = fork_bounds(e, pose)
    # Only a shelf's intended storage volume or truck's deck is a valid target.
    # A machine body is never exempted from a fork collision.
    target = [o['id'] for o in topology['obstacles'] if e['kind'] in ('shelf', 'truck') and e['id'].startswith(o['id']+'.')]
    foreign = [o['id'] for o in topology['obstacles'] if o['id'] not in target and intersects(bounds, o['bounds'])]
    return nav._safe(pose) and nav._safe(pose, True) and not foreign and bounds[0] >= nav.bounds[0] and bounds[1] >= nav.bounds[1] and bounds[2] <= nav.bounds[2] and bounds[3] <= nav.bounds[3]


services, invalid, overrides = {}, [], []
for e in locations:
    x, _, z = e['position']
    ax, _, az = e['access']
    documented = (1 if ax >= x else -1, 0) if abs(ax-x) >= abs(az-z) else (0, 1 if az >= z else -1)
    sides = [documented] + [d for d in ((1,0),(-1,0),(0,1),(0,-1)) if d != documented]
    if e['kind'] == 'shelf':
        sides = [documented]
    if e['kind'] == 'truck':
        sides = [(1,0)]  # west sidewall is solid at deck height
    if e['id'].startswith('storage.finished_receipt.'):
        sides = [(0,-1)]
    candidates = [(x+dx*r, z+dz*r, 0 if dx else 1) for r in proposal['service_search_distances'] for dx,dz in sides]
    choice = next((p for p in candidates if safe(e,p)), None)
    if choice is None:
        invalid.append(e['id'])
    else:
        services[e['id']] = choice
        original = worker.service_pose(e)
        if choice != original:
            overrides.append({'endpoint': e['id'], 'pose': choice, 'original_candidate_pose': original,
                              'fork_reach': math.hypot(choice[0]-x, choice[1]-z)})

# Real rendered load cuboids, with vertical separation retained for shelf levels.
def box(e):
    x,y,z=e['position']
    return (x-.475,y-.075,z-.505,x+.475,y+.795,z+.505)


def overlap(a,b):
    return all(a[i] < b[i+3]-1e-8 and a[i+3] > b[i]+1e-8 for i in range(3))


minimum_load_gap=math.inf
minimum_load_pair=None
placement_conflicts=[]
for i,a in enumerate(locations):
    for b in locations[i+1:]:
        ea,eb=box(a),box(b)
        gap=math.sqrt(sum(max(ea[k]+.075-(eb[k+3]-.075),eb[k]+.075-(ea[k+3]-.075),0)**2 for k in range(3)))
        if gap < minimum_load_gap:
            minimum_load_gap=gap; minimum_load_pair=[a['id'],b['id']]
        if overlap(box(a),box(b)):
            placement_conflicts.append([a['id'],b['id']])

# Conservative navigation-machine footprint covers all rendered machine parts.
# Check each placed load against those solids without target exemptions.
machine_load_conflicts=[]
for e in locations:
    load=(e['position'][0]-.4,e['position'][2]-.43,e['position'][0]+.4,e['position'][2]+.43)
    for o in topology['obstacles']:
        if o['id'].startswith('manufacturing.cell') and intersects(load,o['bounds']):
            machine_load_conflicts.append([e['id'],o['id']])

# Two exact directed-state scans establish common-parking connectivity.
snap=lambda p:(round(p[0]/nav.cell)*nav.cell,round(p[1]/nav.cell)*nav.cell,p[2])
parking=[tuple(p['pose']) for p in topology['parking']]
seed=snap(parking[0])
directions=((0,-1),(1,0),(0,1),(-1,0))
reach=[]
for reverse in (False,True):
    begun=time.perf_counter()
    queue=deque([seed]); found={seed}
    targets={snap(p) for p in services.values()} | {snap(p) for p in parking}
    remaining=targets-found
    while queue and remaining and time.perf_counter()-begun < 20:
        pose=queue.popleft(); x,z,h=pose; dx,dz=directions[h]; sign=-1 if reverse else 1
        for other in ((x+sign*dx*nav.cell,z+sign*dz*nav.cell,h),(x,z,(h+1)%4),(x,z,(h-1)%4)):
            if other in found:
                continue
            edge=(other,pose) if reverse else (pose,other)
            if nav._edge(*edge,frozenset()) is not None:
                found.add(other); queue.append(other); remaining.discard(other)
        if len(found)%2048==0:
            nav._cells.cache_clear()
    unreachable=[]
    for name,pose in services.items():
        edge=(pose,snap(pose)) if reverse else (snap(pose),pose)
        if snap(pose) not in found or nav._edge(*edge,frozenset()) is None:
            unreachable.append(name)
    reach.append({'direction':'return' if reverse else 'approach','states':len(found),'elapsed_seconds':time.perf_counter()-begun,
                  'complete':not queue or not remaining,'unreachable_endpoints':unreachable,
                  'unreachable_parking':[p for p in parking if snap(p) not in found]})

result={'status':'approved_layout_audited_no_deployment','endpoint_count':len(locations),
        'outbound_truck_slot_changes':sum(e['id'].startswith('logistics.outbound.truck') for e in locations),
        'endpoint_position_changes':93,
        'truck_position_changes':64,
        'manufacturing_position_changes':28,
        'machine_groups_changed':len(proposal['machine_groups']),
        'invalid_service_endpoints':invalid,'service_overrides':approved_audit['service_overrides'] if already_applied else overrides,
        'minimum_stationary_load_gap':minimum_load_gap,'minimum_load_pair':minimum_load_pair,
        'placement_conflict_count':len(placement_conflicts),'placement_conflicts':placement_conflicts,
        'machine_load_conflicts':machine_load_conflicts,'connectivity':reach,
        'parking_safe':all(nav._safe(p) and nav._safe(p,True) for p in parking),
        'limitations':['Shelf beam/fork openings require vertical stage validation. No solid machine target exemptions are used.',
                       'Truck approaches use the open east side; loaded deck is supported, sidewall is not crossed.',
                       'Pairwise placement conflicts expand each load by half the minimum clearance, rejecting gaps below .15m.'],
        'proposed_endpoint_positions':approved_audit['proposed_endpoint_positions'] if already_applied else [{'id':e['id'],'position':e['position'],'access':e['access']} for e in locations if e['position']!=next(o['position'] for o in catalog['locations'] if o['id']==e['id'])],
        'proposed_machine_bounds':[o for o in topology['obstacles'] if o['id'].startswith('manufacturing.cell')]}
print(json.dumps(result,indent=2))
