#!/bin/sh
# Exercise persistent packaging with a fresh, disposable project and volumes.
# Existing manufacturing-v1 deployments and credentials are never attached.
set -eu
project=simu-manufacturing-startup-$(date +%s)
manifest=apps/manufacturing/compose.v1.yaml
mkdir -p .superpowers/sdd/simu-3
envfile=$(mktemp .superpowers/manufacturing-startup.XXXXXX)
remoteenv=$(mktemp .superpowers/manufacturing-worker.XXXXXX)
remote="$project-external-worker"
work() { python3 scripts/docker_guard.py --minimum-gib "${SIMULATOR_MINIMUM_FREE_GIB:-20}" --label manufacturing-startup -- docker "$@"; }
cleanup() { docker rm -f "$remote" >/dev/null 2>&1 || true; docker compose -p "$project" --env-file "$envfile" -f "$manifest" --profile local down --volumes; rm -f "$envfile" "$remoteenv"; }
trap cleanup EXIT HUP INT TERM
python3 - "$envfile" <<'PY'
import secrets,sys
from pathlib import Path
p=Path(sys.argv[1]);p.chmod(0o600)
p.write_text('MANUFACTURING_USERNAME=operator\nMANUFACTURING_PASSWORD='+secrets.token_hex(24)+'\nMANUFACTURING_PORT=0\nAUTONOMOUS_PRODUCTION=true\nSCENARIO_PRESET=pump-assembly\n')
PY
work tag logistics-simulator:manufacturing-migrated logistics-simulator:manufacturing-v1
work tag logistics-simulator:manufacturing-web-migrated logistics-simulator:manufacturing-v1-web
work compose -p "$project" --env-file "$envfile" -f "$manifest" --profile local up -d --no-build --wait --wait-timeout 120
work run --rm --network "${project}_default" --env-file "$envfile" logistics-simulator:bootstrap python -c '
import os,time,httpx
with httpx.Client(base_url="http://manufacturing-web",auth=(os.environ["MANUFACTURING_USERNAME"],os.environ["MANUFACTURING_PASSWORD"]),timeout=5) as client:
    deadline=time.monotonic()+45
    while time.monotonic()<deadline:
        try:
            if client.get("/api/health/ready").status_code==200:
                client.get("/").raise_for_status();client.get("/api/production").raise_for_status()
                client.post("/api/control/speed",json={"speed":60}).raise_for_status()
                end=time.monotonic()+45
                while time.monotonic()<end:
                    snapshot=client.get("/api/production").json()
                    if any(o["status"]=="completed" for o in snapshot["orders"]):
                        assert snapshot["config"]["products"][0]["sku"]=="PUMP"
                        break
                    time.sleep(.2)
                else: raise AssertionError("Autonomous production did not complete")
                print("manufacturing V1: fresh persistent packaging starts ready without manual restarts")
                break
        except httpx.HTTPError: pass
        time.sleep(.2)
    else: raise AssertionError("Persistent packaging failed readiness")'
for service in manufacturing-api manufacturing-worker manufacturing-controller; do
 container=$(docker compose -p "$project" --env-file "$envfile" -f "$manifest" ps -q "$service")
 [ "$(docker inspect --format '{{.RestartCount}}' "$container")" -eq 0 ]
done
# Run a worker outside the Compose dependency graph using explicit DB/broker URLs.
python3 - "$envfile" "$remoteenv" <<'PYENV'
import sys
from pathlib import Path
values=dict(line.split('=',1) for line in Path(sys.argv[1]).read_text().splitlines())
secret=values['MANUFACTURING_PASSWORD']
Path(sys.argv[2]).chmod(0o600)
Path(sys.argv[2]).write_text('ROLE=worker\nCLOCK_MODE=standalone\nAPP_USERNAME=operator\nAPP_PASSWORD='+secret+'\nDATABASE_URL=postgresql://manufacturing:'+secret+'@manufacturing-db:5432/manufacturing\nAMQP_URL=amqp://manufacturing:'+secret+'@manufacturing-rabbit:5672/%2f\nJAVA_TOOL_OPTIONS=-Xmx256m\nAUTONOMOUS_PRODUCTION=false\n')
PYENV
work compose -p "$project" --env-file "$envfile" -f "$manifest" stop manufacturing-worker
work run -d --name "$remote" --network "${project}_default" --env-file "$remoteenv" logistics-simulator:manufacturing-v1
work run --rm --network "${project}_default" --env-file "$envfile" logistics-simulator:bootstrap python -c '
import os,time,httpx,uuid
with httpx.Client(base_url="http://manufacturing-web",auth=(os.environ["MANUFACTURING_USERNAME"],os.environ["MANUFACTURING_PASSWORD"]),timeout=5) as c:
    r=c.get("/api/status").json()["run"]
    response=c.post("/api/jobs",json={"due_at":max(r["granted"],r["requested"])+5,"quantity":13},headers={"Idempotency-Key":"external-worker-"+uuid.uuid4().hex});response.raise_for_status();job=response.json()["id"]
    deadline=time.monotonic()+60
    while time.monotonic()<deadline:
        if any(j["id"]==job and j["status"]=="completed" for j in c.get("/api/status").json()["jobs"]): break
        time.sleep(.2)
    else: raise AssertionError("External worker did not execute durable work")
    print("manufacturing V1: separately launched worker connects to explicit owned PostgreSQL/RabbitMQ addresses and executes work")'
# The optional local dependencies must also permit externally addressed roles.
work compose -p "$project" --env-file "$envfile" -f "$manifest" config --quiet
echo 'manufacturing V1: startup ordering, zero backend restarts and external profile configuration passed'
