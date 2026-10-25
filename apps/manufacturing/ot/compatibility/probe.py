"""Real OpenPLC Modbus step-handshake acceptance; Python standard library only.

Run inside Docker on the private compatibility network. No PLC emulator fallback.
"""
import os
import socket
import struct
import time


class Modbus:
    def __init__(self, host, port=502):
        self.host, self.port, self.transaction = host, port, 0

    def request(self, function, body):
        self.transaction += 1
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


def acknowledged(plc, sequence, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = plc.read(0, 4)
        if result[0] == sequence:
            return result
        time.sleep(0.02)
    raise AssertionError(f'PLC did not acknowledge logical step {sequence}')


def main():
    plc = Modbus(os.environ.get('PLC_HOST', 'openplc'), int(os.environ.get('PLC_PORT', '502')))
    # Dedicated unloaded/initialised compatibility cell only; no live deployment.
    assert plc.read(0, 4) == [0, 0, 0, 0], 'Compatibility PLC must start from a clean program state'
    for sequence in range(1, 101):
        # %MW0..3: enable, guard, power, sequence (commit marker written separately).
        plc.write(1024, [1, 1, 1])
        plc.write(1027, [sequence])
        result = acknowledged(plc, sequence)
        assert result == [sequence, sequence, 1, 0], result
        plc.write(1027, [sequence])
        time.sleep(0.05)
        assert plc.read(0, 4) == result, 'Duplicate sequence advanced PLC control state'
    time.sleep(0.2)
    assert plc.read(0, 4)[1] == 100, 'Extra scans advanced logical time'
    # Guard and power inhibit output while still settling a paused step.
    for sequence, inputs in [(101, [1, 0, 1]), (102, [1, 1, 0]), (103, [0, 1, 1])]:
        plc.write(1024, inputs)
        # Permit inputs to reach the scan image before publishing the commit marker.
        time.sleep(0.05)
        plc.write(1027, [sequence])
        assert acknowledged(plc, sequence) == [sequence, 100, 0, 1]
    print('PASS: 100 logical steps, duplicate replay, extra scans, guard/power/stop interlocks')


if __name__ == '__main__':
    main()
