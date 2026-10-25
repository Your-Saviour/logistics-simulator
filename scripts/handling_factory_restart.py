"""Host-side process control; the verifier never receives a Docker socket."""
import json
from pathlib import Path
import subprocess
import sys
import time


def main():
    manifest, artifacts = sys.argv[1:]
    project = json.loads(Path(manifest).read_text())['name']
    verifier = project + '-restart-verifier'
    compose = ['compose', '-f', manifest]

    def work(*args):
        subprocess.run([sys.executable, 'scripts/docker_guard.py', '--wait', '--label', 'handling-factory-restart', '--', 'docker', *args], check=True)

    def inspect(name):
        return json.loads(subprocess.check_output(['docker', 'inspect', name], text=True))[0]

    workers = {}
    for app in ('logistics', 'storage'):
        workers[app] = subprocess.check_output(['docker', *compose, 'ps', '-q', app + '-worker'], text=True).strip()
        assert workers[app], app + ' worker is missing'
    work(*compose, 'run', '-d', '--no-deps', '--name', verifier, 'verify')
    deadline = time.monotonic() + 600
    completed = set()
    while True:
        state = inspect(verifier)['State']
        if not state['Running']:
            subprocess.run(['docker', 'logs', verifier], check=True)
            assert state['ExitCode'] == 0, state
            assert completed == {'accepted', 'received', 'acknowledged'}, completed
            return
        assert time.monotonic() < deadline, 'Factory restart acceptance timed out'
        for stage in ('accepted', 'received', 'acknowledged'):
            request = Path(artifacts) / ('restart-' + stage + '.request')
            if stage in completed or not request.exists():
                continue
            assert not request.with_suffix('.ack').exists(), 'Stale restart acknowledgement'
            before = {app: inspect(identity)['State']['StartedAt'] for app, identity in workers.items()}
            work(*compose, 'restart', 'logistics-worker', 'storage-worker')
            evidence = {}
            for app, identity in workers.items():
                after = inspect(identity)['State']
                assert after['Running'] and before[app] != after['StartedAt'], (app, after)
                evidence[app] = {'before': before[app], 'after': after['StartedAt'], 'running': after['Running']}
            request.with_suffix('.ack').write_text(json.dumps(evidence, indent=2))
            completed.add(stage)
        time.sleep(.2)


if __name__ == '__main__':
    main()
