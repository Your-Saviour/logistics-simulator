#!/bin/sh
# Synthetic production-frontend rendering benchmark; not native acceptance.
set -eu
project=simu-fleet-performance-$(date +%s)
artifacts=${FLEET_PERFORMANCE_ARTIFACTS:-.superpowers/sdd/2026-10-25-simu75-implementation/render-performance}
browser_image=logistics-simulator:handling-performance-browser
web_image=logistics-simulator:twin-fleet-web
mkdir -p "$artifacts"
work() { python3 scripts/docker_guard.py --wait --label fleet-performance -- docker "$@"; }
cleanup() { docker rm -f "$project-web" >/dev/null 2>&1 || true; docker network rm "$project" >/dev/null 2>&1 || true; }
trap cleanup EXIT HUP INT TERM
# Reuse cached images. This benchmark deliberately does not install or rebuild software.
docker image inspect "$browser_image" "$web_image" >/dev/null
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
work run -d --name "$project-web" --network "$project" --network-alias preview -e API_UPSTREAM=http://127.0.0.1:8000 "$web_image"
work run --rm --network "$project" -e TWIN_URL=http://preview:8080 -e FLEET_BENCHMARK=1 -e HANDLING_RENDERER=mesa -e "HOST_HARDWARE_JSON=$host_hardware" -e "BENCHMARK_BROWSER_IMAGE=$browser_image" -v "$PWD/$artifacts:/artifacts" -v "$PWD/apps/browser-check/fleet-performance.spec.ts:/checks/fleet-performance.spec.ts:ro" "$browser_image" sh -c 'printf "%s\n" "import base from \"./playwright.config\"; export default {...base,testMatch:[\"fleet-performance.spec.ts\"]};" > /checks/fleet-performance.config.ts; npx playwright test --config=fleet-performance.config.ts'
