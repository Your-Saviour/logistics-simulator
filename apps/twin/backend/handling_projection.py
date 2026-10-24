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
