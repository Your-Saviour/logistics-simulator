#!/bin/sh
set -eu
manifest=deploy/generated/handling-factory.json
artifacts=.superpowers/sdd/2026-10-25-simu64-implementation/factory-native
mkdir -p "$artifacts"
work() { python3 scripts/docker_guard.py --wait --label handling-factory -- docker "$@"; }
python3 scripts/handling_factory_compose.py
cleanup() {
 result=$?
 trap - EXIT HUP INT TERM
 docker compose -f "$manifest" logs --no-color > "$artifacts/services.log" 2>&1 || true
 if work compose -f "$manifest" down --volumes; then :; else cleanup_result=$?; if [ "$result" -eq 0 ]; then result=$cleanup_result; fi; fi
 exit "$result"
}
trap cleanup EXIT HUP INT TERM
if [ "${HANDLING_FACTORY_REUSE_IMAGES:-0}" != 1 ]; then
 work build -t logistics-simulator:bootstrap .
 work build -t logistics-simulator:handling-factory-adapter -f apps/adapter/Dockerfile .
 for app in storage manufacturing shipping logistics; do work compose -f "$manifest" build "$app-api"; done
fi
work compose -f "$manifest" up -d
work compose -f "$manifest" run --rm verify
