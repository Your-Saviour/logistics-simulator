"""Transport schemas only. Inventory execution remains in the C# department."""
from typing import Annotated, Literal
from uuid import UUID
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, TypeAdapter, model_validator
from .contracts import Envelope

Code = Annotated[str, Field(pattern=r'^[A-Z0-9][A-Z0-9_-]{0,31}$')]
Quantity = Annotated[int, Field(strict=True, ge=1, le=10000)]


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid')


class StockQuantity(Strict):
    sku: Code
    location: Code
    quantity: Quantity


class UnitManifest(Strict):
    id: UUID
    quantity: Quantity


class ReceiptInput(StockQuantity):
    units: list[UnitManifest] = Field(min_length=1, max_length=256)

    @model_validator(mode='after')
    def exact_whole_manifest(self):
        if len({unit.id for unit in self.units}) != len(self.units):
            raise ValueError('Duplicate whole-unit identity')
        if sum(unit.quantity for unit in self.units) != self.quantity:
            raise ValueError('Whole-unit manifest must match the exact receipt quantity')
        return self


class RequestInput(StockQuantity):
    purpose: Literal['production', 'customer']


class ArrivalInput(Strict):
    reference: UUID


class ReceiptFact(StockQuantity):
    id: UUID
    run_id: UUID
    correlation_id: UUID
    status: Literal['expected', 'received']
    version: int = Field(strict=True, ge=1)
    unit_manifest: list[UnitManifest] | None = None


class ReservationFact(StockQuantity):
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
