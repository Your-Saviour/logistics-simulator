"""Private adapter wire union; departmental public schemas remain independently owned."""
from typing import Annotated
from pydantic import BeforeValidator, Field, TypeAdapter
from .contracts import Envelope
from .storage_contracts import ReceiptEnvelope, RequestEnvelope, ArrivalEnvelope, FactEnvelope, legacy_sample_default
from .logistics_contracts import LogisticsRequestEnvelope, LogisticsReceiptEnvelope, LogisticsFactEnvelope

TransportEnvelope = Annotated[
    Envelope | ReceiptEnvelope | RequestEnvelope | ArrivalEnvelope | FactEnvelope |
    LogisticsRequestEnvelope | LogisticsReceiptEnvelope | LogisticsFactEnvelope,
    Field(discriminator='type'), BeforeValidator(legacy_sample_default)]
transport_envelope = TypeAdapter(TransportEnvelope)
