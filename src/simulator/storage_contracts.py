"""Transport schemas only. Inventory execution remains in the C# department."""
from typing import Annotated, Literal
from uuid import UUID
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, TypeAdapter
from .contracts import Envelope

Code = Annotated[str, Field(pattern=r'^[A-Z0-9][A-Z0-9_-]{0,31}$')]
Quantity = Annotated[int, Field(strict=True, ge=1, le=10000)]


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid')


class ReceiptInput(Strict):
    sku: Code
    location: Code
    quantity: Quantity


class RequestInput(ReceiptInput):
    purpose: Literal['production', 'customer']


class ArrivalInput(Strict):
    reference: UUID


class ReceiptFact(ReceiptInput):
    id: UUID
    run_id: UUID
    correlation_id: UUID
    status: Literal['expected', 'received']
    version: int = Field(strict=True, ge=1)


class ReservationFact(ReceiptInput):
    id: UUID
    run_id: UUID
    correlation_id: UUID
    purpose: Literal['production', 'customer']
    status: Literal['reserved', 'picked', 'released', 'issued', 'transferred']
    version: int = Field(strict=True, ge=1)


class TransferFact(Strict):
    id: UUID
    run_id: UUID
    reservation_id: UUID
    sku: Code
    origin: Code
    destination: Code
    quantity: Quantity
    correlation_id: UUID
    status: Literal['in_transit', 'received']
    version: int = Field(strict=True, ge=1)


class ReceiptEnvelope(Envelope):
    type: Literal['storage.receipt.v1']
    destination: Literal['storage']
    boundary: Literal['supply']
    aggregate_version: int = Field(strict=True, ge=1, le=1)
    payload: ReceiptInput


class RequestEnvelope(Envelope):
    type: Literal['storage.request.v1']
    destination: Literal['storage']
    boundary: Literal['requests']
    aggregate_version: int = Field(strict=True, ge=1, le=1)
    payload: RequestInput


class ArrivalEnvelope(Envelope):
    type: Literal['storage.transfer.arrived.v1']
    destination: Literal['storage']
    boundary: Literal['requests']
    aggregate_version: int = Field(strict=True, ge=1, le=1)
    payload: ArrivalInput


class FactEnvelope(Envelope):
    type: Literal['storage.expect.completed.v1', 'storage.receive.completed.v1',
                  'storage.reserve.completed.v1', 'storage.release.completed.v1',
                  'storage.issue.completed.v1', 'storage.pick.completed.v1',
                  'storage.transfer.completed.v1', 'storage.arrive.completed.v1']
    source: Literal['storage']
    payload: ReceiptFact | ReservationFact | TransferFact


# Preserve the published sample schema exactly, while making the adapter a
# typed transport for both legacy samples and department-owned domain messages.
def legacy_sample_default(value):
    # The original sample schema permits omitted type and defaults to sample.
    # Preserve that behavior before the union's discriminator is evaluated.
    if isinstance(value, dict) and 'type' not in value:
        return {'type': 'sample.completed.v1', **value}
    return value


TransportEnvelope = Annotated[
    Envelope | ReceiptEnvelope | RequestEnvelope | ArrivalEnvelope | FactEnvelope,
    Field(discriminator='type'), BeforeValidator(legacy_sample_default)]
transport_envelope = TypeAdapter(TransportEnvelope)
