"""Wire validation only; all transport business effects belong to Go."""
from .handling_wire import HandlingEnvelope
from typing import Annotated, Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator
from .contracts import Envelope
from .storage_contracts import UnitManifest

Code = Annotated[str, Field(pattern=r'^[A-Z0-9][A-Z0-9_-]{0,31}$')]
Quantity = Annotated[int, Field(strict=True, ge=1, le=10000)]

class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid')

class TransportRequest(Strict):
    customer_destination: Code | None = None
    route: Code
    sku: Code
    quantity: Quantity
    external_reference: UUID | None = None
    unit_ids: list[UUID] = Field(default_factory=list, max_length=256)
    unit_manifest: list[UnitManifest] | None = Field(default=None, min_length=1, max_length=8)

    @model_validator(mode='after')
    def exact_expected_units(self):
        if self.unit_manifest is not None:
            if self.customer_destination is None:
                raise ValueError('Expected shipment requires the exact customer destination')
            ids = [unit.id for unit in self.unit_manifest]
            if len(set(ids)) != len(ids) or len(set(self.unit_ids)) != len(self.unit_ids) or set(ids) != set(self.unit_ids) or sum(unit.quantity for unit in self.unit_manifest) != self.quantity:
                raise ValueError('Expected manifest must preserve exact whole identities and quantity')
        return self

class TransportReceipt(Strict):
    reference: UUID

class TransportRecord(Strict):
    unit_destinations: dict[UUID, str] = Field(default_factory=dict)
    customer_destination: Code | None = None
    unit_ids: list[UUID] = Field(default_factory=list, max_length=256)
    id: UUID
    run_id: UUID
    epoch: UUID
    correlation_id: UUID
    external_reference: UUID | None
    route: Code
    origin: Code
    destination: Code
    journey_seconds: float = Field(ge=1,le=604800,allow_inf_nan=False)
    sku: Code
    quantity: Quantity
    vehicle: Code | None
    status: Literal['requested','assigned','loaded','in_transit','arrived','unloaded','received']
    custody: Literal['origin','vehicle','destination']
    provider: bool
    version: int = Field(strict=True,ge=1)
    planned_eta: float | None
    departed_at: float | None
    arrived_at: float | None
    unloaded_at: float | None
    received_at: float | None

class LogisticsRequestEnvelope(Envelope):
    type: Literal['logistics.request.v1']
    destination: Literal['logistics']
    boundary: Literal['transport']
    aggregate_version: int = Field(strict=True,ge=1,le=1)
    payload: TransportRequest

    @model_validator(mode='after')
    def expected_authority(self):
        if self.payload.unit_manifest is not None and (self.source != 'shipping' or self.payload.external_reference != self.aggregate_id):
            raise ValueError('Expected units require the exact Shipping dispatch request authority')
        return self

class LogisticsReceiptEnvelope(Envelope):
    type: Literal['logistics.receipt.v1']
    destination: Literal['logistics']
    boundary: Literal['destinations']
    aggregate_version: int = Field(strict=True,ge=1,le=1)
    payload: TransportReceipt

class LogisticsFactEnvelope(Envelope):
    type: Literal['logistics.request.completed.v1','logistics.assign.completed.v1',
        'logistics.load.completed.v1','logistics.depart.completed.v1','logistics.arrive.completed.v1',
        'logistics.unload.completed.v1','logistics.receive.completed.v1']
    source: Literal['logistics']
    payload: TransportRecord

LogisticsEnvelope = Annotated[LogisticsRequestEnvelope | LogisticsReceiptEnvelope | LogisticsFactEnvelope | HandlingEnvelope, Field(discriminator='type')]
logistics_envelope = TypeAdapter(LogisticsEnvelope)
