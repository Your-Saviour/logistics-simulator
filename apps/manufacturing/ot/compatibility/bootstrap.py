"""Upload the compiled probe only to the isolated compatibility PLC."""
import io
import os
import json
from pathlib import Path
import ssl
import time
import urllib.error
import urllib.request
import zipfile
from program_artifact import record, verify

BASE = os.environ.get('PLC_URL', 'https://openplc:8443')
# Disposable private-network probe: runtime generates its own self-signed certificate.
CONTEXT = ssl._create_unverified_context()


def request(path, body=None, token=None, content_type='application/json'):
    headers = {'Content-Type': content_type}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    if isinstance(body, dict):
        body = json.dumps(body).encode()
    req = urllib.request.Request(BASE + path, data=body, headers=headers)
    with urllib.request.urlopen(req, context=CONTEXT, timeout=60) as response:
        return json.load(response)


def main():
    deadline = time.monotonic() + 90
    while True:
        try:
            request('/api/version')
            break
        except (OSError, urllib.error.URLError):
            if time.monotonic() >= deadline:
                raise
            time.sleep(1)
    credentials = {'username': os.environ.get('PLC_USERNAME', 'compatibility'), 'password': os.environ.get('PLC_PASSWORD', 'isolated-compatibility-only')}
    try:
        token = request('/api/login', credentials)['access_token']
    except urllib.error.HTTPError as error:
        if error.code != 401:
            raise
        request('/api/create-user', {**credentials, 'role': 'admin'})
        token = request('/api/login', credentials)['access_token']
    state = request('/api/status', token=token).get('status', '').strip().split(':')[-1].upper()
    build = os.environ.get('PLC_BUILD')
    if build and verify('/generated', build):
        if state != 'RUNNING':
            raise RuntimeError('Known PLC program is stopped; supervised recovery required')
        print('Verified persistent PLC program preserved')
        return
    if state not in {'EMPTY', 'STOPPED', 'ERROR'}:
        raise RuntimeError('Cold runtime required for program upload; live replacement is disabled: ' + state)
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(Path('/generated').rglob('*')):
            if path.is_file() and path.name != 'compiler-package-lock.json':
                archive.write(path, path.relative_to('/generated').as_posix())
    boundary = 'simu54compatibilityupload'
    body = ('--' + boundary + '\r\nContent-Disposition: form-data; name="file"; filename="program.zip"\r\nContent-Type: application/zip\r\n\r\n').encode() + payload.getvalue() + ('\r\n--' + boundary + '--\r\n').encode()
    request('/api/upload-file', body, token, 'multipart/form-data; boundary=' + boundary)
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        status = request('/api/compilation-status', token=token)
        if status.get('status') == 'FAILED':
            raise RuntimeError(json.dumps(status))
        if status.get('status') == 'SUCCESS':
            print('Real runtime compiled uploaded IEC program')
            started = request('/api/start-plc', token=token)
            if started.get('status', '').strip() != 'START:OK':
                raise RuntimeError('PLC did not acknowledge execution: ' + str(started))
            if build:
                record('/generated', build)
            print('PLC acknowledged execution')
            return
        time.sleep(1)
    raise TimeoutError('Real runtime compilation did not complete')


if __name__ == '__main__':
    main()
