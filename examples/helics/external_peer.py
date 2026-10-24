"""Small independent power peer, replaceable by an external simulator."""
import os
import signal
import time
from simulator.clocks import HelicsClock
from simulator.federation_config import config


def main():
    stop=False
    def stopping(*_):
        nonlocal stop
        stop=True
    signal.signal(signal.SIGTERM,stopping)
    clock=HelicsClock(config('external-power',os.getenv('HELICS_BROKER','tcp://helics-broker:24900'),power=True))
    try:
        clock.initialize()
        while not clock.initialized():
            if stop:
                return
            time.sleep(.05)
        clock.publish_value(float(os.getenv('AVAILABLE_POWER_KW','25')))
        target=1
        # Delayed requests demonstrate that participants cannot process future
        # work just because wall time passed. This is a pacing example only.
        delay=float(os.getenv('PEER_DELAY_SECONDS','0.2'))
        while not stop:
            time.sleep(delay)
            clock.request(target)
            granted=None
            while granted is None and not stop:
                granted=clock.poll()
                time.sleep(.02)
            if granted is not None:
                target=granted+1
                clock.publish_value(float(os.getenv('AVAILABLE_POWER_KW','25')))
    finally:
        clock.finalize()


if __name__=='__main__':
    main()
