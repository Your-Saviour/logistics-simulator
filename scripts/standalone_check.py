#!/usr/bin/env python3
"""Start each application alone, then restore the suite for local review."""
import argparse
import subprocess
from smoke import APPS, check


def compose(app,*args):
    subprocess.run(['docker','compose','-f',f'deploy/generated/{app}.json',*args],check=True)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--restore-suite',action='store_true')
    args=parser.parse_args()
    compose('suite','down')
    try:
        for app in APPS:
            try:
                compose(app,'up','-d','--wait','--wait-timeout','180')
                check(app)
                print(app+': standalone startup without other websites passed',flush=True)
            finally:
                compose(app,'down')
    finally:
        if args.restore_suite:
            compose('suite','up','-d','--wait','--wait-timeout','180')


if __name__=='__main__':
    main()
