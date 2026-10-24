"""Validate observed handling data; never allocate stock or infer coordinates."""
import math
from copy import deepcopy
from uuid import UUID

from simulator.handling_contracts import (
    validate_snapshot, validate_movement, validate_handoff, validate_lineage,
)

IMMUTABLE_UNIT = ('id', 'barcode', 'run_id', 'epoch', 'category', 'contents')
HANDOFF_ORDER = {state: index for index, state in enumerate(
    ('offered', 'accepted', 'departed', 'received', 'acknowledged', 'quarantined'))}


def validate_handling(source, run, handling):
    if not isinstance(handling, dict) or type(handling.get('version')) is not int or handling['version'] != 1:
        raise ValueError('Handling projection version 1 required')
    if type(handling.get('catalog_version')) is not int or handling['catalog_version'] != 1:
        raise ValueError('Handling catalog version 1 required')
    for key in ('units', 'movements', 'handoffs', 'lineage'):
        if not isinstance(handling.get(key), list):
            raise ValueError('Complete handling arrays required: ' + key)
    if not isinstance(handling.get('quarantine', []), list):
        raise ValueError('Handling quarantine must be an array')
    scope = run['id'], run['epoch']
    # Unknown endpoint IDs remain data. Only the fixed catalog can supply their
    # coordinates, ownership and capacity; known endpoints retain strict checks.
    validate_snapshot(handling['units'], *scope, allow_unmapped=True)
    units = {unit['id']: unit for unit in handling['units']}
    if any(unit['owner'] != source for unit in units.values()):
        raise ValueError('A source can report only its own unit records')
    movement_ids, sequences, latest = set(), set(), {}
    for move in handling['movements']:
        validate_movement(move, *scope, allow_unmapped=True)
        unit = units.get(move['unit_id'])
        if not unit or move['barcode'] != unit['barcode']:
            raise ValueError('Movement must reference a retained unit manifest')
        key = move['unit_id'], move['sequence']
        if move['id'] in movement_ids or key in sequences:
            raise ValueError('Duplicate movement identity or unit sequence')
        if move['sequence'] > unit['last_sequence'] or move['custody_generation'] > unit['custody_generation']:
            raise ValueError('Movement exceeds recorded unit counters')
        if move['simulation_time'] > run['granted']:
            raise ValueError('Movement exceeds its source grant')
        movement_ids.add(move['id']); sequences.add(key)
        latest[move['unit_id']] = max(latest.get(move['unit_id'], 0), move['sequence'])
    if any(latest.get(unit['id'], 0) != unit['last_sequence'] for unit in units.values()):
        raise ValueError('Snapshot omitted the latest durable unit movement')
    handoff_ids = set()
    for handoff in handling['handoffs']:
        validate_handoff(handoff, *scope, allow_unmapped=True)
        if source not in (handoff['source'], handoff['destination_owner']) or handoff['id'] in handoff_ids:
            raise ValueError('Handoff witness or identity mismatch')
        handoff_ids.add(handoff['id'])
        unit = units.get(handoff['unit']['id'])
        if unit and any(unit[key] != handoff['unit'][key] for key in IMMUTABLE_UNIT):
            raise ValueError('Handoff changed retained immutable contents')
    lineage_ids, batches = set(), set()
    for lineage in handling['lineage']:
        if source != 'manufacturing':
            raise ValueError('Manufacturing owns production lineage')
        validate_lineage(lineage, handling['units'], *scope, allow_unmapped=True)
        if lineage['id'] in lineage_ids or lineage['batch_id'] in batches:
            raise ValueError('Duplicate production lineage')
        lineage_ids.add(lineage['id']); batches.add(lineage['batch_id'])
    quarantine_ids = set()
    for case in handling.get('quarantine', []):
        if not isinstance(case, dict):
            raise ValueError('Quarantine record object required')
        try:
            UUID(case['id']); UUID(case['event_id'])
        except (KeyError, TypeError, ValueError, AttributeError) as error:
            raise ValueError('Quarantine identities must be UUIDs') from error
        if case['id'] in quarantine_ids or (case.get('run_id'), case.get('epoch')) != scope:
            raise ValueError('Quarantine identity or observing scope mismatch')
        if case.get('phase') not in ('ingest', 'apply') or not isinstance(case.get('endpoint'), str) or not isinstance(case.get('reason'), str) or not case['reason']:
            raise ValueError('Quarantine endpoint, phase and reason required')
        moment = case.get('simulation_time')
        if isinstance(moment, bool) or not isinstance(moment, (int, float)) or not math.isfinite(moment) or moment < 0 or not isinstance(case.get('envelope'), dict):
            raise ValueError('Original quarantine envelope and observation time required')
        quarantine_ids.add(case['id'])
    return handling


