#!/usr/bin/env python3
"""Reproduce the pinned, network-isolated OFacT domain example evaluation."""
from pathlib import Path
import subprocess
import tempfile

ROOT=Path(__file__).resolve().parents[1]
REVISION='45d044da62e7e3f993845c41b37471ea16bb2771'


def main():
    with tempfile.TemporaryDirectory(prefix='simu-ofact-') as workspace:
        source=Path(workspace)/'ofact'
        subprocess.run(['git','clone','--no-checkout','https://github.com/OpenFactoryTwin/ofact.git',str(source)],check=True)
        subprocess.run(['git','-C',str(source),'checkout','--detach',REVISION],check=True)
        subprocess.run(['docker','build','-f',str(ROOT/'tools/ofact/Dockerfile'),'-t','simu-ofact-spike:45d044d',str(source)],check=True)
        subprocess.run(['docker','run','--rm','-i','--network','none','--memory','1g','--cpus','2','--workdir','/ofact/projects/tutorial','simu-ofact-spike:45d044d','python','-'],
                       input=(ROOT/'tools/ofact/run_example.py').read_text(),text=True,check=True,timeout=90)


if __name__=='__main__':
    main()
