#!/bin/sh
# Synthetic rendering benchmark against the production frontend, not business acceptance.
set -eu
project=simu-handling-performance-$(date +%s)
artifacts=.superpowers/sdd/2026-10-25-simu64-implementation/performance
renderer=${HANDLING_PERFORMANCE_RENDERER:-mesa}
case "$renderer" in
 mesa) browser_image=logistics-simulator:handling-performance-browser ;;
 swiftshader) browser_image=logistics-simulator:handling-ui-browser ;;
 *) echo 'HANDLING_PERFORMANCE_RENDERER must be mesa or swiftshader' >&2; exit 2 ;;
esac
mkdir -p "$artifacts"
work() { python3 scripts/docker_guard.py --wait --label handling-performance -- docker "$@"; }
cleanup() { docker rm -f "$project-web" >/dev/null 2>&1 || true; docker network rm "$project" >/dev/null 2>&1 || true; }
trap cleanup EXIT HUP INT TERM
if [ "${HANDLING_PERFORMANCE_REUSE_IMAGES:-0}" != 1 ]; then
 work build -f apps/twin/web/Dockerfile -t logistics-simulator:twin-web-migrated .
 work build -f apps/browser-check/Dockerfile -t logistics-simulator:handling-ui-browser .
 if [ "$renderer" = mesa ]; then work build -f apps/browser-check/Dockerfile.performance -t "$browser_image" .; fi
fi
host_hardware=$(python3 - <<'PY'
import json,platform,subprocess
result={'platform':platform.platform()}
for key in ('machdep.cpu.brand_string','hw.ncpu','hw.memsize','hw.model'):
 try:result[key]=subprocess.check_output(['sysctl','-n',key],text=True,stderr=subprocess.DEVNULL).strip()
 except (OSError,subprocess.CalledProcessError):pass
print(json.dumps(result))
PY
)
work network create "$project"
work run -d --name "$project-web" --network "$project" --network-alias preview -e API_UPSTREAM=http://127.0.0.1:8000 logistics-simulator:twin-web-migrated
work run --rm --network "$project" -e TWIN_URL=http://preview:8080 -e HANDLING_BENCHMARK=1 -e "HANDLING_RENDERER=$renderer" -e "HOST_HARDWARE_JSON=$host_hardware" -v "$PWD/$artifacts:/artifacts" "$browser_image" npx playwright test handling-performance.spec.ts
