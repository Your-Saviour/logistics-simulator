import unittest
from model import Cell


class CellTest(unittest.TestCase):
    def batch(self):
        cell = Cell()
        cell.dispatch({'order_id': 'order', 'correlation_id': 'correlation', 'quantity': 20,
                       'scrap_quantity': 1, 'duration_seconds': 3})
        cell.control('start')
        return cell

    def test_no_progress_without_actual_actuators(self):
        cell = self.batch()
        before = cell.snapshot()
        cell.advance({'conveyor': False, 'clamp': False, 'cycle': False})
        self.assertEqual(cell.snapshot()['position'], before['position'])
        self.assertEqual(cell.snapshot()['progress_seconds'], 0)
        self.assertFalse(cell.snapshot()['completed'])

    def test_full_feedback_loop_and_batch_counters(self):
        cell = self.batch()
        for _ in range(2):
            cell.advance({'conveyor': True, 'clamp': False, 'cycle': False})
        self.assertTrue(cell.sensors()['positioned'])
        cell.advance({'conveyor': False, 'clamp': True, 'cycle': False})
        self.assertTrue(cell.sensors()['clamped'])
        for _ in range(3):
            cell.advance({'conveyor': False, 'clamp': True, 'cycle': True})
        self.assertTrue(cell.sensors()['processed'])
        cell.advance({'conveyor': False, 'clamp': False, 'cycle': False})
        for _ in range(2):
            cell.advance({'conveyor': True, 'clamp': False, 'cycle': False})
        self.assertTrue(cell.snapshot()['completed'])
        self.assertEqual(cell.snapshot()['good_quantity'], 19)
        self.assertEqual(cell.snapshot()['scrap_quantity'], 1)
        cell.advance({'conveyor': True, 'clamp': True, 'cycle': True})
        self.assertEqual(cell.snapshot()['good_quantity'], 19)

    def test_all_faults_latch_and_require_restoration_reset_start(self):
        for fault in ['conveyor_jam', 'sensor_failure', 'guard_open', 'power_loss']:
            with self.subTest(fault=fault):
                cell = self.batch()
                cell.control('fault', fault, True)
                before = cell.snapshot()['position']
                cell.advance({'conveyor': True, 'clamp': True, 'cycle': True})
                self.assertEqual(cell.snapshot()['position'], before)
                with self.assertRaises(ValueError):
                    cell.control('reset')
                cell.control('fault', fault, False)
                with self.assertRaises(ValueError):
                    cell.control('start')
                cell.control('reset')
                self.assertFalse(cell.snapshot()['enabled'])
                cell.control('start')
                self.assertTrue(cell.snapshot()['enabled'])

    def test_stop_preserves_consumed_batch_and_progress(self):
        cell = self.batch()
        cell.advance({'conveyor': True, 'clamp': False, 'cycle': False})
        cell.control('stop')
        cell.advance({'conveyor': True, 'clamp': True, 'cycle': True})
        self.assertEqual(cell.snapshot()['position'], 1)
        self.assertEqual(cell.snapshot()['batch']['order_id'], 'order')
        cell.control('start')
        self.assertTrue(cell.snapshot()['enabled'])

    def test_second_batch_cannot_replace_active_batch(self):
        cell = self.batch()
        with self.assertRaises(ValueError):
            cell.dispatch({'order_id': 'another', 'quantity': 1, 'scrap_quantity': 0, 'duration_seconds': 1})


if __name__ == '__main__':
    unittest.main()
