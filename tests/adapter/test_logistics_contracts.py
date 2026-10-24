"""The private adapter must transport logistics commands without executing them."""
from uuid import uuid4
import pytest
from simulator.wire_contracts import transport_envelope

def envelope():
    return dict(schema_version='1.0',type='logistics.request.v1',event_id=str(uuid4()),
        federation_id='transport-test',run_id=str(uuid4()),epoch=str(uuid4()),
        correlation_id=str(uuid4()),causation_id=str(uuid4()),aggregate_id=str(uuid4()),aggregate_version=1,
        source='storage',destination='logistics',boundary='transport',effective_time=1,
        wall_time='2026-10-24T00:00:00Z',quantity_unit='item',
        payload=dict(route='WAREHOUSE-DISPATCH',sku='PRODUCT',quantity=5))

def test_adapter_transports_logistics_request_and_receipt():
    event=envelope()
    assert transport_envelope.validate_python(event).payload.quantity==5
    event.update(type='logistics.receipt.v1',boundary='destinations',payload={'reference':str(uuid4())})
    assert str(transport_envelope.validate_python(event).payload.reference)==event['payload']['reference']

@pytest.mark.parametrize('quantity',[True,1.5,'2',0])
def test_adapter_rejects_malformed_transport_quantity(quantity):
    event=envelope();event['payload']['quantity']=quantity
    with pytest.raises(ValueError):transport_envelope.validate_python(event)


def test_adapter_transports_exact_expected_shipping_manifest():
    event=envelope();identity=str(uuid4())
    event['source']='shipping'
    event['payload'].update(route='DISPATCH-CUSTOMER',customer_destination='CUSTOMER-A',unit_ids=[identity],
                            unit_manifest=[{'id':identity,'quantity':5}],external_reference=event['aggregate_id'])
    parsed=transport_envelope.validate_python(event)
    assert str(parsed.payload.unit_ids[0])==identity
    assert parsed.payload.unit_manifest[0].quantity==5
    for invalid in ([{'id':identity,'quantity':4}], [{'id':str(uuid4()),'quantity':5}]):
        with pytest.raises(ValueError):
            transport_envelope.validate_python({**event,'payload':{**event['payload'],'unit_manifest':invalid}})
    with pytest.raises(ValueError):
        transport_envelope.validate_python({**event,'source':'storage'})
