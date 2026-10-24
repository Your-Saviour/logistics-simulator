from datetime import datetime, timezone
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class SamplePayload(BaseModel):
    model_config = ConfigDict(extra='forbid')
    quantity: int = Field(strict=True, ge=1, le=10000)


class Envelope(BaseModel):
    model_config = ConfigDict(extra='forbid')
    schema_version: Literal['1.0'] = '1.0'
    type: Literal['sample.completed.v1'] = 'sample.completed.v1'
    event_id: UUID = Field(default_factory=uuid4)
    federation_id: str = Field(min_length=1, max_length=128)
    run_id: UUID
    epoch: UUID
    correlation_id: UUID
    causation_id: UUID
    aggregate_id: UUID
    aggregate_version: int = Field(ge=1, strict=True)
    source: str = Field(min_length=1)
    destination: str = Field(min_length=1)
    boundary: str = Field(min_length=1)
    effective_time: float = Field(ge=0, allow_inf_nan=False, strict=True)
    wall_time: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    quantity_unit: Literal['item'] = 'item'
    payload: SamplePayload

    @field_validator('wall_time', mode='before')
    @classmethod
    def wall_time_type(cls, value):
        if not isinstance(value, (str, datetime)):
            raise ValueError('Wall timestamp must be an offset-bearing date-time string')
        return value

    @model_validator(mode='after')
    def wall_time_offset(self):
        if self.wall_time.utcoffset() is None:
            raise ValueError('Wall timestamp requires an explicit UTC offset')
        return self
