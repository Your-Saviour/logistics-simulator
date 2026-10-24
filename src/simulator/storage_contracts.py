"""Transport schemas only. Inventory execution remains in the C# department."""
from .handling_wire import HandlingEnvelope
from .handling_contracts import contract_root, validate_unit
import json
from typing import Annotated, Any, Literal
from uuid import UUID
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, TypeAdapter, WithJsonSchema, model_validator
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


class IssueInput(ArrivalInput):
    unit_destinations: dict[UUID, Annotated[str, Field(pattern=r'^manufacturing\.cell0[1-4]\.input0[1-4]$')]] = Field(min_length=1, max_length=4)

    @model_validator(mode='after')
    def distinct_input_endpoints(self):
        if len(set(self.unit_destinations.values())) != len(self.unit_destinations):
            raise ValueError('Distinct whole-unit receiving endpoints required')
        return self


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
    unit_manifest: list[Annotated[dict[str, Any], WithJsonSchema(
        json.loads((contract_root() / 'unit.schema.json').read_text()))]] | None = Field(default=None, min_length=1, max_length=8)

    @model_validator(mode='after')
    def exact_reserved_units(self):
        if self.unit_manifest is None:
            return self
        if self.status != 'reserved' or len(self.unit_manifest) > (4 if self.purpose == 'production' else 8):
            raise ValueError('Only compatible reserved allocations carry selected unit manifests')
        category = 'raw' if self.purpose == 'production' else 'finished'
        maximum_sequence = 2147483645 if self.purpose == 'production' else 2147483644
        identities=set()
        total=0
        for unit in self.unit_manifest:
            validate_unit(unit)
            if unit['version'] > 2147483644 or unit['last_sequence'] > maximum_sequence or unit['custody_generation'] > 2147483646:
                raise ValueError('Selected counters lack native departure, receipt and consumption headroom')
            if unit['id'] in identities or unit['owner'] != 'storage' or unit['category'] != category or unit['state'] != 'reserved' or unit['run_id'] != str(self.run_id):
                raise ValueError('Invalid selected source custody identity')
            if len(unit['contents']) != 1 or unit['contents'][0]['sku'] != self.sku:
                raise ValueError('Selected unit must match reserved SKU')
            identities.add(unit['id'])
            total+=unit['contents'][0]['quantity']
        if total != self.quantity:
            raise ValueError('Selected units must exactly equal reservation quantity')
        return self


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
    destination_owner: Literal['shipping'] | None = None
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


class IssueEnvelope(Envelope):
    type: Literal['storage.issue.v1']
    source: Literal['manufacturing']
    destination: Literal['storage']
    boundary: Literal['requests']
    aggregate_version: int = Field(strict=True, ge=1, le=1)
    payload: IssueInput


class FactEnvelope(Envelope):
    type: Literal['storage.expect.completed.v1', 'storage.receive.completed.v1',
                  'storage.reserve.completed.v1', 'storage.release.completed.v1',
                  'storage.issue.completed.v1', 'storage.pick.completed.v1',
                  'storage.transfer.completed.v1', 'storage.arrive.completed.v1']
    source: Literal['storage']
    payload: ReceiptFact | ReservationFact | TransferFact

    @model_validator(mode='after')
    def selected_manifest_scope(self):
        if isinstance(self.payload, ReservationFact) and self.payload.unit_manifest is not None:
            if self.aggregate_id != self.payload.id or self.run_id != self.payload.run_id or self.correlation_id != self.payload.correlation_id or self.aggregate_version != self.payload.version or any(unit['epoch'] != str(self.epoch) for unit in self.payload.unit_manifest):
                raise ValueError('Selected unit manifest envelope scope or identity mismatch')
        return self


# Preserve the published sample schema exactly, while making the adapter a
# typed transport for both legacy samples and department-owned domain messages.
def legacy_sample_default(value):
    # The original sample schema permits omitted type and defaults to sample.
    # Preserve that behavior before the union's discriminator is evaluated.
    if isinstance(value, dict) and 'type' not in value:
        return {'type': 'sample.completed.v1', **value}
    return value


TransportEnvelope = Annotated[
    Envelope | ReceiptEnvelope | RequestEnvelope | ArrivalEnvelope | IssueEnvelope | FactEnvelope | HandlingEnvelope,
    Field(discriminator='type'), BeforeValidator(legacy_sample_default)]
transport_envelope = TypeAdapter(TransportEnvelope)
