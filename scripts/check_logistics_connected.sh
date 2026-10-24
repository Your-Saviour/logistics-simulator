#!/bin/sh
set -eu
work() { python3 scripts/docker_guard.py --wait --minimum-gib "${SIMULATOR_MINIMUM_FREE_GIB:-20}" --label logistics-connected -- docker "$@"; }
manifest=deploy/generated/logistics-v1-connected.json
prefix=simu4-connected-$(date +%s)
project=$prefix-orderly
scenario=orderly
mkdir -p .superpowers/sdd/2026-10-24-simu-4-logistics-v1
cleanup() {
 docker compose -p "$project" -f "$manifest" logs --no-color logistics-worker logistics-controller logistics-adapter transport-peer > ".superpowers/sdd/2026-10-24-simu-4-logistics-v1/connected-services-$scenario.log"
 docker compose -p "$project" -f "$manifest" down
}
trap cleanup EXIT HUP INT TERM
work build -t logistics-simulator:logistics-v1-adapter -f apps/adapter/Dockerfile .
for scenario in orderly loss; do
 project=$prefix-$scenario
 if [ "$scenario" = loss ]; then LOGISTICS_PEER_LOSS=true python3 scripts/logistics_connected_compose.py; else python3 scripts/logistics_connected_compose.py; fi
 if [ "$scenario" = orderly ]; then work compose -p "$project" -f "$manifest" build logistics-api; fi
 work compose -p "$project" -f "$manifest" up -d logistics-db logistics-broker transport-broker logistics-adapter transport-peer logistics-api logistics-worker logistics-controller
 work compose -p "$project" -f "$manifest" run --rm logistics-verify
 cleanup
done
trap - EXIT HUP INT TERM
