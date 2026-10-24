#!/bin/sh
# All framework and dependency checks execute in the application's containers.
set -eu
app=${1:?Expected storage, manufacturing, logistics, shipping or twin}
work() { python3 scripts/docker_guard.py --minimum-gib "${SIMULATOR_MINIMUM_FREE_GIB:-20}" --label "$app-unit" -- docker "$@"; }
case "$app" in
storage)
 manifest=apps/storage/compose.smoke.yaml
 project=simu-storage-unit-$(date +%s)
 cleanup() { docker compose -p "$project" -f "$manifest" down --volumes; }; trap cleanup EXIT HUP INT TERM
 work compose -p "$project" -f "$manifest" up -d storage-db storage-rabbit
 work compose -p "$project" -f "$manifest" run --rm tests
 ;;
manufacturing)
 manifest=apps/manufacturing/compose.test.yml
 cleanup() { docker compose -f "$manifest" down; }; trap cleanup EXIT HUP INT TERM
 work compose -f "$manifest" run --rm backend-test sh -c 'mvn -B -q verify dependency:tree -DoutputFile=/tmp/dependencies.actual && diff -u dependencies.lock /tmp/dependencies.actual'
 ;;
logistics)
 manifest=apps/logistics/compose.test.yml
 cleanup() { docker compose -p logistics-go-test -f "$manifest" down; }; trap cleanup EXIT HUP INT TERM
 work compose -p logistics-go-test -f "$manifest" up -d --wait db broker
 work compose -p logistics-go-test -f "$manifest" run --rm test sh -c 'go vet -tags nomsgpack -p 1 ./... && go test -tags nomsgpack -p 1 -count=1 -timeout 120s ./...'
 ;;
shipping)
 manifest=apps/shipping/compose.smoke.yml
 cleanup() { docker compose -f "$manifest" down; }; trap cleanup EXIT HUP INT TERM
 work compose -f "$manifest" build shipping-api
 work compose -f "$manifest" up -d --wait shipping-db shipping-broker
 work compose -f "$manifest" run --rm --no-deps --entrypoint sh shipping-api /app/tests/all.sh
 ;;
twin)
 manifest=apps/twin/test.compose.yml
 cleanup() { docker compose -f "$manifest" down; }; trap cleanup EXIT HUP INT TERM
 work compose -f "$manifest" run --build --rm tests
 ;;
*) echo 'Expected storage, manufacturing, logistics, shipping or twin' >&2; exit 2;;
esac
