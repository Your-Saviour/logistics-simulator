#!/bin/sh
# Explicit disposable acceptance only; no existing volumes or live cutover.
set -eu
umask 077
manifest=$(python3 scripts/fleet_factory_compose.py)
artifacts=$(python3 -c 'import json,sys;v=json.load(open(sys.argv[1]));print(next(x.split(":/evidence")[0] for x in v["services"]["verify"]["volumes"] if x.endswith(":/evidence")))' "$manifest")
verifier=$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["name"]+"-verifier")' "$manifest")
work() { python3 scripts/docker_guard.py --wait --label fleet-factory -- docker "$@"; }
cleanup() {
 result=$?
 trap - EXIT HUP INT TERM
 docker compose -f "$manifest" logs --no-color > "$artifacts/services.log" 2>&1 || true
 docker logs "$verifier" > "$artifacts/verifier.log" 2>&1 || true
 work rm -f "$verifier" || true
 if work compose -f "$manifest" down --volumes; then :; else cleanup_result=$?; if [ "$result" -eq 0 ]; then result=$cleanup_result; fi; fi
 chmod 600 "$artifacts"/* 2>/dev/null || true
 echo "Fleet factory evidence: $artifacts"
 exit "$result"
}
trap cleanup EXIT HUP INT TERM
if [ "${FLEET_FACTORY_REUSE_IMAGES:-0}" != 1 ]; then
 work build -t logistics-simulator:bootstrap .
 work build -t logistics-simulator:handling-factory-adapter -f apps/adapter/Dockerfile .
 for app in storage manufacturing shipping logistics; do work compose -f "$manifest" build "$app-api"; done
 work compose -f "$manifest" build fleet-api
 if [ "${FLEET_FACTORY_WITH_TWIN:-0}" = 1 ]; then work compose -f "$manifest" build twin-api; fi
fi
work compose -f "$manifest" up -d --no-build
python3 scripts/fleet_factory_compose.py --control "$manifest" "$artifacts"
