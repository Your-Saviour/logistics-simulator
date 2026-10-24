"""Versioned bootstrap federation mappings; no runtime dependencies."""
import json

ROUTES = {'manufacturing': ('storage', 'supply'), 'storage': ('logistics', 'destinations'), 'logistics': ('shipping', 'carrier'), 'shipping': ('manufacturing', 'demand')}
PROVIDERS = {
    'manufacturing': {'materials': 'synthetic', 'demand': 'helics', 'power': 'helics'},
    'storage': {'supply': 'helics', 'requests': 'synthetic'},
    'logistics': {'transport': 'synthetic', 'destinations': 'helics'},
    'shipping': {'orders': 'synthetic', 'goods': 'synthetic', 'carrier': 'helics'},
}


def config(name, broker, power=False):
    result = {'name': name, 'coreType': 'tcp_ss', 'coreInit': '--federates=1', 'broker': broker,
              'period': 1.0, 'timeDelta': 1.0,
              'endpoints': [{'name': name+'/events', 'global': True, 'type': 'application/json'}],
              'publications': [{'key': 'available_power_kw' if power else 'completed_items', 'type': 'double', 'unit': 'kW' if power else 'item'}]}
    if not power:
        result['subscriptions'] = [{'key': 'external-power/available_power_kw', 'type': 'double', 'unit': 'kW', 'required': True}]
    return json.dumps(result)


def peers_for(app):
    peers={}
    for source,(destination,boundary) in ROUTES.items():
        if destination==app:
            peers[boundary]={'source':source,'endpoint':source+'/events'}
    if app=='manufacturing':
        peers['power']={'source':'external-power','endpoint':'external-power/events','value_target':'external-power/available_power_kw'}
    return peers
