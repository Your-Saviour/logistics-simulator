import json
import os
from dataclasses import dataclass, field

BOUNDARIES = {
    'manufacturing': ('materials', 'demand', 'power'),
    'storage': ('supply', 'requests'),
    'logistics': ('transport', 'destinations'),
    'shipping': ('orders', 'goods', 'carrier'),
    'twin': (),
}


@dataclass
class Settings:
    app: str = 'storage'
    mode: str = 'standalone'
    providers: dict = field(default_factory=dict)
    database_url: str = ''
    amqp_url: str = ''
    username: str = 'operator'
    password: str = ''
    quantum: float = 1
    federation_id: str = ''
    run_id: str = ''
    epoch: str = ''
    helics_config: str = ''
    identities: list = field(default_factory=list)
    scenario: dict = field(default_factory=dict)

    def __post_init__(self):
        if self.app not in BOUNDARIES or self.mode not in ('standalone', 'helics'):
            raise ValueError('Unknown application or clock mode')
        if not self.quantum >= 1 or not self.quantum < float('inf'):
            raise ValueError('Handoff quantum must be finite and at least one second')
        expected = set(BOUNDARIES[self.app])
        if not self.providers:
            if self.mode == 'helics' and expected:
                raise ValueError('Connected mode requires explicit HELICS boundary providers')
            self.providers = dict.fromkeys(expected, 'synthetic')
        if set(self.providers) != expected:
            raise ValueError('Exactly one provider is required for every declared boundary')
        if any(value not in ('synthetic', 'helics') for value in self.providers.values()):
            raise ValueError('Each boundary needs one synthetic or HELICS provider')
        if self.mode == 'standalone' and any(value != 'synthetic' for value in self.providers.values()):
            raise ValueError('Standalone boundaries must use explicit synthetic providers')
        if self.mode == 'helics' and expected and 'helics' not in self.providers.values():
            raise ValueError('Connected mode requires at least one HELICS peer')
        from .scenario import Scenario
        self.scenario=Scenario.model_validate(self.scenario).model_dump(mode='json')
        if self.password or self.identities:
            from .security import accounts
            accounts(self)

    @classmethod
    def from_env(cls):
        return cls(
            app=os.getenv('SIMULATOR', 'storage'), mode=os.getenv('CLOCK_MODE', 'standalone'),
            providers=json.loads(os.getenv('BOUNDARY_PROVIDERS', '{}')),
            database_url=os.environ['DATABASE_URL'], amqp_url=os.environ['AMQP_URL'],
            username=os.getenv('APP_USERNAME', 'operator'), password=os.environ['APP_PASSWORD'],
            quantum=float(os.getenv('HANDOFF_QUANTUM', '1')),
            federation_id=os.getenv('FEDERATION_ID', ''), run_id=os.getenv('FEDERATION_RUN_ID', ''),
            epoch=os.getenv('FEDERATION_EPOCH', ''), helics_config=os.getenv('HELICS_CONFIG', ''),
            identities=json.loads(os.getenv('APP_IDENTITIES', '[]')),
            scenario=json.loads(os.getenv('SCENARIO', '{}')),
        )
