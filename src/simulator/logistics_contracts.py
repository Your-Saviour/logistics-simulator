"""Wire validation only; all transport business effects belong to Go."""
from typing import Annotated, Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter
from .contracts import Envelope

Code = Annotated[str, Field(pattern=r'^[A-Z0-9][A-Z0-9_-]{0,31}$')]
Quantity = Annotated[int, Field(strict=True, ge=1, le=10000)]

class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid')

class TransportRequest(Strict):
    route: Code
    sku: Code
    quantity: Quantity
    external_reference: UUID | None = None

class TransportReceipt(Strict):
    reference: UUID

class TransportRecord(Strict):
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

LogisticsEnvelope = Annotated[LogisticsRequestEnvelope | LogisticsReceiptEnvelope | LogisticsFactEnvelope, Field(discriminator='type')]
logistics_envelope = TypeAdapter(LogisticsEnvelope)
