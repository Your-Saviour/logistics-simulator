"""Projection regressions use the real owned PostgreSQL ledger."""
import os
import json
from pathlib import Path
from copy import deepcopy
from uuid import uuid4

import pytest
from simulator.store import Store
from twin.projection import ProjectionStore, Consumer


@pytest.fixture
def projection():
    store = Store(os.environ['TEST_DATABASE_URL'])
    store.migrate()
    with store.transaction() as db:
        db.execute('TRUNCATE twin_unit_manifests,twin_events,twin_revisions,twin_sources RESTART IDENTITY')
    return ProjectionStore(store)


def source():
    return {'name': 'shipping', 'url': 'http://shipping-api:8000',
            'username': 'observer', 'password': 'never-expose',
            'website_url': 'https://shipping.example.test'}


def snapshot():
    return {'version': 1, 'source': 'shipping', 'cursor': 'source-a',
            'run': {'id': str(uuid4()), 'epoch': str(uuid4()), 'granted': 5,
                    'requested': 6, 'committed': 5, 'state': 'running', 'speed': 1,
                    'anchor': '2026-01-01T00:00:00Z',
                    'scenario': {'time_zone': 'UTC'}},
            'snapshot': {'orders': [{'id': 'order-1', 'status': 'in_transit'}]},
            'events': [{'id': 'event-1', 'correlation_id': 'order-1',
                        'simulation_time': 5, 'action': 'dispatch'}]}


def handling_source():
    config = {**source(), 'name': 'storage', 'url': 'http://storage-api:8000'}
    value = snapshot()
    value['source'] = 'storage'
    identity = str(uuid4())
    unit = {'id': identity, 'barcode': 'HU-' + identity.replace('-', '').upper(),
            'run_id': value['run']['id'], 'epoch': value['run']['epoch'],
            'version': 1, 'custody_generation': 0, 'last_sequence': 1,
            'owner': 'storage', 'category': 'raw', 'state': 'available',
            'contents': [{'sku': 'COMPONENT', 'quantity': 2}],
            'position': 'storage.raw.r01.b01.l01', 'origin': None,
            'destination': None, 'handoff_id': None}
    move = {'id': str(uuid4()), 'unit_id': identity, 'barcode': unit['barcode'],
            'run_id': unit['run_id'], 'epoch': unit['epoch'], 'sequence': 1,
            'custody_generation': 0, 'action': 'receive', 'origin': None,
            'destination': unit['position'], 'simulation_time': 5,
            'references': {'transfer_id': None, 'batch_id': None, 'shipment_id': None}}
    value['snapshot']['handling'] = {'version': 1, 'catalog_version': 1,
        'units': [unit], 'movements': [move], 'handoffs': [], 'lineage': [], 'quarantine': []}
    value['events'].append({**move, 'id': 'storage:unit-movement:' + move['id'], 'kind': 'unit-movement'})
    return config, value


def capacity_source():
    config, value = handling_source()
    handling = value['snapshot']['handling']
    unit = handling['units'][0]
    unit.update(state='reserved', version=2)
    handling['handoffs'] = [{'id': str(uuid4()), 'run_id': unit['run_id'],
        'epoch': unit['epoch'], 'source': 'storage', 'destination_owner': 'manufacturing',
        'origin': unit['position'], 'destination': 'manufacturing.cell01.input01',
        'state': 'accepted', 'unit': deepcopy(unit), 'departure_token': None,
        'receipt_id': None, 'reason': None}]
    return config, value


def test_invalid_handling_snapshot_cannot_advance_cursor_or_change_units(projection):
    config, value = handling_source()
    projection.configure([config]); projection.accept(config, value)
    before = projection.view()
    for field, change in [('barcode', 'HU-' + '0' * 32), ('owner', 'shipping'),
                          ('epoch', str(uuid4())), ('contents', [{'sku': 'COMPONENT', 'quantity': 0}]),
                          ('position', 'shipping.receiving.dock01')]:
        bad = deepcopy(value); bad['cursor'] = 'invalid-handling'
        bad['snapshot']['handling']['units'][0][field] = change
        with pytest.raises(ValueError): projection.accept(config, bad)
        current = projection.view()
        assert current['sources'][0]['snapshot'] == before['sources'][0]['snapshot']
        assert current['sources'][0]['cursor'] == before['sources'][0]['cursor']
        assert current['revision'] == before['revision']


