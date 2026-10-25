#!/bin/sh
# Disposable project, credentials and volumes. All service work goes through the
# shared guard; no tags, networks or volumes from other projects are touched.
set -eu
cd "$(dirname "$0")/.."
project=${SHIPPING_CHECK_PROJECT:-simu5-shipping-v1}
manifest=apps/shipping/compose.v1.yaml
artifacts=$(pwd)/.superpowers/sdd/simu-5-shipping/deployment
mkdir -p "$artifacts"
envfile=$(mktemp .superpowers/shipping-v1.XXXXXX)
root=$(pwd)
# Worktree invocations must share the original checkout's guard lock.
guard=${SHIPPING_DOCKER_GUARD:-$root/scripts/docker_guard.py}
work() {
 python3 "$guard" --wait --minimum-gib "${SIMULATOR_MINIMUM_FREE_GIB:-20}" --label shipping-v1 -- docker "$@"
}
compose() { work compose -p "$project" --env-file "$envfile" -f "$manifest" --profile local "$@"; }
cleanup() {
 result=$?
 if [ "$result" -ne 0 ]; then docker compose -p "$project" --env-file "$envfile" -f "$manifest" logs --no-color > "$artifacts/containers.log" 2>&1 || true; fi
 compose down --volumes || true
 rm -f "$envfile"
 exit "$result"
}
trap cleanup EXIT HUP INT TERM
python3 - "$envfile" <<'PY'
import base64,json,secrets,sys
from pathlib import Path
path=Path(sys.argv[1]);path.chmod(0o600)
password=secrets.token_hex(24);employee=secrets.token_hex(24)
values={'SHIPPING_USERNAME':'operator','SHIPPING_PASSWORD':password,'SHIPPING_EMPLOYEE_PASSWORD':employee,'SHIPPING_DB_PASSWORD':secrets.token_hex(24),'SHIPPING_BROKER_PASSWORD':secrets.token_hex(24),'SHIPPING_APP_KEY':'base64:'+base64.b64encode(secrets.token_bytes(32)).decode(),'SHIPPING_IDENTITIES':json.dumps([{'username':'employee','password':employee,'role':'employee'}],separators=(',',':')),'SHIPPING_PORT':'0','AUTONOMOUS_SHIPPING':'false','SHIPPING_IMAGE':'logistics-simulator:simu5-shipping'}
path.write_text(''.join(k+'='+v+'\n' for k,v in values.items()))
PY
if [ "${SHIPPING_REUSE_IMAGE:-0}" != 1 ]; then compose build shipping-api; fi
compose config --quiet
compose up -d --no-build --wait --wait-timeout 180
verify() { work run --rm --network "${project}_default" --env-file "$envfile" -v "$root/scripts:/app/scripts:ro" -w /app logistics-simulator:bootstrap python scripts/shipping_acceptance.py "$@"; }
verify
compose stop shipping-worker
verify --phase queue
compose start shipping-worker
verify --phase recovered
work build -t logistics-simulator:browser-check -f apps/browser-check/Dockerfile .
work run --rm --network "${project}_default" --env-file "$envfile" -v "$root/apps/browser-check/shipping.spec.ts:/checks/shipping.spec.ts:ro" -v "$root/apps/browser-check/shipping.config.ts:/checks/shipping.config.ts:ro" -v "$artifacts:/artifacts" logistics-simulator:browser-check npx playwright test --config shipping.config.ts
for service in shipping-api shipping-worker shipping-controller; do
 container=$(docker compose -p "$project" --env-file "$envfile" -f "$manifest" ps -q "$service")
 [ "$(docker inspect --format '{{.RestartCount}}' "$container")" -eq 0 ]
done
printf 'shipping V1: independent production packaging, HTTP, restart and browser acceptance passed; artifacts: %s\n' "$artifacts"
