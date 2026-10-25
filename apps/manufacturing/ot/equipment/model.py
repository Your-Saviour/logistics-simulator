"""Discrete batch-carrier equipment. Only acknowledged actuators move the model."""
import copy

FAULTS = {'conveyor_jam', 'sensor_failure', 'guard_open', 'power_loss'}


class Cell:
    def __init__(self, state=None):
        self.data = copy.deepcopy(state) if state is not None else {
            'batch': None, 'position': 0, 'clamped': False, 'progress_seconds': 0,
            'enabled': False, 'latched': False, 'faults': [], 'power_available': True,
            'completed': False, 'good_quantity': 0, 'scrap_quantity': 0,
        }

    def snapshot(self):
        return copy.deepcopy(self.data)

    def dispatch(self, batch):
        if self.data['batch'] and not self.data['completed']:
            raise ValueError('Cell capacity occupied by an unfinished batch')
        for name, minimum, maximum in [('quantity', 1, 10000), ('duration_seconds', 1, 86400), ('scrap_quantity', 0, 10000)]:
            if type(batch.get(name)) is not int or not minimum <= batch[name] <= maximum:
                raise ValueError('Invalid batch ' + name)
        if batch['scrap_quantity'] > batch['quantity']:
            raise ValueError('Scrap exceeds batch quantity')
        self.data.update(batch=copy.deepcopy(batch), position=0, clamped=False,
                         progress_seconds=0, completed=False, good_quantity=0, scrap_quantity=0,
                         enabled=False)

    def control(self, action, fault=None, active=None):
        if action == 'fault':
            if fault not in FAULTS or type(active) is not bool:
                raise ValueError('Known fault and boolean active required')
            faults = set(self.data['faults'])
            faults.add(fault) if active else faults.discard(fault)
            self.data['faults'] = sorted(faults)
            if active:
                self.data.update(latched=True, enabled=False)
        elif action == 'stop':
            self.data['enabled'] = False
        elif action == 'reset':
            if self.data['faults'] or not self.data['power_available']:
                raise ValueError('Restore unsafe conditions before fault acknowledgement')
            self.data.update(latched=False, enabled=False)
        elif action == 'start':
            if self.data['latched'] or self.data['faults'] or not self.data['power_available']:
                raise ValueError('Restore conditions and acknowledge the latched fault first')
            if not self.data['batch'] or self.data['completed']:
                raise ValueError('A dispatched unfinished batch is required')
            self.data['enabled'] = True
        else:
            raise ValueError('Unknown cell control')

    def power(self, available):
        if type(available) is not bool:
            raise ValueError('Boolean power availability required')
        self.data['power_available'] = available
        if not available:
            self.data.update(latched=True, enabled=False)

    def sensors(self):
        d = self.data
        return {'present': bool(d['batch']) and d['position'] < 4 and 'sensor_failure' not in d['faults'],
                'positioned': bool(d['batch']) and d['position'] == 2 and 'sensor_failure' not in d['faults'],
                'clamped': d['clamped'],
                'processed': bool(d['batch']) and d['progress_seconds'] >= d['batch']['duration_seconds'],
                'exited': bool(d['batch']) and d['position'] >= 4,
                'guard_closed': 'guard_open' not in d['faults'],
                'power_available': d['power_available'] and 'power_loss' not in d['faults'],
                'healthy': not bool(set(d['faults']) & {'sensor_failure', 'conveyor_jam'}),
                'enabled': d['enabled'] and not d['latched'], 'active': bool(d['batch']) and not d['completed']}

    def advance(self, outputs):
        d = self.data
        if not d['batch'] or d['completed'] or not d['enabled'] or d['latched'] or d['faults'] or not d['power_available']:
            return
        d['clamped'] = bool(outputs['clamp']) and d['position'] == 2
        if outputs['conveyor'] and not d['clamped']:
            if d['position'] < 2 or d['progress_seconds'] >= d['batch']['duration_seconds']:
                d['position'] = min(4, d['position'] + 1)
        if outputs['cycle'] and d['clamped']:
            d['progress_seconds'] = min(d['batch']['duration_seconds'], d['progress_seconds'] + 1)
        if d['position'] == 4 and d['progress_seconds'] >= d['batch']['duration_seconds']:
            d.update(completed=True, enabled=False,
                     good_quantity=d['batch']['quantity'] - d['batch']['scrap_quantity'],
                     scrap_quantity=d['batch']['scrap_quantity'])