def test_handling_identity_and_complete_unit_history_survive_restarts(projection):
    config, value = handling_source()
    projection.configure([config]); projection.accept(config, value)
    restarted = ProjectionStore(projection.store)
    bad = deepcopy(value); bad['cursor'] = 'changed-contents'
    bad['snapshot']['handling']['units'][0]['contents'][0]['quantity'] = 3
    bad['snapshot']['handling']['units'][0]['version'] = 2
    with pytest.raises(ValueError): restarted.accept(config, bad)
    missing = deepcopy(value); missing['snapshot']['handling']['movements'] = []
    with pytest.raises(ValueError): restarted.accept(config, missing)
    omitted = deepcopy(value); omitted['snapshot']['handling']['units'] = []
    omitted['snapshot']['handling']['movements'] = []
    with pytest.raises(ValueError): restarted.accept(config, omitted)
    assert restarted.view()['sources'][0]['snapshot'] == value['snapshot']


def test_unknown_handling_endpoint_is_retained_without_inventing_coordinates(projection):
    config, value = handling_source()
    value['snapshot']['handling']['units'][0]['position'] = 'storage.future.rack99.slot01'
    value['snapshot']['handling']['movements'][0]['destination'] = 'storage.future.rack99.slot01'
    value['events'][-1]['destination'] = 'storage.future.rack99.slot01'
    projection.configure([config]); projection.accept(config, value)
    saved = projection.view()['sources'][0]['snapshot']['handling']['units'][0]
    assert saved['position'] == 'storage.future.rack99.slot01'
    assert 'coordinates' not in saved


def test_same_grant_cannot_reverse_an_observed_capacity_acceptance(projection):
    config, value = handling_source()
    handling = value['snapshot']['handling']
    unit = handling['units'][0]
    unit.update(state='reserved', version=2)
    handling['handoffs'] = [{'id': str(uuid4()), 'run_id': unit['run_id'],
        'epoch': unit['epoch'], 'source': 'storage', 'destination_owner': 'manufacturing',
        'origin': unit['position'], 'destination': 'manufacturing.cell01.input01',
        'state': 'accepted', 'unit': deepcopy(unit), 'departure_token': None,
        'receipt_id': None, 'reason': None}]
    projection.configure([config]); projection.accept(config, value)
    older = deepcopy(value); older['cursor'] = 'old-offer'
    older['snapshot']['handling']['handoffs'][0]['state'] = 'offered'
    with pytest.raises(ValueError): projection.accept(config, older)
    assert projection.view()['sources'][0]['cursor'] == value['cursor']


@pytest.mark.parametrize('field', ['version', 'last_sequence', 'custody_generation'])
def test_accepted_capacity_cannot_rewrite_its_reserved_manifest(projection, field):
    config, value = capacity_source()
    projection.configure([config]); projection.accept(config, value)
    bad = deepcopy(value); bad['cursor'] = 'changed-capacity'
    bad['snapshot']['handling']['handoffs'][0]['unit'][field] += 1
    with pytest.raises(ValueError): projection.accept(config, bad)
    assert projection.view()['sources'][0]['cursor'] == value['cursor']


