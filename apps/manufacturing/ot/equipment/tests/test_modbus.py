import struct
import unittest
from unittest.mock import patch
from modbus import Modbus


class Connection:
    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def settimeout(self, _):
        pass

    def sendall(self, packet):
        self.transaction = struct.unpack('>H', packet[:2])[0]
        self.response = struct.pack('>HHHB', self.transaction, 0, 5, 1) + bytes([3, 2, 0, 7])

    def recv(self, length):
        result, self.response = self.response[:length], self.response[length:]
        return result


class ModbusTest(unittest.TestCase):
    def test_transport_transaction_wraps_without_changing_logical_sequence(self):
        transport = Modbus('plc')
        transport.transaction = 65534
        connection = Connection()
        with patch('modbus.socket.create_connection', return_value=connection):
            for expected in [65535, 0, 1]:
                self.assertEqual(transport.read(0, 1), [7])
                self.assertEqual(connection.transaction, expected)
