"""Custody control transport only; native departments own state transitions."""
import json
from typing import Annotated, Any, Literal
from pydantic import WithJsonSchema, model_validator
from .contracts import Envelope
from .handling_contracts import contract_root, validate_handoff

HandoffPayload = Annotated[dict[str, Any], WithJsonSchema(
    json.loads((contract_root() / 'handoff.schema.json').read_text()))]


class HandlingEnvelope(Envelope):
    type: Literal['handling.offered.v1', 'handling.accepted.v1',
                  'handling.departed.v1', 'handling.received.v1',
                  'handling.acknowledged.v1', 'handling.quarantined.v1']
    payload: HandoffPayload

    @model_validator(mode='after')
    def custody_metadata(self):
        handoff = validate_handoff(self.payload, str(self.run_id), str(self.epoch))
        if self.type != f"handling.{handoff['state']}.v1":
            raise ValueError('Custody type differs from its durable transition')
        if str(self.aggregate_id) != handoff['id'] or str(self.causation_id) != handoff['id'] or self.aggregate_version != handoff['unit']['version']:
            raise ValueError('Custody envelope identity/version mismatch')
        source, destination = handoff['source'], handoff['destination_owner']
        if handoff['state'] in {'accepted', 'received'}:
            source, destination = destination, source
        elif handoff['state'] == 'quarantined' and self.source == destination:
            source, destination = destination, source
        if (self.source, self.destination) != (source, destination):
            raise ValueError('Custody sender or recipient does not own this transition')
        return self
