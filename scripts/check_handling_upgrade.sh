#!/bin/sh
# Disposable pre-unit schemas -> current native APIs -> repeat startup.
set -eu
manifest=deploy/generated/handling-upgrade.json
artifacts=.superpowers/sdd/2026-10-25-simu64-implementation/upgrade-native
mkdir -p "$artifacts"
work() { python3 scripts/docker_guard.py --wait --label handling-upgrade -- docker "$@"; }
python3 - <<'PY'
import json,sys
from pathlib import Path
sys.path.insert(0,'scripts')
from stacks_compose import generate,ROOT
apps=['storage','manufacturing','shipping','logistics']
value=generate(apps,write=False,disposable=True)
value['name']=value['name'].replace('migration-standalone-suite','handling-upgrade')
services=value['services']
identities={};databases={}
for app in apps:
    env=services[app+'-api']['environment']
    identities[app]={'username':env['APP_USERNAME'],'password':env['APP_PASSWORD']}
    databases[app]=env['DATABASE_URL']
    for role in ('api','worker','controller'):
        services[app+'-'+role]['environment'].update(AUTONOMOUS_WAREHOUSE='false',AUTONOMOUS_PRODUCTION='false')
    for role in ('web','verify'):
        services.pop(app+'-'+role,None)
    if app not in ('storage','manufacturing'):
        for role in ('worker','controller'):
            services.pop(app+'-'+role,None)
services.pop('browser-check',None)
services['upgrade-check']={'image':'logistics-simulator:bootstrap','profiles':['test'],'user':'0:0',
    'environment':{'UPGRADE_DATABASES':json.dumps(databases),'UPGRADE_IDENTITIES':json.dumps(identities)},
    'volumes':[str(ROOT)+':/repo:ro',str(ROOT/'.superpowers/sdd/2026-10-25-simu64-implementation/upgrade-native')+':/evidence'],
    'entrypoint':['python','/repo/scripts/handling_upgrade_verify.py']}
path=ROOT/'deploy/generated/handling-upgrade.json'
path.write_text(json.dumps(value,indent=2));path.chmod(0o600)
PY
cleanup() {
 result=$?
 trap - EXIT HUP INT TERM
 docker compose -f "$manifest" logs --no-color > "$artifacts/services.log" 2>&1 || true
 if work compose -f "$manifest" down --volumes; then :; else if [ "$result" -eq 0 ]; then result=1; fi; fi
 exit "$result"
}
trap cleanup EXIT HUP INT TERM
work compose -f "$manifest" up -d --wait storage-db manufacturing-db shipping-db logistics-db
work compose -f "$manifest" run --rm upgrade-check seed
work compose -f "$manifest" up -d storage-api manufacturing-api shipping-api logistics-api
work compose -f "$manifest" run --rm upgrade-check migrated
work compose -f "$manifest" restart storage-api manufacturing-api shipping-api logistics-api
work compose -f "$manifest" run --rm upgrade-check restarted
work compose -f "$manifest" up -d storage-worker storage-controller manufacturing-worker manufacturing-controller
work compose -f "$manifest" run --rm upgrade-check convert
work compose -f "$manifest" restart storage-api storage-worker manufacturing-api manufacturing-worker
work compose -f "$manifest" run --rm upgrade-check converted-restart
