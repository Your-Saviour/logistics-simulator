import tempfile
import unittest
import uuid
from journal import Engine, Conflict, RecoveryRequired


class PLC:
    def __init__(self):
        self.calls = []
        self.fail = False

    def exchange(self, sequence, inputs, expected_sequence, cookie, reset=False):
        self.calls.append((sequence, inputs, expected_sequence, cookie, reset))
        if self.fail:
            raise OSError('PLC disconnected')
        return {'ack_sequence': sequence, 'cookie': cookie, 'conveyor': False,
                'clamp': False, 'cycle': False, 'fault': False,
                'good_quantity': 0, 'scrap_quantity': 0}


class ProtocolTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = self.directory.name + '/journal.sqlite'
        self.plc = PLC()
        self.engine = Engine(self.path, self.plc)
        self.scope = {key: str(uuid.uuid4()) for key in ('run_id', 'epoch', 'session_id')}
        self.send('initialize', {})

    def tearDown(self):
        self.engine.close()
        self.directory.cleanup()

    def body(self, operation, payload):
        return {'version': '1.0', 'command_id': str(uuid.uuid4()), **self.scope,
                'operation': operation, 'payload': payload}

    def send(self, operation, payload):
        return self.engine.command(self.body(operation, payload))

    def test_identical_step_replay_does_not_touch_plc_or_advance_twice(self):
        request = self.body('step', {'simulation_time': 1, 'power_available': True})
        reply = self.engine.command(request)
        calls = len(self.plc.calls)
        self.assertEqual(self.engine.command(request), reply)
        self.assertEqual(len(self.plc.calls), calls)
        self.assertEqual(self.engine.status()['simulation_time'], 1)
        conflict = {**request, 'payload': {'simulation_time': 2, 'power_available': True}}
        with self.assertRaises(Conflict):
            self.engine.command(conflict)

    def test_stale_scope_and_ungranted_jump_rejected_before_io(self):
        request = self.body('step', {'simulation_time': 1, 'power_available': True})
        request['epoch'] = str(uuid.uuid4())
        calls = len(self.plc.calls)
        with self.assertRaises(Conflict):
            self.engine.command(request)
        with self.assertRaises(ValueError):
            self.send('step', {'simulation_time': 2, 'power_available': True})
        self.assertEqual(len(self.plc.calls), calls)

    def test_restart_requires_reconciliation_not_silent_resume(self):
        self.send('step', {'simulation_time': 1, 'power_available': True})
        self.engine.close()
        self.engine = Engine(self.path, self.plc)
        self.assertTrue(self.engine.status()['recovery_required'])
        with self.assertRaises(RecoveryRequired):
            self.send('step', {'simulation_time': 2, 'power_available': True})

    def test_unknown_plc_state_does_not_commit_progress(self):
        self.plc.fail = True
        with self.assertRaises(OSError):
            self.send('step', {'simulation_time': 1, 'power_available': True})
        self.assertEqual(self.engine.status()['simulation_time'], 0)

    def test_old_receipts_cannot_reopen_an_archived_epoch(self):
        old_request = self.body('control', {'action': 'stop'})
        self.engine.command(old_request)
        self.scope = {key: str(uuid.uuid4()) for key in self.scope}
        self.send('initialize', {})
        with self.assertRaises(Conflict):
            self.engine.command(old_request)

    def test_strict_types_unknown_fields_and_versions(self):
        for payload in [{'simulation_time': True, 'power_available': True},
                        {'simulation_time': 1, 'power_available': 1},
                        {'simulation_time': 1, 'power_available': True, 'extra': 0}]:
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                self.send('step', payload)
        request = self.body('step', {'simulation_time': 1, 'power_available': True})
        request['version'] = '2.0'
        with self.assertRaises(ValueError):
            self.engine.command(request)

    def test_rejected_control_keeps_its_outcome_after_conditions_change(self):
        self.send('control', {'action': 'fault', 'fault': 'guard_open', 'active': True})
        request = self.body('control', {'action': 'reset'})
        with self.assertRaises(ValueError):
            self.engine.command(request)
        self.send('control', {'action': 'fault', 'fault': 'guard_open', 'active': False})
        with self.assertRaises(ValueError):
            self.engine.command(request)
        self.send('control', {'action': 'reset'})  # A deliberate new identity may now reset.


if __name__ == '__main__':
    unittest.main()

class SnapshotTest(unittest.TestCase):
    def test_scan_ack_race_retries_until_a_consistent_output_snapshot(self):
        from modbus import PLC as RealPLC
        full = [1, 0, 0, 0, 0, 0, 0, 0, 11, 12, 13, 14]
        class Transport:
            def __init__(self):
                self.replies = iter([[0], full, [1], [1], full, [1]])
            def read(self, _address, _count):
                return next(self.replies)
        plc = RealPLC('unused')
        plc.transport = Transport()
        self.assertEqual(plc.read()['ack_sequence'], 1)
