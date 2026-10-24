from uuid import uuid4
import pytest
from pydantic import ValidationError
from simulator.shipping_contracts import transport_envelope


def envelope(kind='shipping.fact.v1'):
    order, intent = str(uuid4()), str(uuid4())
    return dict(schema_version='1.0', type=kind, event_id=str(uuid4()),
        federation_id='shipping-test', run_id=str(uuid4()), epoch=str(uuid4()),
        correlation_id=order, causation_id=intent, aggregate_id=order,
        aggregate_version=1, source='storage', destination='shipping', boundary='goods',
        effective_time=1, quantity_unit='item', payload=dict(intent_id=intent,
        owner='storage', result='reserved', reference=order, sku='PRODUCT',
        quantity=2, destination='CUSTOMER-A'))


def test_shipping_fact_exact_quantity_and_identity():
    e=envelope()
    assert transport_envelope.validate_python(e).payload.quantity == 2
    e['payload']['quantity']=True
    with pytest.raises(ValidationError): transport_envelope.validate_python(e)


def test_shipping_order_and_stock_operations_are_typed():
    e=envelope('shipping.order.v1')
    e.update(source='external-orders',boundary='orders',payload=dict(customer='ACME',destination='CUSTOMER-A',lines=[dict(sku='PRODUCT',quantity=2)]))
    assert transport_envelope.validate_python(e).payload.customer=='ACME'
    for kind in ['storage.pick.v1','storage.release.v1','storage.transfer.v1']:
        e=envelope(kind);e.update(source='shipping',destination='storage',boundary='requests',payload=dict(reference=str(uuid4())))
        if kind=='storage.transfer.v1':e['payload']['destination']='DISPATCH'
        assert transport_envelope.validate_python(e).type==kind


def test_legacy_sample_stays_supported():
    e=envelope('sample.completed.v1');e['payload']={'quantity':2}
    assert transport_envelope.validate_python(e).payload.quantity==2


@pytest.mark.parametrize('owner,boundary',[('storage','goods'),('manufacturing','goods'),('logistics','carrier')])
def test_each_explicit_provider_can_report_its_own_failure(owner,boundary):
    e=envelope();e['source']=owner;e['boundary']=boundary
    e['payload'].update(owner=owner,result='failed',reason='Provider declined')
    assert transport_envelope.validate_python(e).payload.result=='failed'
