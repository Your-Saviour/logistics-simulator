"""Handling v1 validation for contract consumers, not a business stock owner.

Native departments enforce these invariants in their own SQL transactions.
This module validates projection/fixture boundaries and exact allocation examples.
"""
import json
from functools import lru_cache
from pathlib import Path
from uuid import UUID

from jsonschema import Draft202012Validator, FormatChecker, ValidationError


def contract_root():
    local = Path(__file__).resolve().parents[2] / 'contracts/handling/v1'
    return local if local.is_dir() else Path('contracts/handling/v1')


@lru_cache(maxsize=None)
def validator(name):
    schema = json.loads((contract_root() / (name + '.schema.json')).read_text())
    return Draft202012Validator(schema, format_checker=FormatChecker())


@lru_cache(maxsize=1)
def catalog():
    return {row['id']: row for row in json.loads((contract_root() / 'facility.json').read_text())['locations']}


def check(name, value):
    try:
        validator(name).validate(value)
    except ValidationError as error:
        raise ValueError(f'Invalid handling {name}: {error.message}') from error


def validate_unit(unit):
    check('unit', unit)
    if unit['barcode'] != 'HU-' + UUID(unit['id']).hex.upper():
        raise ValueError('Barcode must identify the immutable unit UUID')
    skus = [item['sku'] for item in unit['contents']]
    if len(set(skus)) != len(skus):
        raise ValueError('Unit contents must have one quantity per SKU')
    if unit['position'] is not None:
        location = catalog().get(unit['position'])
        if not location or location['owner'] != unit['owner'] or unit['category'] not in location['compatible']:
            raise ValueError('Incompatible or unknown confirmed position')
    return unit


def validate_snapshot(units, run_id=None, epoch=None):
    identities, barcodes, occupancy = set(), set(), {}
    for unit in units:
        validate_unit(unit)
        if run_id is not None and unit['run_id'] != run_id or epoch is not None and unit['epoch'] != epoch:
            raise ValueError('Unit scope mismatch')
        if unit['id'] in identities or unit['barcode'] in barcodes:
            raise ValueError('Duplicate handling-unit identity or barcode')
        identities.add(unit['id'])
        barcodes.add(unit['barcode'])
        if unit['position'] is not None:
            key = (unit['run_id'], unit['epoch'], unit['position'])
            occupancy[key] = occupancy.get(key, 0) + 1
            if occupancy[key] > catalog()[unit['position']]['capacity']:
                raise ValueError('Physical endpoint capacity exceeded')
    return units


def validate_movement(movement, run_id, epoch):
    check('movement', movement)
    if movement['run_id'] != run_id or movement['epoch'] != epoch:
        raise ValueError('Movement scope mismatch')
    if movement['barcode'] != 'HU-' + UUID(movement['unit_id']).hex.upper():
        raise ValueError('Movement barcode identity mismatch')
    if movement['origin'] == movement['destination']:
        raise ValueError('Movement must change physical position')
    if movement['destination'] not in catalog() or movement['origin'] is not None and movement['origin'] not in catalog():
        raise ValueError('Unknown movement endpoint')
    return movement


def allocate_whole(units, quantities):
    """Return deterministic exact subset IDs; never split or overfulfil.

    Callers must hold the owning run/allocation lock through reservation.
    A bounded search fails explicitly rather than consuming unbounded resources.
    """
    if not quantities or any(type(q) is not int or not 1 <= q <= 10000 for q in quantities.values()):
        raise ValueError('Positive integer whole-unit requirements required')
    keys = sorted(quantities)
    target = tuple(quantities[key] for key in keys)
    zero = (0,) * len(keys)
    paths = {zero: ()}
    seen = set()
    for unit in sorted(units, key=lambda row: row['id']):
        if unit['id'] in seen:
            raise ValueError('Duplicate handling-unit identity')
        seen.add(unit['id'])
        if unit['state'] != 'available':
            continue
        validate_unit(unit)
        contents = {item['sku']: item['quantity'] for item in unit['contents']}
        if set(contents) - set(keys):
            continue
        delta = tuple(contents.get(key, 0) for key in keys)
        for total, selected in list(paths.items()):
            next_total = tuple(a + b for a, b in zip(total, delta))
            if any(a > b for a, b in zip(next_total, target)) or next_total in paths:
                continue
            paths[next_total] = (*selected, unit['id'])
            if next_total == target:
                return list(paths[next_total])
            if len(paths) > 100000:
                raise ValueError('Whole-unit search limit exceeded; select explicit units')
    raise ValueError('No exact available whole-unit allocation; units cannot be split')


def validate_handoff(handoff, run_id, epoch):
    check('handoff', handoff)
    unit = validate_unit(handoff['unit'])
    if any(row['run_id'] != run_id or row['epoch'] != epoch for row in (handoff, unit)):
        raise ValueError('Handoff scope mismatch; quarantine required')
    origin, destination = (catalog().get(handoff[key]) for key in ('origin', 'destination'))
    if not origin or not destination or origin['owner'] != handoff['source'] or destination['owner'] != handoff['destination_owner']:
        raise ValueError('Handoff endpoint ownership mismatch')
    if handoff['source'] == handoff['destination_owner'] or unit['category'] not in destination['compatible']:
        raise ValueError('Handoff requires compatible distinct departments')
    if unit['owner'] != handoff['source']:
        raise ValueError('Handoff manifest must retain source custody provenance')
    token = handoff['departure_token']
    if token:
        if (token['handoff_id'], token['unit_id'], token['run_id'], token['epoch']) != (handoff['id'], unit['id'], run_id, epoch):
            raise ValueError('Departure token identity or scope mismatch')
        if any(token[field] != unit[other] for field, other in (
                ('custody_generation', 'custody_generation'), ('last_sequence', 'last_sequence'), ('unit_version', 'version'))):
            raise ValueError('Departure token sequence/version mismatch')
        if unit['state'] != 'in_transit' or unit['handoff_id'] != handoff['id'] or unit['origin'] != handoff['origin'] or unit['destination'] != handoff['destination']:
            raise ValueError('Departure token requires matching unplaced transit manifest')
    elif handoff['state'] in {'offered', 'accepted'} and (unit['state'] != 'reserved' or unit['position'] != handoff['origin']):
        raise ValueError('Offered units must be reserved at the source origin')
    return handoff
