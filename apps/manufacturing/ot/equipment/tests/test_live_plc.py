"""Acceptance against the real OpenPLC cell program; never a control emulator."""
import os
import tempfile
import unittest
import uuid
from journal import Engine, RecoveryRequired
from modbus import PLC


@unittest.skipUnless(os.environ.get('PLC_HOST'), 'requires actual OpenPLC with cell.st loaded')
class LivePLCTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = self.directory.name + '/equipment.sqlite'
        self.engine = Engine(self.path, PLC(os.environ['PLC_HOST']))
        self.scope = {key: str(uuid.uuid4()) for key in ['run_id', 'epoch', 'session_id']}
        self.time = 0
        self.send('initialize', {})
        self.send('dispatch', {'order_id': str(uuid.uuid4()), 'correlation_id': str(uuid.uuid4()),
                              'quantity': 20, 'scrap_quantity': 1, 'duration_seconds': 3})
        self.send('control', {'action': 'start'})

    def tearDown(self):
        self.engine.close()
        self.directory.cleanup()

    def send(self, operation, payload):
        return self.engine.command({'version': '1.0', 'command_id': str(uuid.uuid4()),
                                   **self.scope, 'operation': operation, 'payload': payload})['result']

    def step(self):
        self.time += 1
        return self.send('step', {'simulation_time': self.time, 'power_available': True})

    def finish(self):
        for _ in range(20):
            result = self.step()
            if result['completion']:
                self.assertEqual(result['completion']['good_quantity'], 19)
                self.assertEqual(result['completion']['scrap_quantity'], 1)
                return result
        self.fail('Real PLC/equipment did not complete the batch')

    def test_real_plc_batch_and_counter_feedback(self):
        completed = self.finish()
        event = completed['completion']
        for _ in range(3):
            self.assertEqual(self.step()['completion'], event, 'A settled completion fact is immutable')
        stopped = self.send('finalize', {})
        self.assertFalse(stopped['actuators']['conveyor'])
        self.assertFalse(stopped['actuators']['cycle'])
        self.assertTrue(stopped['finalized'])

    def test_real_plc_faults_and_controlled_recovery(self):
        for fault in ['conveyor_jam', 'sensor_failure', 'guard_open', 'power_loss']:
            with self.subTest(fault=fault):
                result = self.send('control', {'action': 'fault', 'fault': fault, 'active': True})
                self.assertTrue(result['actuators']['fault'])
                before = result['cell']
                result = self.step()
                self.assertEqual(before['position'], result['cell']['position'])
                self.assertEqual(before['progress_seconds'], result['cell']['progress_seconds'])
                self.assertFalse(result['actuators']['conveyor'])
                self.send('control', {'action': 'fault', 'fault': fault, 'active': False})
                self.assertTrue(self.engine.status()['cell']['latched'])
                self.send('control', {'action': 'reset'})
                self.send('control', {'action': 'start'})
        self.finish()

    def test_restart_does_not_resume_from_sql_alone(self):
        self.step()
        self.engine.close()
        self.engine = Engine(self.path, PLC(os.environ['PLC_HOST']))
        with self.assertRaises(RecoveryRequired):
            self.step()


if __name__ == '__main__':
    unittest.main()
