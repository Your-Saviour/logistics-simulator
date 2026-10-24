#!/bin/sh
# Only disposable migrated-stack test containers are stopped/restarted.
set -eu
manifest=${1:?Expected generated test manifest}
app=${2:?Expected business application}
case "$manifest" in deploy/generated/migration-*.json) ;; *) echo 'Expected an isolated migration test manifest' >&2;exit 2;; esac
case "$app" in storage|manufacturing|logistics|shipping) ;; *) echo 'Business application required' >&2;exit 2;; esac
work() { python3 scripts/docker_guard.py --minimum-gib "${SIMULATOR_MINIMUM_FREE_GIB:-20}" --label "$app-recovery" -- docker "$@"; }
probe() { work compose -f "$manifest" run --rm "$app-verify" python scripts/stack_recovery.py --app "$app" --url "http://$app-api:8000" --phase "$1"; }
probe prepare-broker
work compose -f "$manifest" stop "$app-broker"
probe broker-down
work compose -f "$manifest" up -d --wait "$app-broker"
probe broker-up
work compose -f "$manifest" stop "$app-worker"
probe duplicate
work compose -f "$manifest" start "$app-worker"
probe worker-up
probe prepare-db
work compose -f "$manifest" stop "$app-db"
probe db-down
work compose -f "$manifest" up -d --wait "$app-db"
work compose -f "$manifest" restart "$app-controller" "$app-worker"
probe db-up
