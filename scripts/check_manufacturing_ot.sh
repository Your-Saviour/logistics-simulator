#!/bin/sh
# Real PLC/FUXA acceptance. Only this unique project's disposable volumes are removed.
set -eu
project=simu-manufacturing-ot-$(date +%s)-$$
artifacts=${OT_ARTIFACTS:-.superpowers/sdd/manufacturing-ot-acceptance}
mkdir -p "$artifacts"
artifacts=$(cd "$artifacts" && pwd)
envfile=$(mktemp "$artifacts/credentials.XXXXXX")
base=apps/manufacturing/compose.v1.yaml
overlay=apps/manufacturing/compose.ot.yaml
runtime=ghcr.io/autonomy-logic/openplc-runtime@sha256:2ca9fc611f25c3ad0471b996a4bf27507ac112612292426ca6d5ca4bf06e97e6
work() { python3 scripts/docker_guard.py --wait --label manufacturing-ot -- docker "$@"; }
compose() { work compose -p "$project" --env-file "$envfile" -f "$base" -f "$overlay" --profile local "$@"; }
cleanup() {
  docker compose -p "$project" --env-file "$envfile" -f "$base" -f "$overlay" --profile local logs --no-color > "$artifacts/services.log" 2>&1 || true
  compose down --volumes --remove-orphans || true
  rm -f "$envfile"
}
trap cleanup EXIT HUP INT TERM
python3 - "$envfile" <<'PY'
import json,secrets,sys
from pathlib import Path
password=secrets.token_hex(24);hmi=secrets.token_hex(24)
identities=[{'username':'employee','password':password,'role':'employee'},
 {'username':'fuxa','password':hmi,'role':'operator','scopes':['status:read','runs:control']}]
p=Path(sys.argv[1]);p.chmod(0o600)
p.write_text('MANUFACTURING_USERNAME=operator\nMANUFACTURING_PASSWORD='+password+'\nMANUFACTURING_IDENTITIES='+json.dumps(identities,separators=(',',':'))+'\nFUXA_API_PASSWORD='+hmi+'\nPLC_PASSWORD='+secrets.token_hex(24)+'\nOT_EQUIPMENT_TOKEN='+secrets.token_hex(24)+'\nMANUFACTURING_PORT=0\nFUXA_PORT=0\nSCENARIO_PRESET=pump-assembly\nAUTONOMOUS_PRODUCTION=false\n')
PY
python_case() { work run --rm --network "${project}_default" --env-file "$envfile" --entrypoint python3 -v "$PWD/apps/manufacturing/ot/acceptance:/tests:ro" -v "$artifacts:/artifacts" "$runtime" "$@"; }
if [ "${STACK_REUSE_IMAGES:-0}" != 1 ]; then
  for service in ot-plc-compiler openplc manufacturing-equipment manufacturing-api manufacturing-web; do compose build "$service"; done
  work build -t logistics-simulator:simu54-browser -f apps/browser-check/Dockerfile .
fi
work run --rm --entrypoint python3 -w /tests -v "$PWD/apps/manufacturing/ot/equipment:/tests:ro" "$runtime" -m unittest discover -s tests
work run --rm --entrypoint python3 -w /tests -v "$PWD/apps/manufacturing/ot/compatibility:/tests:ro" "$runtime" -m unittest discover -p 'test_*.py'
compose up -d --no-build manufacturing-api manufacturing-worker manufacturing-controller manufacturing-web fuxa
python_case /tests/client.py
compose run --rm --no-deps ot-fuxa-bootstrap
work run --rm --network "${project}_default" --env-file "$envfile" --entrypoint node -v "$PWD/apps/manufacturing/ot/acceptance:/tests:ro" -v "$artifacts:/artifacts" logistics-simulator:simu54-browser /tests/workflow.mjs
compose exec -T manufacturing-db psql -U manufacturing -d manufacturing -v ON_ERROR_STOP=1 < apps/manufacturing/ot/acceptance/steps.sql
python_case /tests/recovery.py replay
compose stop manufacturing-equipment
python_case /tests/recovery.py disconnected
work run --rm --network "${project}_default" --entrypoint node -v "$PWD/apps/manufacturing/ot/acceptance:/tests:ro" -v "$artifacts:/artifacts" logistics-simulator:simu54-browser /tests/disconnected.mjs
compose start manufacturing-equipment
python_case /tests/recovery.py restarted
compose restart manufacturing-controller
python_case /tests/recovery.py new-epoch
python_case /tests/recovery.py replay
compose restart openplc
python_case /tests/recovery.py restarted
compose restart manufacturing-controller
python_case /tests/recovery.py new-epoch
compose restart manufacturing-controller
python_case /tests/recovery.py controller-restarted
compose restart manufacturing-controller
python_case /tests/recovery.py new-epoch
printf 'Manufacturing OT acceptance passed; local Docker artifacts: %s\n' "$artifacts"
