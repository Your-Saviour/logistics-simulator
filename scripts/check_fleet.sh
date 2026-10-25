#!/bin/sh
# Isolated fleet database only. No persistent project or data volumes touched.
set -eu
project=simu-fleet-unit-$(date +%s)
manifest=apps/fleet/test.compose.yml
work() { python3 scripts/docker_guard.py --wait --label fleet-unit -- docker "$@"; }
cleanup() {
  result=$?
  trap - EXIT HUP INT TERM
  if work compose -p "$project" -f "$manifest" down --volumes; then :; else
    if [ "$result" -eq 0 ]; then result=1; fi
  fi
  exit "$result"
}
trap cleanup EXIT HUP INT TERM
work compose -p "$project" -f "$manifest" run --build --rm tests "$@"