@pytest.mark.parametrize('increment', [1, 2])
def test_departure_continues_the_exact_accepted_manifest(projection, increment):
    config, value = capacity_source()
    projection.configure([config]); projection.accept(config, value)
    departed = deepcopy(value); departed['cursor'] = 'departure'
    handling = departed['snapshot']['handling']; handoff = handling['handoffs'][0]
    unit = handling['units'][0]
    for field in ('version', 'last_sequence', 'custody_generation'):
        unit[field] += increment
    unit.update(state='in_transit', position=None, origin=handoff['origin'],
                destination=handoff['destination'], handoff_id=handoff['id'])
    handoff.update(state='departed', unit=deepcopy(unit))
    handoff['departure_token'] = {'id': str(uuid4()), 'handoff_id': handoff['id'],
        'unit_id': unit['id'], 'run_id': unit['run_id'], 'epoch': unit['epoch'],
        'unit_version': unit['version'], 'last_sequence': unit['last_sequence'],
        'custody_generation': unit['custody_generation']}
    move = {**handling['movements'][0], 'id': str(uuid4()), 'action': 'depart',
            'sequence': unit['last_sequence'], 'custody_generation': unit['custody_generation'],
            'origin': unit['origin'], 'destination': unit['destination']}
    handling['movements'].append(move)
    departed['events'].append({**move, 'id': 'storage:unit-movement:' + move['id'], 'kind': 'unit_movement'})
    if increment == 1:
        assert projection.accept(config, departed)
    else:
        with pytest.raises(ValueError): projection.accept(config, departed)


def test_restart_replay_and_atomic_snapshot_cursor_events(projection):
    config, value = source(), snapshot()
    projection.configure([config])
    projection.accept(config, value)
    first = projection.view()
    assert first['sources'][0]['snapshot']['orders'][0]['status'] == 'in_transit'
    assert first['sources'][0]['cursor'] == 'source-a'
    assert len(first['events']) == 1
    restarted = ProjectionStore(projection.store)
    restarted.accept(config, value)
    assert len(restarted.view()['events']) == 1
    value['cursor'] = 'source-b'
    value['snapshot']['orders'][0]['status'] = 'delivered'
    value['events'].append({'id': 'event-2', 'simulation_time': 5, 'action': 'delivery'})
    restarted.accept(config, value)
    current = restarted.view()
    assert current['revision'] > first['revision']
    assert len(current['events']) == 2
    assert current['sources'][0]['snapshot']['orders'][0]['status'] == 'delivered'
    assert 'never-expose' not in str(current)


def test_conflicting_event_rolls_back_snapshot_and_cursor(projection):
    config, value = source(), snapshot()
    projection.configure([config]); projection.accept(config, value)
    bad = deepcopy(value)
    bad['cursor'] = 'bad'
    bad['snapshot'] = {'orders': []}
    bad['events'][0]['action'] = 'forged'
    with pytest.raises(ValueError):
        projection.accept(config, bad)
    assert projection.view()['sources'][0]['cursor'] == 'source-a'
    assert len(projection.view()['sources'][0]['snapshot']['orders']) == 1


def test_out_of_order_watermark_and_epoch_reset(projection):
    config, value = source(), snapshot()
    projection.configure([config]); projection.accept(config, value)
    old = deepcopy(value); old['run']['committed'] = 4; old['cursor'] = 'old'
    with pytest.raises(ValueError): projection.accept(config, old)
    value['run']['id'] = str(uuid4()); value['run']['epoch'] = str(uuid4())
    value['run'].update(granted=0, committed=0, requested=0)
    value.update(cursor='new-run', events=[], snapshot={'orders': []})
    projection.accept(config, value)
    assert projection.view()['events'] == []
    assert projection.view()['sources'][0]['cursor'] == 'new-run'
    with pytest.raises(ValueError): projection.accept(config, old)


def test_stale_failure_retains_facts_but_not_live_connection(projection):
    config, value = source(), snapshot()
    projection.configure([config]); projection.accept(config, value)
    projection.failure(config['name'])
    item = projection.view()['sources'][0]
    assert not item['connected'] and item['stale']
    assert item['snapshot']['orders'][0]['status'] == 'in_transit'
    assert item['last_success_at']
    assert projection.view()['aligned'] is None
    projection.accept(config, value)
    with projection.store.transaction() as db:
        db.execute("UPDATE twin_sources SET last_success_at=clock_timestamp()-interval '20 seconds'")
    item = projection.view()['sources'][0]
    assert item['stale'] and not item['connected']


