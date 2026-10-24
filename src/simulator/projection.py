"""Optional independent twin read model; absent sources are explicit."""
import json
import logging
import os
import signal
import time

import httpx
import psycopg

from .config import Settings
from .store import Store


def main():
    logging.basicConfig(level=logging.INFO)
    settings = Settings.from_env()
    store = Store(settings.database_url)
    store.migrate()
    sources = json.loads(os.getenv('TWIN_SOURCES', '[]'))
    stopping = False

    def stop(*_):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    with httpx.Client(timeout=3) as client:
        while not stopping:
            try:
                for source in sources:
                    try:
                        response = client.get(source['url'].rstrip('/') + '/api/status', auth=(source['username'], source['password']))
                        response.raise_for_status()
                        value = response.json()
                        if value['application'] != source['name']:
                            raise ValueError('Configured source identity mismatch')
                        store.project(source['name'], value)
                    except (httpx.HTTPError, ValueError, KeyError):
                        store.project(source['name'], error='Source unavailable or identity mismatch')
                store.heartbeat('projection')
            except psycopg.Error:
                logging.exception('Projection database unavailable')
            time.sleep(1)


if __name__ == '__main__':
    main()
