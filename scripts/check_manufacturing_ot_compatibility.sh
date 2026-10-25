#!/bin/sh
# Real PLC acceptance in a disposable project; never touches deployment volumes.
set -eu
project="simu54-compat-$$"
manifest=apps/manufacturing/ot/compatibility/compose.yaml
work() { python3 scripts/docker_guard.py --wait --label simu54-compat -- docker compose -p "$project" -f "$manifest" "$@"; }
cleanup() { work down --volumes --remove-orphans; }
trap cleanup EXIT HUP INT TERM
work run --rm compiler
work run --rm bootstrap
work run --rm probe
