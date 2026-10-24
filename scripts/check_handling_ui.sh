#!/bin/sh
# Production departmental images and real employee workflows; no Twin required.
set -eu
manifest=deploy/generated/handling-ui.json
artifacts=.superpowers/sdd/2026-10-25-simu64-implementation/department-ui
mkdir -p "$artifacts"
work() { python3 scripts/docker_guard.py --wait --label handling-ui -- docker "$@"; }
python3 - <<'PY'
import json
from pathlib import Path
import sys
from uuid import uuid4
sys.path.insert(0, str(Path.cwd() / 'scripts'))
from stacks_compose import generate

value = generate(['storage', 'manufacturing', 'logistics', 'shipping'], write=False)
value['name'] = 'simu-handling-ui-' + uuid4().hex[:8]
browser = value['services']['browser-check']
browser['image'] = 'logistics-simulator:handling-ui-browser'
browser['command'] = ['npx', 'playwright', 'test', 'stacks.spec.ts']
browser['volumes'] = [str(Path('.superpowers/sdd/2026-10-25-simu64-implementation/department-ui').resolve()) + ':/artifacts']
path = Path('deploy/generated/handling-ui.json')
path.write_text(json.dumps(value, indent=2))
path.chmod(0o600)
PY
cleanup() {
 result=$?
 trap - EXIT HUP INT TERM
 docker compose -f "$manifest" logs --no-color > "$artifacts/services.log" 2>&1 || true
 # The unique project above creates only new disposable test volumes.
 if work compose -f "$manifest" down --volumes; then :; else cleanup_result=$?; if [ "$result" -eq 0 ]; then result=$cleanup_result; fi; fi
 exit "$result"
}
trap cleanup EXIT HUP INT TERM
if [ "${HANDLING_UI_REUSE_IMAGES:-0}" != 1 ]; then
 for app in storage manufacturing logistics shipping; do
  work compose -f "$manifest" build "$app-api"
  if [ "$app" != shipping ]; then work compose -f "$manifest" build "$app-web"; fi
 done
fi
work compose -f "$manifest" build browser-check
work compose -f "$manifest" up -d
for app in storage manufacturing logistics shipping; do
 work compose -f "$manifest" run --rm "$app-verify"
done
work compose -f "$manifest" run --rm browser-check
