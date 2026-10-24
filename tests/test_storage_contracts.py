import copy
import json
from pathlib import Path
import jsonschema
import pytest
from pydantic import ValidationError
from simulator.storage_contracts import transport_envelope
from simulator.adapter_protocol import Publication


def test_storage_domain_fixture_and_invalid_shapes_match_published_schema():
    raw=json.loads(Path('contracts/v1/fixtures/storage-boundary.json').read_text())
    schema=json.loads(Path('contracts/v1/storage-boundary.schema.json').read_text())
    validator=jsonschema.Draft202012Validator(schema,format_checker=jsonschema.FormatChecker())
    validator.validate(raw);transport_envelope.validate_python(raw)
    for changes in ({'type':'storage.unknown.v1'}, {'payload':{'sku':'COMPONENT','location':'RAW-A','quantity':True}},
                    {'payload':{'sku':'COMPONENT','location':'RAW-A','quantity':1,'unknown':1}},
                    {'aggregate_version':2}, {'destination':'other'}, {'boundary':'requests'}):
        wrong={**copy.deepcopy(raw),**changes}
        with pytest.raises(ValidationError):transport_envelope.validate_python(wrong)
        assert list(validator.iter_errors(wrong))
    publication={'endpoint':'storage/events','envelope':raw}
    Publication.model_validate(publication)


def test_http_warehouse_command_schema_strict_actions_and_fields():
    schema=json.loads(Path('contracts/http/v1/warehouse-command.schema.json').read_text())
    validator=jsonschema.Draft202012Validator(schema,format_checker=jsonschema.FormatChecker())
    common={'run_id':'20000000-0000-4000-8000-000000000001','epoch':'30000000-0000-4000-8000-000000000001','due_at':2}
    expect={**common,'action':'expect','sku':'COMPONENT','location':'RAW-A','quantity':1,'correlation_id':common['run_id']}
    expect['units']=[{'id':common['run_id'],'quantity':1}]
    validator.validate(expect)
    validator.validate({**common,'action':'arrive','reference':common['run_id']})
    for changes in ({'quantity':True},{'quantity':1.5},{'quantity':0},{'unknown':1},{'reference':common['run_id']},{'action':'bogus'}):
        assert list(validator.iter_errors({**expect,**changes}))
    assert list(validator.iter_errors({k:v for k,v in expect.items() if k!='units'}))
    validator.validate({**expect,'action':'convert','units':[{'id':common['run_id'],'quantity':1,'position':'storage.raw.r01.b01.l01'}]})
    for action in ('putaway','retrieve'):
        validator.validate({**common,'action':action,'unit_id':common['run_id'],'destination':'storage.raw.r01.b01.l01'})
    validator.validate({**common,'action':'issue','reference':common['run_id'],
                        'unit_destinations':{common['run_id']:'manufacturing.cell03.input04'}})


def test_material_issue_transports_the_receivers_exact_unit_endpoint_assignment():
    from simulator.manufacturing_contracts import transport_envelope as manufacturing
    raw=json.loads(Path('contracts/v1/fixtures/storage-boundary.json').read_text())
    unit='40000000-0000-4000-8000-000000000001'
    raw.update(type='storage.issue.v1', source='manufacturing', boundary='requests',
               payload={'reference':raw['aggregate_id'],
                        'unit_destinations':{unit:'manufacturing.cell02.input03'}})
    transport_envelope.validate_python(raw)
    manufacturing.validate_python(raw)
    Publication.model_validate({'endpoint':'storage/events','envelope':raw})
    for destinations in ({}, {unit:'storage.raw.r01.b01.l01'}, {'not-a-uuid':'manufacturing.cell02.input03'}):
        wrong={**raw,'payload':{**raw['payload'],'unit_destinations':destinations}}
        with pytest.raises(ValidationError):transport_envelope.validate_python(wrong)


def test_production_reservation_carries_the_exact_reserved_source_unit_manifest():
    raw=json.loads(Path('contracts/v1/fixtures/storage-boundary.json').read_text())
    unit=json.loads(Path('contracts/handling/v1/fixtures.json').read_text())['placed_unit']
    unit.update(state='reserved',run_id=raw['run_id'],epoch=raw['epoch'])
    raw.update(type='storage.reserve.completed.v1',source='storage',destination='manufacturing',boundary='materials',
               aggregate_version=1,payload={'id':raw['aggregate_id'],'run_id':raw['run_id'],
               'correlation_id':raw['correlation_id'],'sku':unit['contents'][0]['sku'],
               'quantity':unit['contents'][0]['quantity'],'location':'RAW-A','purpose':'production',
               'status':'reserved','version':1,'unit_manifest':[unit]})
    transport_envelope.validate_python(raw)
    Publication.model_validate({'endpoint':'manufacturing/events','envelope':raw})
    for change in ({'quantity':raw['payload']['quantity']+1}, {'unit_manifest':[unit,unit]},
                   {'unit_manifest':[{**unit,'state':'available'}]}, {'unit_manifest':[{**unit,'version':2147483645}]}):
        with pytest.raises(ValidationError):transport_envelope.validate_python({**raw,'payload':{**raw['payload'],**change}})


def test_customer_reservation_preserves_finished_unit_identity_for_shipping():
    raw=json.loads(Path('contracts/v1/fixtures/storage-boundary.json').read_text())
    unit=json.loads(Path('contracts/handling/v1/fixtures.json').read_text())['placed_unit']
    unit.update(state='reserved',category='finished',run_id=raw['run_id'],epoch=raw['epoch'],
                position='storage.finished.r01.b01.l01')
    raw.update(type='storage.reserve.completed.v1',source='storage',destination='shipping',boundary='goods',
               aggregate_version=1,payload={'id':raw['aggregate_id'],'run_id':raw['run_id'],
               'correlation_id':raw['correlation_id'],'sku':unit['contents'][0]['sku'],
               'quantity':unit['contents'][0]['quantity'],'location':'FINISHED-A','purpose':'customer',
               'status':'reserved','version':1,'unit_manifest':[unit]})
    Publication.model_validate({'endpoint':'shipping/events','envelope':raw})
    for change in ({'quantity':raw['payload']['quantity']+1}, {'unit_manifest':[unit,unit]},
                   {'unit_manifest':[{**unit,'category':'raw'}]}):
        with pytest.raises(ValidationError):Publication.model_validate({'endpoint':'shipping/events','envelope':{**raw,'payload':{**raw['payload'],**change}}})
