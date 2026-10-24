"""Shipping wire types only; PHP owns scheduling and all business effects."""
from .handling_wire import HandlingEnvelope
from typing import Annotated, Any, Literal
from uuid import UUID
from pydantic import BeforeValidator, Field, TypeAdapter, model_validator
from .contracts import Envelope
from .storage_contracts import (Strict, Code, Quantity, ReceiptEnvelope, RequestEnvelope,
    ArrivalEnvelope, FactEnvelope, legacy_sample_default)


class OrderLine(Strict):
    sku: Code
    quantity: Quantity


class CustomerOrder(Strict):
    customer: str = Field(min_length=1, max_length=128)
    destination: Code
    lines: list[OrderLine] = Field(min_length=1, max_length=100)

    @model_validator(mode='after')
    def distinct_skus(self):
        if len({line.sku for line in self.lines}) != len(self.lines):
            raise ValueError('duplicate SKU')
        return self


class ShippingOrderEnvelope(Envelope):
    type: Literal['shipping.order.v1']
    source: Literal['external-orders']
    destination: Literal['shipping']
    boundary: Literal['orders']
    aggregate_version: int = Field(strict=True, ge=1, le=1)
    payload: CustomerOrder


class ProviderFact(Strict):
    intent_id: UUID
    owner: Literal['storage', 'manufacturing', 'logistics']
    result: Literal['reserved', 'shortage', 'produced', 'picked', 'transferred', 'received',
                    'released', 'departed', 'delivered', 'failed']
    reference: UUID
    sku: Code | None = None
    quantity: Quantity | None = None
    destination: Code
    peer_reference: UUID | None = None
    reason: str | None = Field(default=None, min_length=1, max_length=1000)


class ShippingFactEnvelope(Envelope):
    type: Literal['shipping.fact.v1']
    destination: Literal['shipping']
    boundary: Literal['goods', 'carrier']
    payload: ProviderFact

    @model_validator(mode='after')
    def owner_and_identity(self):
        expected = self.payload.owner if self.payload.result == 'failed' else ('logistics' if self.payload.result in ('departed','delivered') else
                    'manufacturing' if self.payload.result == 'produced' else 'storage')
        if self.source != expected or self.payload.owner != self.source:
            raise ValueError('outcome owner mismatch')
        if self.causation_id != self.payload.intent_id or self.aggregate_id != self.payload.reference:
            raise ValueError('outcome identity mismatch')
        if self.boundary != ('carrier' if expected == 'logistics' else 'goods'):
            raise ValueError('outcome boundary mismatch')
        return self


class ReferenceInput(Strict):
    reference: UUID


class TransferInput(ReferenceInput):
    destination: Code


class StorageReferenceEnvelope(Envelope):
    type: Literal['storage.pick.v1', 'storage.release.v1']
    destination: Literal['storage']
    boundary: Literal['requests']
    aggregate_version: int = Field(strict=True, ge=1, le=1)
    payload: ReferenceInput


class StorageTransferEnvelope(Envelope):
    type: Literal['storage.transfer.v1']
    destination: Literal['storage']
    boundary: Literal['requests']
    aggregate_version: int = Field(strict=True, ge=1, le=1)
    payload: TransferInput


class StorageRejection(Strict):
    action: Literal['expect','reserve','receive','release','issue','pick','transfer','arrive']
    reason: str = Field(min_length=1, max_length=1000)
    request: dict[str, Any]


class StorageRejectionEnvelope(Envelope):
    type: Literal['storage.command.rejected.v1']
    source: Literal['storage']
    payload: StorageRejection



# These are shared wire contracts, not implementations of either peer's domain.
class ProductionDemand(Strict):
    product: Code
    line: Code
    quantity: Quantity


class ProductionDemandEnvelope(Envelope):
    type: Literal['manufacturing.demand.v1']
    destination: Literal['manufacturing']
    boundary: Literal['demand']
    aggregate_version: int = Field(strict=True, ge=1, le=1)
    payload: ProductionDemand


class CarrierRequest(Strict):
    route: Code
    sku: Code
    quantity: Quantity
    external_reference: UUID | None = None


class CarrierRequestEnvelope(Envelope):
    type: Literal['logistics.request.v1']
    destination: Literal['logistics']
    boundary: Literal['transport']
    aggregate_version: int = Field(strict=True, ge=1, le=1)
    payload: CarrierRequest


class CarrierRecord(Strict):
    id: UUID
    run_id: UUID
    epoch: UUID
    correlation_id: UUID
    external_reference: UUID | None
    route: Code
    origin: Code
    destination: Code
    journey_seconds: float = Field(ge=1, le=604800, allow_inf_nan=False)
    sku: Code
    quantity: Quantity
    vehicle: Code | None
    status: Literal['requested','assigned','loaded','in_transit','arrived','unloaded','received']
    custody: Literal['origin','vehicle','destination']
    provider: bool
    version: int = Field(strict=True, ge=1)
    planned_eta: float | None
    departed_at: float | None
    arrived_at: float | None
    unloaded_at: float | None
    received_at: float | None


class CarrierFactEnvelope(Envelope):
    type: Literal['logistics.request.completed.v1','logistics.assign.completed.v1',
        'logistics.load.completed.v1','logistics.depart.completed.v1','logistics.arrive.completed.v1',
        'logistics.unload.completed.v1','logistics.receive.completed.v1']
    source: Literal['logistics']
    payload: CarrierRecord


TransportEnvelope = Annotated[
    Envelope | ReceiptEnvelope | RequestEnvelope | ArrivalEnvelope | FactEnvelope |
    ShippingOrderEnvelope | ShippingFactEnvelope | StorageReferenceEnvelope |
    StorageTransferEnvelope | StorageRejectionEnvelope | ProductionDemandEnvelope |
    CarrierRequestEnvelope | CarrierFactEnvelope | HandlingEnvelope,
    Field(discriminator='type'), BeforeValidator(legacy_sample_default)]
transport_envelope = TypeAdapter(TransportEnvelope)
