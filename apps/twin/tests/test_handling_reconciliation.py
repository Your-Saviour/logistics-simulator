"""Cross-source observation rules use Twin's real owned PostgreSQL store."""
from copy import deepcopy
from uuid import uuid4

import pytest
from test_projection import projection, handling_source
from twin.projection import ProjectionStore


def other_source(value, name='manufacturing'):
    copied = deepcopy(value)
    copied['source'] = name
    unit = copied['snapshot']['handling']['units'][0]
    unit.update(owner=name, position='manufacturing.cell01.input01')
    copied['snapshot']['handling']['movements'][0]['destination'] = unit['position']
    copied['events'][-1].update(id=name + ':unit-movement:' + copied['snapshot']['handling']['movements'][0]['id'], destination=unit['position'])
    config = {'name': name, 'url': 'http://' + name + '-api:8000', 'username': 'observer', 'password': 'test-only'}
    return config, copied


def test_global_manifest_conflict_rolls_back_source_cursor_and_survives_restart(projection):
    storage, original = handling_source()
    manufacturing, changed = other_source(original)
    changed['snapshot']['handling']['units'][0]['contents'][0]['quantity'] += 1
    projection.configure([storage, manufacturing]); projection.accept(storage, original)
    before = projection.view()
    restarted = ProjectionStore(projection.store)
    with pytest.raises(ValueError) as error:
        restarted.accept(manufacturing, changed)
    after = restarted.view()
    assert after['revision'] == before['revision']
    assert next(row for row in after['sources'] if row['name'] == 'manufacturing')['cursor'] is None
    assert len(after['events']) == len(before['events'])
    # A failed source observation is visible without accepting its stock claims.
    restarted.failure('manufacturing', conflict=error.value.conflict)
    failed = next(row for row in restarted.view()['sources'] if row['name'] == 'manufacturing')
    assert failed['handling_conflicts'][0]['unit_id'] == original['snapshot']['handling']['units'][0]['id']
    assert not failed['connected']
    assert restarted.view()['handling']['units'][0]['status'] == 'conflict'
    assert restarted.view()['handling']['units'][0]['position'] is None
    # Corrected observations clear the rejected claim without deleting identity.
    corrected = other_source(original)[1]
    restarted.accept(manufacturing, corrected)
    assert not next(row for row in restarted.view()['sources'] if row['name'] == 'manufacturing')['handling_conflicts']


def test_global_unit_identity_cannot_be_recycled_in_another_epoch(projection):
    config, value = handling_source()
    projection.configure([config]); projection.accept(config, value)
    recycled = deepcopy(value)
    recycled['run'].update(id=str(uuid4()), epoch=str(uuid4()))
    for row in [*recycled['snapshot']['handling']['units'], *recycled['snapshot']['handling']['movements'], *recycled['events']]:
        if 'run_id' in row:
            row.update(run_id=recycled['run']['id'], epoch=recycled['run']['epoch'])
    with pytest.raises(ValueError): ProjectionStore(projection.store).accept(config, recycled)
    assert projection.view()['sources'][0]['cursor'] == value['cursor']


@pytest.mark.parametrize('change', ['missing', 'changed', 'extra'])
def test_unit_history_events_and_snapshot_must_agree_on_first_observation(projection, change):
    config, value = handling_source()
    projection.configure([config])
    if change == 'missing':
        value['events'].pop()
    elif change == 'changed':
        value['events'][-1]['destination'] = 'storage.raw.r01.b02.l01'
    else:
        event = deepcopy(value['events'][-1]); event['id'] = 'storage:unit-movement:' + str(uuid4()); value['events'].append(event)
    with pytest.raises(ValueError): projection.accept(config, value)
    assert projection.view()['sources'][0]['snapshot'] is None


def test_unproven_cross_source_claims_never_choose_a_clock_winner(projection):
    storage, original = handling_source()
    manufacturing, claimed = other_source(original)
    claimed['run'].update(granted=999, committed=999)
    projection.configure([storage, manufacturing])
    projection.accept(storage, original); projection.accept(manufacturing, claimed)
    record = projection.view()['handling']['units'][0]
    assert record['status'] == 'conflict'
    assert record['position'] is None
    assert {row['source'] for row in record['observations']} == {'storage', 'manufacturing'}


def test_single_source_unknown_position_is_retained_without_mapping(projection):
    config, value = handling_source()
    unit = value['snapshot']['handling']['units'][0]
    unit['position'] = 'storage.future.rack01'
    value['snapshot']['handling']['movements'][0]['destination'] = unit['position']
    value['events'][-1]['destination'] = unit['position']
    projection.configure([config]); projection.accept(config, value)
    record = projection.view()['handling']['units'][0]
    assert record['position'] == unit['position']
    assert not record['mapped']
    assert record['status'] == 'confirmed'


def test_captured_native_receipts_resolve_terminal_custody_without_duplicate_stock():
    import json
    from pathlib import Path
    from twin.handling_projection import reconcile_handling
    captured = json.loads((Path(__file__).parent / 'fixtures/handling-factory.json').read_text())
    sources = [{'name': name, 'snapshot': {'handling': handling}, 'connected': True,
                'status': {'run': {'id': captured['run_id'], 'epoch': captured['epoch']}}}
               for name, handling in captured['handling'].items()]
    records = reconcile_handling(sources)['units']
    assert len(records) == 2
    assert all(record['position'] is None for record in records)
    assert {record['owner'] for record in records} == {'manufacturing', 'logistics'}
    assert all(record['status'] == 'confirmed' for record in records)
    # A recipient can be observed independently of its predecessors.
    recipient = reconcile_handling([source for source in sources if source['name'] == 'manufacturing'])['units']
    assert next(record for record in recipient if record['category'] == 'raw')['status'] == 'confirmed'
    missing_recipient = next(record for record in recipient if record['category'] == 'finished')
    assert missing_recipient['status'] == 'unobserved'
    assert missing_recipient['owner'] == 'storage'
    assert missing_recipient['position'] is None


@pytest.mark.parametrize('name', ['storage', 'manufacturing', 'shipping', 'logistics'])
def test_native_history_shapes_pass_complete_snapshot_event_agreement(projection, name):
    import json
    from pathlib import Path
    from test_projection import snapshot
    captured = json.loads((Path(__file__).parent / 'fixtures/handling-factory.json').read_text())
    config = {'name': name, 'url': 'http://' + name + '-api:8000', 'username': 'observer', 'password': 'test-only'}
    value = snapshot()
    value['source'] = name
    value['run'].update(id=captured['run_id'], epoch=captured['epoch'], granted=10000, committed=10000)
    handling = captured['handling'][name]
    value['snapshot']['handling'] = handling
    value['events'] = []
    for collection, kind in (('movements', 'unit-movement'), ('lineage', 'lineage')):
        for record in handling[collection]:
            value['events'].append({**record, 'id': name + ':' + kind + ':' + record['id'], 'kind': kind})
    projection.configure([config])
    assert projection.accept(config, value)
    assert len(projection.view()['events']) == len(value['events'])


def test_receipt_does_not_authorize_a_recipient_record_older_than_departure():
    import json
    from pathlib import Path
    from twin.handling_projection import reconcile_handling
    captured = json.loads((Path(__file__).parent / 'fixtures/handling-factory.json').read_text())
    handling = deepcopy(captured['handling']['logistics'])
    handling['units'][0].update(version=1, last_sequence=1)
    records = reconcile_handling([{'name': 'logistics', 'connected': True, 'snapshot': {'handling': handling}}])['units']
    assert records[0]['status'] == 'conflict'
    assert records[0]['position'] is None
