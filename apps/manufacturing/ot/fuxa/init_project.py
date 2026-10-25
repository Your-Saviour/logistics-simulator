"""Seed only an empty FUXA instance; never overwrite an operator-edited project."""
import json
import argparse
import os
from pathlib import Path
import time
import urllib.error
import urllib.request


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--replace-owned-project', action='store_true', help='Explicitly replace an existing SIMU-54-only project after backing it up')
    options = parser.parse_args()
    base = os.environ.get('FUXA_URL', 'http://fuxa:1881')
    headers = {'Content-Type': 'application/json'}
    if os.environ.get('FUXA_ADMIN_TOKEN'):
        headers['Authorization'] = 'Bearer ' + os.environ['FUXA_ADMIN_TOKEN']
    deadline = time.monotonic() + 90
    while True:
        try:
            with urllib.request.urlopen(urllib.request.Request(base + '/api/project', headers=headers), timeout=10) as reply:
                current = json.load(reply)
            break
        except (OSError, urllib.error.URLError):
            if time.monotonic() >= deadline:
                raise
            time.sleep(1)
    views = current.get('hmi', {}).get('views', [])
    owned = views and all(view.get('id') == 'simu54-cell' for view in views)
    if owned and not options.replace_owned_project:
        print('Existing SIMU-54 project preserved')
        return
    if views and not (owned and options.replace_owned_project):
        raise RuntimeError('FUXA project is not empty; import explicitly after backing up existing configuration')
    body = (Path(__file__).resolve().parent / 'project.json').read_bytes()
    try:
        with urllib.request.urlopen(urllib.request.Request(base + '/api/project', data=body, headers=headers), timeout=30) as reply:
            if reply.status != 200:
                raise RuntimeError('FUXA did not accept the project')
    except (TimeoutError, OSError):
        # FUXA can commit/import while its restart response is delayed. Verify before retrying writes.
        with urllib.request.urlopen(urllib.request.Request(base + '/api/project', headers=headers), timeout=10) as reply:
            observed = json.load(reply)
        wanted = json.loads(body)
        expected = wanted['hmi']['views'][0]
        if not any(view.get('id') == expected['id'] and view.get('svgcontent') == expected['svgcontent'] for view in observed.get('hmi', {}).get('views', [])):
            raise RuntimeError('FUXA import result is uncertain; inspect it before retrying')
    print('FUXA accepted the editable Assembly cell project')


if __name__ == '__main__':
    main()
