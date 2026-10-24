"""Strict language-neutral control plane; no business execution lives here."""
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field
from .manufacturing_contracts import TransportEnvelope


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Command(Strict):
    version: Literal['1.0']
    request_id: UUID
    run_id: UUID
    epoch: UUID
    session_id: UUID
    operation: Literal['initialize','poll','receive_ack','request_time','publish','publish_value','checkpoint','finalize']
    payload: dict


class Empty(Strict): pass


class TimeRequest(Strict):
    target: float = Field(ge=0, allow_inf_nan=False, strict=True)
    committed: float = Field(ge=0, allow_inf_nan=False, strict=True)
    pending_work: int = Field(ge=0, strict=True)
    pending_outputs: int = Field(ge=0, strict=True)


class ReceiveAck(Strict):
    event_ids: list[UUID] = Field(max_length=10000)


class Publication(Strict):
    endpoint: str = Field(min_length=1, max_length=256)
    envelope: TransportEnvelope


class ValuePublication(Strict):
    value: float = Field(allow_inf_nan=False, strict=True)
    unit: Literal['item']


PAYLOADS = {'initialize':Empty, 'poll':Empty, 'receive_ack':ReceiveAck,
            'request_time':TimeRequest, 'publish':Publication,
            'publish_value':ValuePublication, 'checkpoint':Empty, 'finalize':Empty}
