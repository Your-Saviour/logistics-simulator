"""Rebuild the checked-in editable FUXA project from its SVG and client script."""
import json
from pathlib import Path
root = Path(__file__).resolve().parent
names = ['frame', 'command', 'run_id', 'epoch', 'connected', 'heartbeat_ms', 'work_order',
         'simulation_time', 'cell_state', 'progress_seconds', 'duration_seconds', 'good_quantity',
         'scrap_quantity', 'guard_closed', 'power_available', 'part_present', 'positioned', 'clamped',
         'conveyor', 'cycle', 'fault', 'fault_reason', 'conveyor_jam', 'sensor_failure', 'guard_open',
         'power_loss', 'last_command_id', 'last_command_status', 'last_command_reason']
device = {'id': 'ot', 'name': 'Manufacturing OT', 'enabled': True, 'type': 'WebAPI', 'polling': 500,
          'property': {'getTags': 'http://ot-hmi-proxy:8011/tags', 'postTags': 'http://ot-hmi-proxy:8011/tags'},
          'tags': {name: {'id': name, 'name': name, 'type': 'string' if name in ['frame', 'command', 'run_id', 'epoch', 'work_order', 'cell_state', 'fault_reason', 'last_command_id', 'last_command_status', 'last_command_reason'] else 'number',
                          'address': name, 'daq': {'enabled': False, 'changed': False, 'interval': 60, 'restored': False}}
                   for name in names}}
view = {'id': 'simu54-cell', 'name': 'Assembly cell', 'type': 'svg',
        'profile': {'width': 1400, 'height': 1040, 'bkcolor': '#0b0c0a', 'margin': 0, 'align': 'topCenter', 'gridType': 'fixed', 'viewRenderDelay': 0},
        'items': {}, 'variables': {}, 'svgcontent': (root / 'cell.svg').read_text(),
        'property': {'events': [{'type': 'onopen', 'action': 'onRunScript', 'actparam': 's_simu54_boot', 'actoptions': {'params': []}},
                                {'type': 'onclose', 'action': 'onRunScript', 'actparam': 's_simu54_close', 'actoptions': {'params': []}}]}}
project = {'version': '1.00', 'devices': {'ot': device}, 'server': {'id': '0', 'name': 'FUXA Server', 'type': 'FuxaServer', 'property': {}, 'tags': {}},
           'hmi': {'layout': {'start': 'simu54-cell', 'autoresize': True, 'showdev': True, 'hidenavigation': True, 'theme': 'dark-theme', 'navigation': {'items': []}, 'header': {'items': []}}, 'views': [view]},
           'scripts': [{'id': 's_simu54_boot', 'name': 'Simu54Cell', 'mode': 'CLIENT', 'parameters': [], 'code': (root / 'client.js').read_text()},
                       {'id': 's_simu54_close', 'name': 'Simu54Close', 'mode': 'CLIENT', 'parameters': [], 'code': 'if (window.simu54Timer) clearInterval(window.simu54Timer);'}],
           'texts': [], 'alarms': [], 'notifications': []}
(root / 'project.json').write_text(json.dumps(project, indent=2) + '\n')
