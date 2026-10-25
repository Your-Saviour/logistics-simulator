"""Private authenticated gateway ledger; no manufacturing SQL or HELICS access."""
import copy
import hashlib
import json
import sqlite3
import threading
import time
import uuid
from model import Cell


class Conflict(ValueError):
    pass


class RecoveryRequired(Conflict):
    pass


def fields(value, allowed, required=None):
    if not isinstance(value, dict) or set(value) - set(allowed) or not set(required or []) <= set(value):
        raise ValueError('Invalid or missing fields')


def identity(value):
    if not isinstance(value, str) or str(uuid.UUID(value)) != value.lower():
        raise ValueError('Canonical UUID required')
    return value


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


class Engine:
    def __init__(self, path, plc):
        self.plc = plc
        self.lock = threading.RLock()
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.executescript('''CREATE TABLE IF NOT EXISTS state (id INTEGER PRIMARY KEY CHECK(id=1), value TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS receipts (id TEXT PRIMARY KEY, request TEXT NOT NULL, response TEXT);
          CREATE TABLE IF NOT EXISTS scopes (epoch TEXT PRIMARY KEY);''')
        row = self.db.execute('SELECT value FROM state WHERE id=1').fetchone()
        self.state = json.loads(row[0]) if row else None
        self.recovery = row is not None

    def close(self):
        self.db.close()

    def status(self, observe=False):
        with self.lock:
            result = copy.deepcopy(self.state) if self.state else {'initialized': False, 'simulation_time': 0}
            result['recovery_required'] = self.recovery
            if observe and self.state and not self.recovery:
                try:
                    result['actuators'] = self.plc.observe(self.state['sequence'], self.state['cookie'])
                    result['observed_at'] = time.time()
                    result['connected'] = True
                except Conflict:
                    self.recovery = True
                    result.update(connected=False, recovery_required=True)
                except OSError:
                    result['connected'] = False
            result['version'] = '1.0'
            return result

    def command(self, request):
        with self.lock:
            fields(request, ['version', 'command_id', 'run_id', 'epoch', 'session_id', 'operation', 'payload'],
                   ['version', 'command_id', 'run_id', 'epoch', 'session_id', 'operation', 'payload'])
            if request['version'] != '1.0':
                raise ValueError('Unsupported equipment contract version')
            for key in ['command_id', 'run_id', 'epoch', 'session_id']:
                identity(request[key])
            scope = {key: request[key] for key in ['run_id', 'epoch', 'session_id']}
            operation, payload = request['operation'], request['payload']
            if operation not in ['initialize', 'dispatch', 'step', 'control', 'finalize']:
                raise ValueError('Unknown operation')
            old_scope = self.state and self.state['scope']
            if operation != 'initialize' and scope != old_scope:
                raise Conflict('Stale run, epoch or controller session')
            if operation == 'initialize' and old_scope != scope:
                if self.db.execute('SELECT 1 FROM scopes WHERE epoch=?', (scope['epoch'],)).fetchone():
                    raise Conflict('Archived epoch cannot acquire equipment again')
            encoded = canonical(request)
            prior = self.db.execute('SELECT request,response FROM receipts WHERE id=?', (request['command_id'],)).fetchone()
            if prior:
                if prior[0] != encoded:
                    raise Conflict('Command identity conflicts with prior body')
                if prior[1] is not None:
                    saved = json.loads(prior[1])
                    if 'error' in saved:
                        raise ValueError(saved['error'])
                    return saved
            if self.recovery and (operation != 'initialize' or old_scope == scope):
                raise RecoveryRequired('Equipment restart requires controlled recovery in a new epoch')
            if operation == 'initialize' and old_scope == scope:
                raise Conflict('Equipment scope already initialized')
            state = copy.deepcopy(self.state)
            reset = operation == 'initialize'
            if reset:
                fields(payload, [])
                cookie = list(int.from_bytes(hashlib.sha256(canonical(scope).encode()).digest()[i:i+2], 'big') for i in range(0, 8, 2))
                state = {'initialized': True, 'scope': scope, 'simulation_time': 0, 'sequence': 0,
                         'cookie': cookie, 'batch_number': 0, 'cell': Cell().snapshot(), 'finalized': False}
            elif state['finalized']:
                raise Conflict('Equipment already finalized')
            cell = Cell(state['cell'])
            if operation == 'dispatch':
                fields(payload, ['order_id', 'correlation_id', 'quantity', 'scrap_quantity', 'duration_seconds'],
                       ['order_id', 'correlation_id', 'quantity', 'scrap_quantity', 'duration_seconds'])
                identity(payload['order_id']); identity(payload['correlation_id'])
                cell.dispatch(payload)
                state['batch_number'] += 1
            elif operation == 'control':
                fields(payload, ['action', 'fault', 'active'], ['action'])
                if payload['action'] != 'fault' and set(payload) != {'action'}:
                    raise ValueError('Fault fields require fault action')
                try:
                    cell.control(payload['action'], payload.get('fault'), payload.get('active'))
                except ValueError as error:
                    with self.db:
                        self.db.execute('INSERT OR REPLACE INTO receipts(id,request,response) VALUES (?,?,?)',
                                        (request['command_id'], encoded, canonical({'error': str(error)})))
                    raise
            elif operation == 'step':
                fields(payload, ['simulation_time', 'power_available'], ['simulation_time', 'power_available'])
                if type(payload['simulation_time']) is not int or payload['simulation_time'] != state['simulation_time'] + 1:
                    raise ValueError('Exactly the next granted one-second step required')
                cell.power(payload['power_available'])
            elif operation == 'finalize':
                fields(payload, [])
                cell.control('stop')
                state['finalized'] = True
            if state['sequence'] >= 65535 or state['batch_number'] >= 65535:
                raise RecoveryRequired('PLC sequence exhausted; controlled new epoch required')
            # Committed intent survives a lost reply; never hold SQLite over PLC I/O.
            if not prior:
                with self.db:
                    self.db.execute('INSERT INTO receipts(id,request) VALUES (?,?)', (request['command_id'], encoded))
            sequence = state['sequence'] + 1
            sensors = cell.sensors()
            batch = cell.data['batch']
            inputs = {**sensors, 'batch_number': state['batch_number'],
                      'good_quantity': batch['quantity'] - batch['scrap_quantity'] if batch else 0,
                      'scrap_quantity': batch['scrap_quantity'] if batch else 0,
                      'reset_fault': operation == 'control' and payload['action'] == 'reset'}
            try:
                outputs = self.plc.exchange(sequence, inputs, state['sequence'], state['cookie'], reset=reset)
            except Conflict:
                self.recovery = True
                raise
            if outputs.get('ack_sequence') != sequence or outputs.get('cookie') != state['cookie']:
                self.recovery = True
                raise RecoveryRequired('Unproven PLC acknowledgement')
            if operation == 'step':
                cell.advance(outputs)
                state['simulation_time'] = payload['simulation_time']
            state.update(sequence=sequence, cell=cell.snapshot(), actuators=outputs, observed_at=time.time())
            if operation == 'dispatch' or 'completion' not in state:
                state['completion'] = None
            if state['completion'] is None and cell.data['completed'] and outputs.get('good_quantity') == cell.data['good_quantity'] and outputs.get('scrap_quantity') == cell.data['scrap_quantity']:
                state['completion'] = {'version': '1.0', 'event_id': str(uuid.uuid5(uuid.UUID(batch['order_id']), 'ot.completed')),
                    **scope, 'order_id': batch['order_id'], 'correlation_id': batch['correlation_id'],
                    'simulation_time': state['simulation_time'], 'quantity': batch['quantity'],
                    'good_quantity': cell.data['good_quantity'], 'scrap_quantity': cell.data['scrap_quantity']}
            response = {'version': '1.0', 'command_id': request['command_id'], 'result': state}
            with self.db:
                if reset:
                    self.db.execute('INSERT INTO scopes(epoch) VALUES (?)', (scope['epoch'],))
                self.db.execute('INSERT OR REPLACE INTO state(id,value) VALUES (1,?)', (canonical(state),))
                self.db.execute('UPDATE receipts SET response=? WHERE id=?', (canonical(response), request['command_id']))
            self.state, self.recovery = state, False
            return response
