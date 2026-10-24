#!/bin/sh
set -eu
case "${ROLE:-api}" in
api) exec gunicorn --workers 2 --threads 4 --bind 0.0.0.0:8000 'twin.api:from_env()' ;;
projection) exec python -m simulator.projection ;;
test) exec pytest -q -p no:cacheprovider tests ;;
*) exec "$@" ;;
esac
