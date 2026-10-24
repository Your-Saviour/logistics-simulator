#!/bin/sh
# Host orchestration only; each service build/test executes in Docker.
set -eu
app=${1:-all}
case "$app" in storage|manufacturing|logistics|shipping|twin|all) ;; *) echo 'Expected storage, manufacturing, logistics, shipping, twin or all' >&2; exit 2;; esac
work() { python3 scripts/docker_guard.py --wait --minimum-gib "${SIMULATOR_MINIMUM_FREE_GIB:-20}" --label "stack-$app" -- docker "$@"; }
python3 scripts/stacks_compose.py --app "$app"
if [ "$app" = all ]; then
 manifest=deploy/generated/migration-standalone-suite.json
 selected='storage manufacturing logistics shipping twin'
else
 manifest=deploy/generated/migration-$app.json
 selected=$app
fi
cleanup() { work compose -f "$manifest" down; }
trap cleanup EXIT HUP INT TERM
if [ "${STACK_REUSE_IMAGES:-0}" != 1 ]; then
work build -t logistics-simulator:bootstrap .
# Never ask Compose/BuildKit to build all five stacks concurrently.
for selected_app in $selected; do
 work compose -f "$manifest" build "$selected_app-api"
 if [ "$selected_app" != shipping ]; then work compose -f "$manifest" build "$selected_app-web"; fi
 work builder prune --all --force --keep-storage 2GB
done
work compose -f "$manifest" build browser-check
fi
work compose -f "$manifest" up -d
for selected_app in $selected; do
 work compose -f "$manifest" run --rm "$selected_app-verify"
 if [ "$selected_app" != twin ]; then
  work compose -f "$manifest" run --rm "$selected_app-verify" python scripts/stack_acceptance.py --app "$selected_app" --url "http://$selected_app-api:8000" --terminal-reset
  if [ "${STACK_STARTUP_ONLY:-0}" != 1 ]; then sh scripts/recovery_stacks.sh "$manifest" "$selected_app"; fi
 fi
 if [ "$selected_app" = logistics ]; then
  work compose -f "$manifest" up -d --scale logistics-worker=2 logistics-worker
  work compose -f "$manifest" run --rm logistics-verify python scripts/logistics_acceptance.py
  work compose -f "$manifest" run --rm logistics-verify python scripts/logistics_acceptance.py --phase prepare-transit
  work compose -f "$manifest" stop logistics-worker
  work compose -f "$manifest" run --rm logistics-verify python scripts/logistics_acceptance.py --phase queue
  work compose -f "$manifest" start logistics-worker
  work compose -f "$manifest" run --rm logistics-verify python scripts/logistics_acceptance.py --phase recovered
  work compose -f "$manifest" stop logistics-broker
  work compose -f "$manifest" run --rm logistics-verify python scripts/logistics_acceptance.py --phase broker-down
  work compose -f "$manifest" up -d --wait logistics-broker
  work compose -f "$manifest" run --rm logistics-verify python scripts/logistics_acceptance.py --phase broker-up
 fi
 if [ "$selected_app" = manufacturing ]; then
  work compose -f "$manifest" up -d --scale manufacturing-worker=2 manufacturing-worker
  replicas=$(docker compose -f "$manifest" ps -q --status running manufacturing-worker | wc -l)
  [ "$replicas" -eq 2 ]
  work compose -f "$manifest" run --rm manufacturing-verify python scripts/manufacturing_acceptance.py
  work compose -f "$manifest" stop manufacturing-worker
  work compose -f "$manifest" run --rm manufacturing-verify python scripts/manufacturing_acceptance.py --phase workers-down
  work compose -f "$manifest" start manufacturing-worker
  work compose -f "$manifest" run --rm manufacturing-verify python scripts/manufacturing_acceptance.py --phase workers-up
  work compose -f "$manifest" stop manufacturing-broker
  work compose -f "$manifest" run --rm manufacturing-verify python scripts/manufacturing_acceptance.py --phase broker-down
  work compose -f "$manifest" up -d --wait manufacturing-broker
  work compose -f "$manifest" run --rm manufacturing-verify python scripts/manufacturing_acceptance.py --phase broker-up
 fi
 if [ "$selected_app" = shipping ]; then
  work compose -f "$manifest" run --rm shipping-verify python scripts/shipping_acceptance.py
  work compose -f "$manifest" stop shipping-worker
  work compose -f "$manifest" run --rm shipping-verify python scripts/shipping_acceptance.py --phase queue
  work compose -f "$manifest" start shipping-worker
  work compose -f "$manifest" run --rm shipping-verify python scripts/shipping_acceptance.py --phase recovered
 fi
 if [ "$selected_app" = storage ]; then
  work compose -f "$manifest" up -d --scale storage-worker=2 storage-worker
  replicas=$(docker compose -f "$manifest" ps -q --status running storage-worker | wc -l)
  [ "$replicas" -eq 2 ]
  echo 'storage V1: two worker replicas running'
  work compose -f "$manifest" run --rm storage-verify python scripts/storage_acceptance.py
  work compose -f "$manifest" stop storage-broker
  work compose -f "$manifest" run --rm storage-verify python scripts/storage_acceptance.py --phase broker-down
  work compose -f "$manifest" up -d --wait storage-broker
  work compose -f "$manifest" run --rm storage-verify python scripts/storage_acceptance.py --phase broker-up
  work compose -f "$manifest" stop storage-worker
  work compose -f "$manifest" run --rm storage-verify python scripts/storage_acceptance.py --phase queue
  work compose -f "$manifest" start storage-worker
  work compose -f "$manifest" run --rm storage-verify python scripts/storage_acceptance.py --phase recovered
 fi
done
work compose -f "$manifest" run --rm browser-check
if [ "$app" = all ]; then
 work compose -f "$manifest" run --rm twin-verify python scripts/twin_acceptance.py --phase native
 work compose -f "$manifest" run --rm twin-verify python scripts/twin_acceptance.py --phase five-sites
 work compose -f "$manifest" stop twin-api twin-projection twin-web
 work compose -f "$manifest" run --rm twin-verify python scripts/twin_acceptance.py --phase without-twin
 work compose -f "$manifest" start twin-api twin-projection twin-web
 work compose -f "$manifest" run --rm twin-verify python scripts/twin_acceptance.py --phase native
 # Each website can stop while the other four keep serving independently.
 for site in storage manufacturing logistics shipping twin; do
  frontend="$site-web"
  if [ "$site" = shipping ]; then frontend=shipping-api; fi
  work compose -f "$manifest" stop "$frontend"
  work compose -f "$manifest" run --rm twin-verify python scripts/twin_acceptance.py --phase five-sites --skip-site "$site"
  work compose -f "$manifest" start "$frontend"
 done
fi
if [ "$app" = all ]; then
 # Also prove each image starts with only its own dependency graph. Reuse the
 # images just built; outage checks already ran above against those images.
 work compose -f "$manifest" down
 for selected_app in $selected; do
  STACK_REUSE_IMAGES=1 STACK_STARTUP_ONLY=1 sh scripts/check_stacks.sh "$selected_app"
 done
fi
