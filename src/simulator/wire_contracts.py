"""Private adapter wire union; departmental public schemas remain independently owned."""
from typing import Annotated
from pydantic import BeforeValidator, Field, TypeAdapter
from .contracts import Envelope
from .handling_wire import HandlingEnvelope
from .storage_contracts import ReceiptEnvelope, RequestEnvelope, ArrivalEnvelope, FactEnvelope, legacy_sample_default
from .logistics_contracts import LogisticsRequestEnvelope, LogisticsReceiptEnvelope, LogisticsFactEnvelope
from .manufacturing_contracts import DemandEnvelope
from .shipping_contracts import (ShippingOrderEnvelope, ShippingFactEnvelope,
    StorageReferenceEnvelope, StorageTransferEnvelope, StorageRejectionEnvelope)

TransportEnvelope = Annotated[
    Envelope | ReceiptEnvelope | RequestEnvelope | ArrivalEnvelope | FactEnvelope |
    DemandEnvelope | LogisticsRequestEnvelope | LogisticsReceiptEnvelope | LogisticsFactEnvelope |
    ShippingOrderEnvelope | ShippingFactEnvelope | StorageReferenceEnvelope |
    StorageTransferEnvelope | StorageRejectionEnvelope | HandlingEnvelope,
    Field(discriminator='type'), BeforeValidator(legacy_sample_default)]
transport_envelope = TypeAdapter(TransportEnvelope)
