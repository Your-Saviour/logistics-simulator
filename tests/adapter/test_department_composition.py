"""The shared adapter must accept every merged department's published fixtures."""
import json
from pathlib import Path
import pytest
from simulator.adapter_protocol import PAYLOADS
from simulator.adapter import transport_envelope


@pytest.mark.parametrize('name', ['sample.completed', 'storage-boundary', 'manufacturing-boundary', 'shipping-boundary', 'logistics-boundary'])
def test_shared_adapter_retains_each_department_wire_contract(name):
    event=json.loads((Path(__file__).resolve().parents[2]/'contracts/v1/fixtures'/f'{name}.json').read_text())
    incoming=transport_envelope.validate_python(event)
    publication=PAYLOADS['publish'].model_validate({'endpoint':event['destination']+'/events','envelope':event})
    assert incoming.type == publication.envelope.type == event.get('type', 'sample.completed.v1')
    assert incoming.payload.model_dump() == publication.envelope.payload.model_dump()
