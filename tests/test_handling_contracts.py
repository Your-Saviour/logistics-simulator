"""Published handling contracts must reject unsafe physical records."""
import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker, ValidationError

ROOT = Path(__file__).resolve().parents[1] / 'contracts/handling/v1'


def contract(name):
    path = ROOT / (name + '.schema.json')
    assert path.exists(), f'Missing published {name} handling contract'
    schema = json.loads(path.read_text())
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def fixture(name):
    return json.loads((ROOT / 'fixtures.json').read_text())[name]


def test_unit_contract_accepts_confirmed_and_pending_placement():
    validator = contract('unit')
    validator.validate(fixture('placed_unit'))
    validator.validate(fixture('transit_unit'))
    validator.validate(fixture('consumed_unit'))


@pytest.mark.parametrize('change', [
    {'barcode': 'not-a-barcode'}, {'contents': []},
    {'contents': [{'sku': 'RAW-STEEL', 'quantity': 0}]},
    {'contents': [{'sku': 'RAW-STEEL', 'quantity': 1.5}]},
    {'state': 'available', 'position': None},
    {'state': 'in_transit', 'position': 'storage.raw.r01.b01.l01'},
    {'state': 'in_transit', 'handoff_id': None},
    {'state': 'consumed', 'position': 'storage.raw.r01.b01.l01'},
    {'owner': 'twin'}, {'epoch': 'yesterday'}, {'version': 0},
])
def test_unit_contract_rejects_invalid_stock_and_fabricated_placement(change):
    validator = contract('unit')
    with pytest.raises(ValidationError):
        validator.validate({**fixture('placed_unit'), **change})


def test_movement_contract_retains_identity_scope_endpoints_and_business_reference():
    validator = contract('movement')
    movement = fixture('movement')
    validator.validate(movement)
    for field in ('id', 'unit_id', 'barcode', 'sequence', 'run_id', 'epoch',
                  'origin', 'destination', 'simulation_time', 'references'):
        invalid = copy.deepcopy(movement)
        del invalid[field]
        with pytest.raises(ValidationError):
            validator.validate(invalid)
    for field, value in [('simulation_time', -1), ('sequence', 0), ('destination', '')]:
        with pytest.raises(ValidationError):
            validator.validate({**movement, field: value})


def test_handoff_contract_requires_departure_evidence_before_receipt():
    validator = contract('handoff')
    for name in ('offered_handoff', 'departed_handoff', 'received_handoff'):
        validator.validate(fixture(name))
    invalid = fixture('received_handoff')
    invalid['departure_token'] = None
    with pytest.raises(ValidationError):
        validator.validate(invalid)


def test_facility_catalog_covers_real_operations_without_duplicate_endpoints():
    assert (ROOT / 'facility.json').exists(), 'Missing fixed physical catalog'
    catalog = json.loads((ROOT / 'facility.json').read_text())
    endpoints = catalog['locations']
    assert len({row['id'] for row in endpoints}) == len(endpoints)
    assert len([row for row in endpoints if row['kind'] == 'shelf']) >= 500
    assert {'shelf', 'dock', 'cell_input', 'cell_output', 'truck'} <= {row['kind'] for row in endpoints}
    for row in endpoints:
        assert row['capacity'] == 1
        assert row['owner'] in {'storage', 'manufacturing', 'logistics', 'shipping'}
        assert len(row['position']) == 3 and len(row['access']) == 3
        assert row['compatible'] and set(row['compatible']) <= {'raw', 'finished'}
    elevated = [row for row in endpoints if row['kind'] == 'shelf' and row['position'][1] > 1]
    assert elevated, 'Shelves require actual elevations for robotic lifting'


