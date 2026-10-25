#!/usr/bin/env bash
# Real scheduler measurements with explicitly synthetic clients and isolated SQL.
set -euo pipefail
project="simu-fleet-budget-$(date +%s)-$$"
manifest=apps/fleet/test.compose.yml
output=.superpowers/sdd/2026-10-25-simu75-implementation/scheduler-budget
mkdir -p "$output"
# Fleet containers use uid10002. Only the explicitly generated evidence directory
# is writable; source and existing application volumes remain untouched.
chmod 0777 "$output"
work() { python3 scripts/docker_guard.py --wait --label fleet-budget -- docker "$@"; }
cleanup() {
  result=$?
  trap - EXIT HUP INT TERM
  if work compose -p "$project" -f "$manifest" down --volumes; then :; else
    if [ "$result" -eq 0 ]; then result=1; fi
  fi
  exit "$result"
}
trap cleanup EXIT HUP INT TERM
# One case per guarded command lets native regression checks interleave.
# Usage: scripts/check_fleet_budget.sh [4|8|16|all] [--wall-limit SECONDS]
selection=${1:-all}
case "$selection" in
  4|8|16) sizes=("$selection"); shift ;;
  all) sizes=(4 8 16); if [ "$#" -gt 0 ]; then shift; fi ;;
  --*) sizes=(4 8 16) ;;
  *) echo 'Expected 4, 8, 16 or all' >&2; exit 2 ;;
esac
for size in "${sizes[@]}"; do
  work compose -p "$project" -f "$manifest" run --build --rm \
    -e FLEET_BENCHMARK_ISOLATED=1 -v "$PWD/$output:/budget" \
    tests python -u tests/benchmark_fleet.py --size "$size" --output "/budget/results-$size.json" "$@" \
    2>&1 | tee "$output/stdout-$size.log"
  # Guard waiters poll every2s; yield without the lock before the next case.
  sleep 3
done
python3 - "$output" "${sizes[@]}" <<'PYMERGE'
import json
from pathlib import Path
import sys
root=Path(sys.argv[1])
reports=[json.loads((root/f'results-{size}.json').read_text()) for size in sys.argv[2:]]
merged={**reports[0],'cases':[case for report in reports for case in report['cases']]}
(root/'results.json').write_text(json.dumps(merged,indent=2,sort_keys=True)+'\n')
PYMERGE
