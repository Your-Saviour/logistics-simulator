#!/usr/bin/env python3
"""Serialize Docker workloads and stop before exhausting the host disk.

This is host orchestration only. Application installation/builds/tests stay
inside Docker. Read-only Docker inspection and emergency cleanup may run
separately. Use one guarded workload at a time across this repository.
"""
import argparse
import fcntl
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
GIB=1024**3


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--minimum-gib',type=float,default=20)
    parser.add_argument('--label',default='container-workload')
    parser.add_argument('--wait',action='store_true',help='Wait for the shared workload lock rather than exit busy')
    parser.add_argument('command',nargs=argparse.REMAINDER)
    args=parser.parse_args()
    command=args.command[1:] if args.command[:1]==['--'] else args.command
    if not command or Path(command[0]).name!='docker':
        parser.error('Pass a Docker command after --; service work must run in containers')
    if args.minimum_gib<1:
        parser.error('Keep at least 1 GiB in reserve')
    # Linked worktrees share Docker resources and must share the same guard.
    common=Path(subprocess.check_output(['git','rev-parse','--path-format=absolute','--git-common-dir'],cwd=ROOT,text=True).strip())
    state=common.parent/'.superpowers';state.mkdir(exist_ok=True)
    with (state/'container-workload.lock').open('a+') as lock:
        try: fcntl.flock(lock.fileno(),fcntl.LOCK_EX|(0 if args.wait else fcntl.LOCK_NB))
        except BlockingIOError:
            print('Another guarded Docker workload is running; wait for its completion.',file=sys.stderr)
            return 75
        def enough(): return shutil.disk_usage(ROOT).free/GIB>=args.minimum_gib
        def free(): return shutil.disk_usage(ROOT).free/GIB
        if not enough():
            print(f'Not started: {free():.1f} GiB free; reserve is {args.minimum_gib:.1f} GiB.',file=sys.stderr)
            return 75
        print(f'{args.label}: starting with {free():.1f} GiB free; reserve {args.minimum_gib:.1f} GiB.',flush=True)
        process=subprocess.Popen(command,start_new_session=True)
        try:
            while process.poll() is None:
                if not enough():
                    print(f'Stopping {args.label}: disk reserve reached ({free():.1f} GiB free).',file=sys.stderr,flush=True)
                    os.killpg(process.pid,signal.SIGTERM)
                    try: process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid,signal.SIGKILL);process.wait()
                    return 75
                time.sleep(2)
            return process.returncode
        except (KeyboardInterrupt,SystemExit):
            if process.poll() is None:
                os.killpg(process.pid,signal.SIGTERM)
                process.wait(timeout=10)
            raise
        finally:
            print(f'{args.label}: finished with {free():.1f} GiB free.',flush=True)

if __name__=='__main__': sys.exit(main())
