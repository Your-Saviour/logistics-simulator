#!/usr/bin/env python3
"""Bounded full-stack connected test using only disposable test volumes."""
import subprocess
import time
from federation_compose import generate
from smoke import call

COMMAND=['docker','compose','-p','simu-connected-check','-f','deploy/generated/federation.json']


def main():
    generate()
    try:
        subprocess.run(COMMAND+['up','-d','--build','--wait','--wait-timeout','180'],check=True)
        deadline=time.monotonic()+90
        for app in ('manufacturing','storage','logistics','shipping'):
            while True:
                status=call(app,'status')
                assert status['run']['mode']=='helics'
                assert status['run']['state']=='running', status['run']['error']
                if any(j['idempotency_key'].startswith('boundary:') and j['status']=='completed' for j in status['jobs']):
                    break
                if time.monotonic()>deadline:
                    raise AssertionError(app+' did not consume its peer sample')
                time.sleep(.3)
            print(app+': connected peer sample completed at grant '+str(status['run']['granted']),flush=True)
    finally:
        subprocess.run(COMMAND+['down','--volumes'],check=True)


if __name__=='__main__':
    main()
