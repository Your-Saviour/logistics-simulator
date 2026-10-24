#!/bin/sh
set -eu
mkdir -p .superpowers/sdd/simu-3
work() { python3 scripts/docker_guard.py --minimum-gib "${SIMULATOR_MINIMUM_FREE_GIB:-20}" --label manufacturing-connected -- docker "$@"; }
python3 scripts/manufacturing_connected_compose.py
manifest=deploy/generated/manufacturing-v1-connected.json
cleanup() { docker compose -f "$manifest" logs --no-color > .superpowers/sdd/simu-3/connected-services.log; docker compose -f "$manifest" down --volumes; }
trap cleanup EXIT HUP INT TERM
if [ "${STACK_REUSE_IMAGES:-0}" != 1 ]; then
 work build -t logistics-simulator:adapter -f apps/adapter/Dockerfile .
 work compose -f "$manifest" build manufacturing-api
fi
work compose -f "$manifest" up -d manufacturing-db manufacturing-broker factory-broker factory-peer manufacturing-adapter manufacturing-api manufacturing-worker manufacturing-controller
work compose -f "$manifest" run --rm manufacturing-verify