def test_zero_subset_removed_sources_and_alignment(projection):
    projection.configure([])
    assert projection.view()['sources'] == []
    config, value = source(), snapshot()
    projection.configure([config]); projection.accept(config, value)
    assert projection.view()['aligned']['committed'] == 5
    second = {**config, 'name': 'storage'}
    other = {**value, 'source': 'storage', 'run': {**value['run'], 'id': str(uuid4())}}
    projection.configure([config, second]); projection.accept(second, other)
    assert projection.view()['aligned'] is None
    projection.configure([])
    assert projection.view()['sources'] == [] and projection.view()['events'] == []


def test_rejected_invalid_projection_does_not_change_durable_state(projection):
    config, value = source(), snapshot()
    projection.configure([config])
    for change in ({'source': 'storage'}, {'run': {'id': 'invalid'}},
                   {'events': [{'id': 'x'}, {'id': 'x'}]},
                   {'snapshot': []}):
        with pytest.raises(ValueError): projection.accept(config, {**value, **change})
    assert projection.view()['sources'][0]['snapshot'] is None


def test_configuration_rejects_secret_links_duplicate_names_and_unknown_sources(projection):
    for config in ([source(), source()], [{**source(), 'website_url': 'https://user:secret@example.test'}],
                   [{**source(), 'name': 'unknown'}], [{**source(), 'url': 'file:///tmp/socket'}]):
        with pytest.raises(ValueError): projection.configure(config)


def test_consumer_http_catchup_independent_failure_and_generation(projection):
    import httpx
    config, value = source(), snapshot()
    response = [value]
    def upstream(request):
        if request.url.path == '/api/health/ready': return httpx.Response(404)
        assert request.url.path == '/api/projection'
        return httpx.Response(200, json=response[0])
    with httpx.Client(transport=httpx.MockTransport(upstream)) as client:
        consumer = Consumer(projection, [config], client)
        consumer.tick()
        response[0] = {'source': 'wrong', 'password': config['password']}
        consumer.tick()
    saved = projection.view()
    assert not saved['sources'][0]['connected']
    assert saved['sources'][0]['snapshot']['orders'][0]['status'] == 'in_transit'
    assert 'never-expose' not in str(saved)
    older = projection.begin('shipping')
    newer = projection.begin('shipping')
    assert projection.accept(config, value, newer)
    projection.failure('shipping', older)
    assert projection.view()['sources'][0]['connected']
    assert projection.accept(config, value, older) is False


def test_alignment_requires_same_calendar_origin(projection):
    config, value = source(), snapshot()
    value['run']['scenario']['start_at'] = '2026-01-01T00:00:00Z'
    second = {**config, 'name': 'storage'}
    other = deepcopy(value); other['source'] = 'storage'
    other['run']['scenario']['start_at'] = '2026-02-01T00:00:00Z'
    projection.configure([config, second])
    projection.accept(config, value); projection.accept(second, other)
    assert projection.view()['aligned'] is None


def test_event_fields_reject_nonfinite_time_and_wrong_run(projection):
    config, value = source(), snapshot()
    projection.configure([config])
    for fields in ({'simulation_time': float('inf')}, {'simulation_time': '5'},
                   {'run_id': str(uuid4())}, {'epoch': str(uuid4())}):
        bad = deepcopy(value); bad['events'][0].update(fields)
        with pytest.raises(ValueError): projection.accept(config, bad)


def test_bad_source_response_does_not_block_other_sources(projection):
    import httpx
    config, value = source(), snapshot()
    other = {**config, 'name': 'storage', 'url': 'http://storage-api:8000'}
    def upstream(request):
        if request.url.host == 'storage-api': return httpx.Response(200, content=b'{not JSON')
        return httpx.Response(200, json=value)
    with httpx.Client(transport=httpx.MockTransport(upstream)) as client:
        Consumer(projection, [other, config], client).tick()
    saved = {s['name']: s for s in projection.view()['sources']}
    assert saved['shipping']['connected'] and saved['shipping']['snapshot']['orders']
    assert not saved['storage']['connected'] and saved['storage']['snapshot'] is None