def retain_handling(previous, current):
    """Run under the projection transaction lock before snapshot/cursor updates."""
    old = (previous or {}).get('handling')
    if old is None:
        return
    new = current.get('handling')
    if new is None:
        raise ValueError('Source omitted its retained handling extension')
    for key in ('units', 'movements', 'lineage', 'quarantine', 'handoffs'):
        records = {record['id']: record for record in new.get(key, [])}
        for record in old.get(key, []):
            saved = records.get(record['id'])
            if saved is None:
                raise ValueError('Source omitted retained handling history: ' + key)
            if key == 'units':
                if any(saved[field] != record[field] for field in IMMUTABLE_UNIT):
                    raise ValueError('Source changed immutable unit identity or contents')
                if any(saved[field] < record[field] for field in ('version', 'last_sequence', 'custody_generation')):
                    raise ValueError('Source unit counters regressed')
                if saved['version'] == record['version'] and saved != record:
                    raise ValueError('Source changed a unit without advancing its version')
            elif key == 'handoffs':
                if any(saved[field] != record[field] for field in ('run_id', 'epoch', 'source', 'destination_owner', 'origin', 'destination')) or any(saved['unit'][field] != record['unit'][field] for field in IMMUTABLE_UNIT):
                    raise ValueError('Source changed immutable handoff provenance')
                before, after = HANDOFF_ORDER[record['state']], HANDOFF_ORDER[saved['state']]
                if after < before:
                    raise ValueError('Source handoff phase regressed')
                if before < HANDOFF_ORDER['departed'] <= after and saved['state'] != 'quarantined':
                    expected = deepcopy(record['unit'])
                    expected.update(state='in_transit', position=None, origin=record['origin'],
                                    destination=record['destination'], handoff_id=record['id'])
                    for field in ('version', 'last_sequence', 'custody_generation'):
                        expected[field] += 1
                    if saved['unit'] != expected:
                        raise ValueError('Departure changed or skipped the accepted manifest')
                elif saved['unit'] != record['unit']:
                    raise ValueError('Source rewrote a frozen custody manifest')
                for field in ('departure_token', 'receipt_id'):
                    if record[field] is not None and saved[field] != record[field]:
                        raise ValueError('Source changed a durable custody proof')
            elif saved != record:
                raise ValueError('Source reused handling history identity with different content')


class ManifestConflict(ValueError):
    def __init__(self, source, expected, claimed):
        super().__init__('Observed handling unit conflicts with its registered identity')
        self.conflict = {'source': source, 'unit_id': claimed['id'],
                         'barcode': claimed['barcode'], 'expected': expected, 'claimed': claimed}


def register_manifests(db, source, handling):
    from psycopg.types.json import Jsonb
    for unit in [*handling['units'], *(handoff['unit'] for handoff in handling['handoffs'])]:
        manifest = {key: unit[key] for key in IMMUTABLE_UNIT}
        saved = db.execute('SELECT manifest FROM twin_unit_manifests WHERE unit_id=%s OR barcode=%s',
                           (unit['id'], unit['barcode'])).fetchone()
        if saved:
            if saved['manifest'] != manifest:
                raise ManifestConflict(source, saved['manifest'], manifest)
        else:
            db.execute('INSERT INTO twin_unit_manifests(unit_id,barcode,manifest,first_source) VALUES (%s,%s,%s,%s)',
                       (unit['id'], unit['barcode'], Jsonb(manifest), source))


def validate_handling_events(source, handling, events):
    for collection, kind in (('movements', 'unit-movement'), ('lineage', 'lineage')):
        prefix = source + ':' + kind + ':'
        observed = {event['id']: event for event in events if isinstance(event.get('id'), str) and event['id'].startswith(prefix)}
        expected = {prefix + record['id']: record for record in handling[collection]}
        if observed.keys() != expected.keys():
            raise ValueError('Handling history and event identities disagree')
        for identity, record in expected.items():
            if any(observed[identity].get(key) != value for key, value in record.items() if key != 'id'):
                raise ValueError('Handling history and event contents disagree')


