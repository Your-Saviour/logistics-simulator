#!/bin/sh
# No other departmental app or Twin participates in this domain protocol check.
set -eu
work() { python3 scripts/docker_guard.py --wait --minimum-gib "${SIMULATOR_MINIMUM_FREE_GIB:-20}" --label storage-connected -- docker "$@"; }
mkdir -p .superpowers/sdd/simu-2-storage
python3 scripts/storage_connected_compose.py
manifest=deploy/generated/storage-v1-connected.json
cleanup() { result=$?; trap - EXIT HUP INT TERM; docker compose -f "$manifest" logs --no-color storage-api storage-worker storage-controller storage-adapter warehouse-peer > .superpowers/sdd/simu-2-storage/connected-services.log 2>&1 || true; work compose -f "$manifest" down --volumes || result=1; exit "$result"; }
trap cleanup EXIT HUP INT TERM
work build -t logistics-simulator:adapter -f apps/adapter/Dockerfile .
work compose -f "$manifest" build storage-api
work compose -f "$manifest" up -d storage-db storage-broker warehouse-broker storage-adapter warehouse-peer storage-api storage-worker storage-controller
work compose -f "$manifest" run --rm storage-verify