def test_history_omission_and_overlapping_polls_cannot_regress_snapshot(projection):
    config, value = source(), snapshot()
    projection.configure([config]); projection.accept(config, value)
    missing = deepcopy(value); missing.update(cursor='omitted-history',events=[],snapshot={})
    with pytest.raises(ValueError): projection.accept(config, missing)
    assert projection.view()['sources'][0]['cursor']=='source-a'


def test_old_consumer_tolerates_source_removed_during_reconfiguration(projection):
    import httpx
    config = source()
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(500))) as client:
        consumer = Consumer(projection, [config], client)
        projection.configure([])
        consumer.tick()
    assert projection.view()['sources'] == []


def test_replaced_endpoint_cannot_be_revived_by_old_consumer(projection):
    import httpx
    config, value = source(), snapshot()
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200,json=value))) as client:
        old = Consumer(projection,[config],client); old.tick()
        projection.configure([{**config,'url':'http://replacement-api:8000'}])
        old.tick()
    assert not projection.view()['sources'][0]['connected']
    assert projection.view()['sources'][0]['snapshot']['orders']


def test_source_operational_health_is_retained_and_filtered(projection):
    config, value = source(), snapshot()
    value['health']={'heartbeats':[{'role':'worker','healthy':False,'password':'hidden'}],
                     'pending_jobs':3,'dead_letters':2,'broker':None,'ready':None,
                     'password':'hidden'}
    projection.configure([config]); projection.accept(config,value)
    health=projection.view()['sources'][0]['health']
    assert health['pending_jobs']==3 and health['dead_letters']==2
    assert health['heartbeats']==[{'role':'worker','healthy':False}]
    assert health['broker'] is None and 'hidden' not in str(health)


def test_readiness_probe_reports_unready_service_without_discarding_business_snapshot(projection):
    import httpx
    config,value=source(),snapshot()
    value['health']={'heartbeats':[],'pending_jobs':1,'dead_letters':0,'ready':None,'broker':None}
    def upstream(request):
        if request.url.path=='/api/health/ready': return httpx.Response(503,json={'ready':False,'broker':False})
        return httpx.Response(200,json=value)
    with httpx.Client(transport=httpx.MockTransport(upstream)) as client:
        Consumer(projection,[config],client).tick()
    current=projection.view()['sources'][0]
    assert current['connected'] and current['snapshot']['orders']
    assert current['health']['ready'] is False and current['health']['broker'] is False


def test_equivalent_native_timestamp_encodings_share_aligned_watermark(projection):
    config,value=source(),snapshot()
    value['run']['scenario']['start_at']='2026-01-05T08:00:00.0000000+10:30'
    second={**config,'name':'storage'}
    other=deepcopy(value); other['source']='storage'
    other['run']['scenario']['start_at']='2026-01-04T21:30Z'
    other['run'].update(granted=4,committed=4)
    projection.configure([config,second]); projection.accept(config,value); projection.accept(second,other)
    assert projection.view()['aligned']['committed']==4


@pytest.mark.parametrize('name', ['storage', 'manufacturing', 'shipping', 'logistics'])
def test_handling_validation_accepts_captured_native_factory_snapshots(name):
    from twin.handling_projection import validate_handling

    captured = json.loads((Path(__file__).parent / 'fixtures/handling-factory.json').read_text())
    handling = captured['handling'][name]
    times = [row['simulation_time'] for key in ('movements', 'lineage', 'quarantine')
             for row in handling.get(key, [])]
    # The fixture retains native handling bodies; the synthetic envelope grant
    # simply covers their recorded times for this isolated validation test.
    run = {'id': captured['run_id'], 'epoch': captured['epoch'], 'granted': max(times, default=0)}
    assert validate_handling(name, run, handling) == handling
