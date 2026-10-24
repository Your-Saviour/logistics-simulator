#!/bin/sh
# Host orchestration only; each service build/test executes in Docker.
set -eu
app=${1:-all}
case "$app" in storage|manufacturing|logistics|shipping|twin|all) ;; *) echo 'Expected storage, manufacturing, logistics, shipping, twin or all' >&2; exit 2;; esac
work() { python3 scripts/docker_guard.py --minimum-gib "${SIMULATOR_MINIMUM_FREE_GIB:-20}" --label "stack-$app" -- docker "$@"; }
python3 scripts/stacks_compose.py --app "$app"
if [ "$app" = all ]; then
 manifest=deploy/generated/migration-standalone-suite.json
 selected='storage manufacturing logistics shipping twin'
else
 manifest=deploy/generated/migration-$app.json
 selected=$app
fi
cleanup() { docker compose -f "$manifest" down; }
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
done
work compose -f "$manifest" run --rm browser-check
if [ "$app" = all ]; then
 # Also prove each image starts with only its own dependency graph. Reuse the
 # images just built; outage checks already ran above against those images.
 work compose -f "$manifest" down
 for selected_app in $selected; do
  STACK_REUSE_IMAGES=1 STACK_STARTUP_ONLY=1 sh scripts/check_stacks.sh "$selected_app"
 done
fi