def reconcile_handling(sources):
    """Resolve observations with directed durable receipt proofs, never clocks.

    A departing source retains a historical shadow at the predecessor node.
    Only the recipient's own unit record can supply its confirmed position.
    """
    from simulator.handling_contracts import catalog
    groups, unsupported = {}, []
    for source in sources:
        handling = (source.get('snapshot') or {}).get('handling')
        if handling is None:
            unsupported.append(source['name'])
            continue
        for collection in ('units', 'handoffs'):
            for record in handling[collection]:
                unit = record if collection == 'units' else record['unit']
                key = unit['run_id'], unit['epoch'], unit['id']
                group = groups.setdefault(key, {'observations': [], 'handoffs': [], 'conflicts': []})
                if collection == 'units':
                    group['observations'].append({'source': source['name'], 'unit': unit,
                                                  'connected': source.get('connected', False)})
                else:
                    group['handoffs'].append(record)
    # Rejected sources may have no accepted snapshot and sort before the
    # registered owner. Apply their evidence after collecting every unit.
    for source in sources:
        for conflict in source.get('handling_conflicts', []):
            for key, group in groups.items():
                if key[2] == conflict['unit_id']:
                    group['conflicts'].append(conflict)
    records = []
    for (run_id, epoch, identity), group in sorted(groups.items()):
        observations, handoffs = group['observations'], group['handoffs']
        if not observations:
            continue
        reasons = list(group['conflicts'])
        witnesses, edges = {}, {}
        for handoff in handoffs:
            witnesses.setdefault(handoff['id'], []).append(handoff)
        for copies in witnesses.values():
            first = copies[0]
            for field in ('source', 'destination_owner', 'origin', 'destination'):
                if any(copy[field] != first[field] for copy in copies):
                    reasons.append({'reason': 'Conflicting handoff provenance', 'handoff_id': first['id']})
            for field in ('departure_token', 'receipt_id'):
                proofs = [copy[field] for copy in copies if copy[field] is not None]
                if proofs and any(proof != proofs[0] for proof in proofs):
                    reasons.append({'reason': 'Conflicting custody proof', 'handoff_id': first['id']})
            manifests = []
            for copy in copies:
                unit = deepcopy(copy['unit'])
                if copy['state'] in ('offered', 'accepted'):
                    unit.update(state='in_transit', position=None, origin=copy['origin'],
                                destination=copy['destination'], handoff_id=copy['id'])
                    for counter in ('version', 'last_sequence', 'custody_generation'):
                        unit[counter] += 1
                if copy['state'] != 'quarantined':
                    manifests.append(unit)
            if manifests and any(unit != manifests[0] for unit in manifests):
                reasons.append({'reason': 'Conflicting custody manifest', 'handoff_id': first['id']})
            for copy in copies:
                if copy['state'] in ('received', 'acknowledged') and copy['departure_token'] and copy['receipt_id']:
                    generation = copy['unit']['custody_generation']
                    start = copy['source'], generation - 1
                    target = copy['destination_owner'], generation
                    edges.setdefault(start, set()).add(target)
        if any(len(targets) != 1 for targets in edges.values()):
            reasons.append({'reason': 'Forked custody receipts'})

        def node(observation):
            unit = observation['unit']
            generation = unit['custody_generation']
            outgoing = witnesses.get(unit['handoff_id'], [])
            if unit['state'] in ('in_transit', 'dispatched') and any(
                    handoff['source'] == observation['source'] and
                    handoff['unit']['custody_generation'] == generation for handoff in outgoing):
                generation -= 1
            return observation['source'], generation

        def leaf(start):
            visited = set()
            while len(edges.get(start, set())) == 1 and start not in visited:
                visited.add(start)
                start = next(iter(edges[start]))
            return start

        leaves = {leaf(node(observation)) for observation in observations}
        if len(leaves) != 1:
            reasons.append({'reason': 'Unconnected custody claims'})
        target = next(iter(leaves)) if len(leaves) == 1 else None
        candidates = [observation for observation in observations if node(observation) == target]
        incoming = {destination for destinations in edges.values() for destination in destinations}
        if target and target[1] > 0 and target not in incoming:
            reasons.append({'reason': 'Custody generation lacks a receipt proof'})
        selected = candidates[0] if len(candidates) == 1 else None
        if selected:
            for handoff in handoffs:
                if (handoff['destination_owner'], handoff['unit']['custody_generation']) == target and handoff['state'] in ('received', 'acknowledged'):
                    if any(selected['unit'][field] < handoff['unit'][field] for field in ('version', 'last_sequence')):
                        reasons.append({'reason': 'Recipient record predates its departure proof', 'handoff_id': handoff['id']})
        status = 'conflict' if reasons else 'confirmed' if selected else 'unobserved'
        unit = selected['unit'] if selected else observations[0]['unit']
        position = unit['position'] if status == 'confirmed' else None
        records.append({'id': identity, 'run_id': run_id, 'epoch': epoch,
                        'barcode': unit['barcode'], 'contents': unit['contents'], 'category': unit['category'],
                        'owner': target[0] if target and not reasons else None,
                        'custody_generation': target[1] if target and not reasons else None,
                        'state': unit['state'] if selected and not reasons else None,
                        'status': status, 'position': position, 'mapped': position in catalog(),
                        'connected': bool(selected and selected['connected']),
                        'observations': observations, 'conflicts': reasons})
    return {'version': 1, 'units': records, 'unsupported_sources': unsupported}
