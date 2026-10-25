"""Strict Modbus TCP transport and scan-acknowledged PLC exchange."""
import socket
import struct
import time


class Modbus:
    def __init__(self, host, port=502):
        self.host, self.port, self.transaction = host, port, 0

    def request(self, function, body):
        # MBAP correlation is a 16-bit transport ID, independent of the durable
        # logical-step sequence. Each request owns its connection, so reuse is safe.
        self.transaction = (self.transaction + 1) & 0xffff
        packet = bytes([function]) + body
        with socket.create_connection((self.host, self.port), timeout=3) as connection:
            connection.settimeout(3)
            connection.sendall(struct.pack('>HHHB', self.transaction, 0, len(packet) + 1, 1) + packet)
            def receive(length):
                data = b''
                while len(data) < length:
                    part = connection.recv(length - len(data))
                    if not part:
                        raise ConnectionError('PLC closed an incomplete response')
                    data += part
                return data
            tid, protocol, length, unit = struct.unpack('>HHHB', receive(7))
            if (tid, protocol, unit) != (self.transaction, 0, 1) or not 2 <= length <= 254:
                raise ValueError('Invalid Modbus response header')
            result = receive(length - 1)
            if result[0] != function:
                raise ValueError(f'Modbus exception or wrong function: {result.hex()}')
            return result[1:]

    def read(self, address, count):
        result = self.request(3, struct.pack('>HH', address, count))
        if len(result) != 1 + count * 2 or result[0] != count * 2:
            raise ValueError('Invalid Modbus register response')
        return list(struct.unpack('>' + 'H' * count, result[1:]))

    def write(self, address, values):
        header = struct.pack('>HH', address, len(values))
        body = header + bytes([len(values) * 2]) + struct.pack('>' + 'H' * len(values), *values)
        if self.request(16, body) != header:
            raise ValueError('Invalid Modbus write echo')



class PLC:
    def __init__(self, host, port=502):
        self.transport = Modbus(host, port)

    def read(self):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            before = self.transport.read(0, 1)[0]
            result = self.transport.read(0, 12)
            after = self.transport.read(0, 1)[0]
            if before == result[0] == after:
                return {'ack_sequence': result[0], 'conveyor': bool(result[1]),
                        'clamp': bool(result[2]), 'cycle': bool(result[3]), 'fault': bool(result[4]),
                        'good_quantity': result[5], 'scrap_quantity': result[6],
                        'batch_number': result[7], 'cookie': result[8:12]}
            time.sleep(0.01)
        raise OSError('PLC outputs did not settle into a consistent snapshot')

    def observe(self, sequence, cookie):
        from journal import RecoveryRequired
        result = self.read()
        if result['ack_sequence'] != sequence or result['cookie'] != cookie:
            raise RecoveryRequired('PLC restart or foreign sequence/cookie; reconciliation required')
        return result

    def exchange(self, sequence, inputs, expected_sequence, cookie, reset=False):
        from journal import RecoveryRequired
        previous = self.read()
        if previous['ack_sequence'] == sequence and previous['cookie'] == cookie:
            return previous  # Same-process lost reply: consume that acknowledged result once.
        if not reset and (previous['ack_sequence'] != expected_sequence or previous['cookie'] != cookie):
            raise RecoveryRequired('PLC state no longer matches the journal')
        # Never overwrite a commit marker with data; verify every data register first.
        words = [int(inputs['enabled']), int(inputs['guard_closed']), int(inputs['power_available']),
                 previous['ack_sequence'], int(inputs['positioned']), int(inputs['clamped']),
                 int(inputs['processed']), int(inputs['exited']), int(inputs['healthy']),
                 inputs['batch_number'], inputs['good_quantity'], inputs['scrap_quantity'],
                 int(inputs['reset_fault']), int(inputs['active']), *cookie, int(reset)]
        if reset and previous['ack_sequence'] == sequence:
            # A different scope may share a 16-bit sequence. Stop/reset at a distinct marker first.
            intermediate = 0 if sequence != 0 else 65535
            self._write_and_wait(intermediate, words)
        return self._write_and_wait(sequence, words)

    def _write_and_wait(self, sequence, words):
        words = list(words)
        self.transport.write(1024, words[:3])
        self.transport.write(1028, words[4:])
        deadline = time.monotonic() + 5
        while True:
            observed = self.transport.read(1024, len(words))
            if observed[:3] == words[:3] and observed[4:] == words[4:]:
                break
            if time.monotonic() >= deadline:
                raise OSError('PLC input snapshot did not settle')
            time.sleep(0.01)
        self.transport.write(1027, [sequence])
        while time.monotonic() < deadline:
            result = self.read()
            if result['ack_sequence'] == sequence and result['cookie'] == words[14:18]:
                return result
            time.sleep(0.01)
        raise OSError('PLC did not acknowledge the committed logical step')
