"""Transport-only manufacturing messages; Java owns all production execution."""
from .handling_wire import HandlingEnvelope
from typing import Annotated, Literal
from pydantic import Field, TypeAdapter
from .contracts import Envelope
from .storage_contracts import (ReceiptEnvelope, RequestEnvelope, ArrivalEnvelope, IssueEnvelope,
                               FactEnvelope, Code, Quantity, Strict, legacy_sample_default)


class DemandInput(Strict):
    product: Code
    line: Code
    quantity: Quantity


class DemandEnvelope(Envelope):
    type: Literal['manufacturing.demand.v1']
    destination: Literal['manufacturing']
    boundary: Literal['demand']
    aggregate_version: int = Field(strict=True, ge=1, le=1)
    payload: DemandInput


TransportEnvelope = Annotated[
    Envelope | ReceiptEnvelope | RequestEnvelope | ArrivalEnvelope | IssueEnvelope | FactEnvelope | DemandEnvelope | HandlingEnvelope,
    Field(discriminator='type')]
# Preserve omitted legacy sample type, without modifying the published storage schema.
from pydantic import BeforeValidator
TransportEnvelope = Annotated[TransportEnvelope, BeforeValidator(legacy_sample_default)]
transport_envelope = TypeAdapter(TransportEnvelope)
