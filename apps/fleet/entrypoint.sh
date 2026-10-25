#!/bin/sh
set -eu
case "${ROLE:-command}" in
  api) exec gunicorn --workers 2 --threads 4 --bind 0.0.0.0:8000 'fleet.api:from_env()' ;;
  worker) exec python -m fleet.worker ;;
  initialize) exec python -m fleet.initialize ;;
  *) exec "$@" ;;
esac
