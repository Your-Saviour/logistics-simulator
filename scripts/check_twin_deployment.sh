#!/bin/sh
# Host orchestration only. All service builds and checks run in guarded Docker.
set -eu
project=simu-twin-acceptance-$(date +%s)-$$
manifest=apps/twin/acceptance.compose.yml
work() { python3 scripts/docker_guard.py --wait --minimum-gib "${SIMULATOR_MINIMUM_FREE_GIB:-20}" --label twin-deployment -- docker "$@"; }
compose() { work compose -p "$project" -f "$manifest" "$@"; }
cleanup() {
 result=$?
 if [ "$result" -ne 0 ]; then
  docker compose -p "$project" -f "$manifest" ps -a
  docker compose -p "$project" -f "$manifest" logs --tail 60
 fi
 # This unique project owns only disposable containers and anonymous DB data.
 compose down --volumes
}
trap cleanup EXIT HUP INT TERM
if [ "${STACK_REUSE_IMAGES:-0}" != 1 ]; then
 compose build api
 compose build web
fi
export TWIN_ACCEPTANCE_SOURCES='[]'
compose up -d db broker api projection web storage-fixture shipping-fixture
compose run --rm verify --phase zero
storage='{"name":"storage","url":"http://storage-fixture:8000","username":"fixture-observer","password":"isolated-source-password"}'
shipping='{"name":"shipping","url":"http://shipping-fixture:8000","username":"fixture-observer","password":"isolated-source-password"}'
export TWIN_ACCEPTANCE_SOURCES="[$storage]"
compose up -d --force-recreate api projection web
compose run --rm verify --phase subset
export TWIN_ACCEPTANCE_SOURCES="[$storage,$shipping]"
compose up -d --force-recreate api projection web
compose run --rm verify --phase connected
compose stop shipping-fixture
compose run --rm verify --phase stale
compose start shipping-fixture
compose run --rm verify --phase connected
compose stop api projection web
compose run --rm verify --phase advance
compose start api projection web
compose run --rm verify --phase catchup
compose restart api projection
compose run --rm verify --phase durable
export TWIN_ACCEPTANCE_SOURCES="[$storage]"
compose up -d --force-recreate api projection web
compose run --rm verify --phase reconfigured
