#!/bin/sh
# Disposable mixed-language HELICS scenarios, all service work inside Docker.
set -eu
work() { python3 scripts/docker_guard.py --wait --minimum-gib "${SIMULATOR_MINIMUM_FREE_GIB:-20}" --label mixed-federation -- docker "$@"; }
python3 scripts/stacks_compose.py --connected
manifest=deploy/generated/migration-mixed.json
prefix=simu-mixed-check-$(date +%s)
project=$prefix-orderly
cleanup() {
 check_status=$?
 if [ "$check_status" -ne 0 ]; then
  docker compose -p "$project" -f "$manifest" ps -a
  docker compose -p "$project" -f "$manifest" logs --tail 100
 fi
 docker compose -p "$project" -f "$manifest" down --volumes
}
trap cleanup EXIT HUP INT TERM
if [ "${STACK_REUSE_IMAGES:-0}" != 1 ]; then
 work build -t logistics-simulator:bootstrap .
 work build -t logistics-simulator:adapter -f apps/adapter/Dockerfile .
 work run --rm --memory=768m logistics-simulator:adapter sh -c 'pytest -q tests/adapter && python examples/helics/adapter_smoke.py'
fi
if [ "${STACK_REUSE_IMAGES:-0}" != 1 ]; then
for app in storage manufacturing logistics shipping twin; do
 work compose -p "$project" -f "$manifest" build "$app-api"
 work builder prune --all --force --keep-storage 2GB
done
fi
# Reuse the verified images in two fresh isolated epochs. Native finalization
# and native-loss recovery cannot both be proved after the same participant exits.
for scenario in orderly loss; do
 project=$prefix-$scenario
 work compose -p "$project" -f "$manifest" up -d
 work compose -p "$project" -f "$manifest" run --rm federation-verify
 if [ "$scenario" = orderly ]; then
  work compose -p "$project" -f "$manifest" stop manufacturing-api shipping-api
  work compose -p "$project" -f "$manifest" run --rm federation-verify python scripts/mixed_federation_check.py --phase subset
  work compose -p "$project" -f "$manifest" stop storage-api logistics-api
  work compose -p "$project" -f "$manifest" run --rm federation-verify python scripts/mixed_federation_check.py --phase zero-sources
  work compose -p "$project" -f "$manifest" start manufacturing-api shipping-api storage-api logistics-api
  work compose -p "$project" -f "$manifest" run --rm federation-verify python scripts/mixed_federation_check.py --phase all-sources
  work compose -p "$project" -f "$manifest" run --rm federation-verify python scripts/mixed_federation_check.py --phase finalize
 else
  work compose -p "$project" -f "$manifest" stop storage-adapter
  work compose -p "$project" -f "$manifest" run --rm federation-verify python scripts/mixed_federation_check.py --phase adapter-loss
  work compose -p "$project" -f "$manifest" start storage-adapter
  work compose -p "$project" -f "$manifest" restart storage-controller
  work compose -p "$project" -f "$manifest" run --rm federation-verify python scripts/mixed_federation_check.py --phase adapter-loss
 fi
 # These volumes were allocated by this unique disposable verification project;
 # remove them only after success. Failure trap retains volumes for diagnosis.
 work compose -p "$project" -f "$manifest" down --volumes
done