def test_protocol_fixtures_enforce_whole_units_capacity_identity_and_epoch():
    from simulator.handling_contracts import validate_snapshot, allocate_whole, validate_handoff

    placed = fixture('placed_unit')
    validate_snapshot([placed])
    for invalid in ([placed, placed], [{**placed, 'barcode': 'HU-22222222222242228222222222222222'}, placed]):
        with pytest.raises(ValueError):
            validate_snapshot(invalid)
    with pytest.raises(ValueError, match='capacity'):
        validate_snapshot([placed, {**placed, 'id': '22222222-2222-4222-8222-222222222222',
                                    'barcode': 'HU-22222222222242228222222222222222'}])
    units = [placed, {**placed, 'id': '22222222-2222-4222-8222-222222222222',
                      'barcode': 'HU-22222222222242228222222222222222', 'position': 'storage.raw.r01.b02.l01',
                      'contents': [{'sku': 'RAW-STEEL', 'quantity': 6}]}]
    assert allocate_whole(units, {'RAW-STEEL': 6}) == ['22222222-2222-4222-8222-222222222222']
    assert allocate_whole(units, {'RAW-STEEL': 10}) == [placed['id'], '22222222-2222-4222-8222-222222222222']
    with pytest.raises(ValueError, match='whole'):
        allocate_whole(units, {'RAW-STEEL': 5})
    with pytest.raises(ValueError, match='scope'):
        validate_handoff(fixture('departed_handoff'), placed['run_id'], '33333333-3333-4333-8333-333333333333')


def test_allocation_rejects_reserved_consumed_and_incompatible_mixed_units():
    from simulator.handling_contracts import allocate_whole

    unit = fixture('placed_unit')
    for state in ('reserved', 'in_transit', 'consumed'):
        with pytest.raises(ValueError, match='whole'):
            allocate_whole([{**unit, 'state': state}], {'RAW-STEEL': 4})
    with pytest.raises(ValueError, match='whole'):
        allocate_whole([{**unit, 'contents': [*unit['contents'], {'sku': 'OTHER', 'quantity': 1}]}], {'RAW-STEEL': 4})


def test_handoff_tokens_bind_identity_version_generation_and_reserved_origin():
    from simulator.handling_contracts import validate_handoff

    for name in ('offered_handoff', 'departed_handoff', 'received_handoff'):
        value = fixture(name)
        validate_handoff(value, value['run_id'], value['epoch'])
    for field, value in [('unit_id', '99999999-9999-4999-8999-999999999999'),
                         ('custody_generation', 2), ('last_sequence', 99), ('unit_version', 99)]:
        handoff = fixture('departed_handoff')
        handoff['departure_token'][field] = value
        with pytest.raises(ValueError):
            validate_handoff(handoff, handoff['run_id'], handoff['epoch'])
    handoff = fixture('offered_handoff')
    handoff['unit']['state'] = 'available'
    with pytest.raises(ValueError, match='reserved'):
        validate_handoff(handoff, handoff['run_id'], handoff['epoch'])


def test_projection_validation_rejects_wrong_category_duplicate_contents_and_scope():
    from simulator.handling_contracts import validate_snapshot

    placed = fixture('placed_unit')
    for change in ({'category': 'finished'}, {'owner': 'shipping'},
                   {'position': 'unknown.rack'}, {'contents': placed['contents'] * 2}):
        with pytest.raises(ValueError):
            validate_snapshot([{**placed, **change}])
    with pytest.raises(ValueError, match='scope'):
        validate_snapshot([placed], epoch='33333333-3333-4333-8333-333333333333')


def test_movement_validation_rejects_fabricated_endpoints_and_scope():
    from simulator.handling_contracts import validate_movement

    value = fixture('movement')
    validate_movement(value, value['run_id'], value['epoch'])
    for change in ({'destination': value['origin']}, {'destination': 'unknown.rack'},
                   {'barcode': 'HU-' + '9' * 32},
                   {'epoch': '33333333-3333-4333-8333-333333333333'}):
        with pytest.raises(ValueError):
            validate_movement({**value, **change}, value['run_id'], value['epoch'])
