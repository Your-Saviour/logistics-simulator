"""Deterministic boundary input interfaces; domain V1 handlers can consume them."""
from hashlib import sha256
from typing import Literal
from uuid import UUID, uuid5
from pydantic import BaseModel, ConfigDict, Field
from .scenario import Scenario

KINDS = {
    'manufacturing': {'materials':'supply','demand':'demand'},
    'storage': {'supply':'receiving','requests':'demand'},
    'logistics': {'transport':'demand','destinations':'carrier'},
    'shipping': {'orders':'demand','goods':'receiving','carrier':'carrier'},
}


class SeededInput(BaseModel):
    model_config=ConfigDict(extra='forbid')
    schema_version: Literal['1.0']='1.0'
    input_id: UUID
    run_id: UUID
    epoch: UUID
    application: Literal['manufacturing','storage','logistics','shipping']
    boundary: str=Field(min_length=1)
    kind: Literal['demand','supply','receiving','carrier']
    provider: Literal['synthetic']='synthetic'
    effective_time: float=Field(ge=0,allow_inf_nan=False)
    quantity: int=Field(ge=1,le=10,strict=True)
    quantity_unit: Literal['item']='item'


def seeded_inputs(providers,app,scenario: Scenario,run_id,epoch,slot,due_at):
    inputs=[]
    for boundary,kind in KINDS.get(app,{}).items():
        if providers[boundary]!='synthetic':
            continue
        digest=sha256(f'{scenario.seed}:{app}:{boundary}:{slot}'.encode()).digest()
        inputs.append(SeededInput(input_id=uuid5(UUID(str(run_id)),f'{epoch}:{boundary}:{slot}:{scenario.seed}'),
                                  run_id=run_id,epoch=epoch,application=app,boundary=boundary,kind=kind,
                                  effective_time=due_at,quantity=1+int.from_bytes(digest[:4],'big')%10))
    return inputs
