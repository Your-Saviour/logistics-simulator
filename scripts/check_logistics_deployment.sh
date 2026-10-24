#!/bin/sh
# Fresh disposable project exercises persistent packaging and external service URLs.
set -eu
manifest=apps/logistics/compose.v1.yaml
project=simu4-startup-$(date +%s)
envfile=$(mktemp .superpowers/logistics-startup.XXXXXX)
work() { python3 scripts/docker_guard.py --wait --minimum-gib "${SIMULATOR_MINIMUM_FREE_GIB:-20}" --label logistics-deployment -- docker "$@"; }
runtimefile=$(mktemp .superpowers/logistics-worker.XXXXXX)
configfile=$(mktemp .superpowers/logistics-config.XXXXXX)
cleanup() { docker rm -f "$project-external-worker" 2>/dev/null || true; docker compose -p "$project" --env-file "$envfile" -f "$manifest" --profile local down; rm -f "$envfile" "$runtimefile" "$configfile"; }
trap cleanup EXIT HUP INT TERM
python3 - "$envfile" <<'PY'
from pathlib import Path
import sys,secrets
p=Path(sys.argv[1]);p.chmod(0o600)
secret=secrets.token_hex(24)
p.write_text(f'LOGISTICS_DATABASE_URL=postgresql://logistics:{secret}@logistics-db:5432/logistics\nLOGISTICS_AMQP_URL=amqp://logistics:{secret}@logistics-broker:5672/%2f\nLOGISTICS_DB_PASSWORD={secret}\nLOGISTICS_BROKER_PASSWORD={secret}\nLOGISTICS_PASSWORD={secret}\nLOGISTICS_PORT=0\nLOGISTICS_IMAGE=logistics-simulator:logistics-migrated\nLOGISTICS_WEB_IMAGE=logistics-simulator:logistics-web-migrated\nAUTONOMOUS_SAMPLE=false\n')
PY
work compose -p "$project" --env-file "$envfile" -f "$manifest" --profile local up -d --no-build --wait --wait-timeout 120
work run --rm --network "${project}_default" --env-file "$envfile" logistics-simulator:bootstrap python -c '
import os,time,httpx
with httpx.Client(base_url="http://logistics-web",auth=("operator",os.environ["LOGISTICS_PASSWORD"]),timeout=5) as c:
 for attempt in range(100):
  try:
   if c.get("/api/health/ready").status_code==200:
    c.get("/").raise_for_status();snap=c.get("/api/transport");snap.raise_for_status();assert len(snap.json()["vehicles"])==2;break
  except httpx.HTTPError:pass
  time.sleep(.3)
 else:raise AssertionError("Persistent packaging not ready")
 print("logistics V1 persistent deployment ready with own fleet, website and external endpoint variables")'
# Omit the local profile and use dependencies on another Docker network as an
# external-endpoint reference. Physical-host routing is separate hosted evidence.
work compose -p "$project" --env-file "$envfile" -f "$manifest" config --quiet
for service in logistics-api logistics-worker logistics-controller; do
 container=$(docker compose -p "$project" --env-file "$envfile" -f "$manifest" ps -q "$service")
 [ "$(docker inspect --format '{{.RestartCount}}' "$container")" -eq 0 ]
done

# Run a worker independently of Compose with externally supplied SQL/broker URLs.
work compose -p "$project" --env-file "$envfile" -f "$manifest" stop logistics-worker
docker compose -p "$project" --env-file "$envfile" -f "$manifest" config --format json > "$configfile"
python3 - "$configfile" "$runtimefile" <<'PYENV'
import json,sys
from pathlib import Path
p=Path(sys.argv[2]);p.chmod(0o600)
env=json.loads(Path(sys.argv[1]).read_text())['services']['logistics-worker']['environment']
p.write_text(''.join(f'{k}={v}\n' for k,v in env.items()))
PYENV
work run -d --name "$project-external-worker" --network "${project}_default" --env-file "$runtimefile" logistics-simulator:logistics-migrated
work run --rm --network "${project}_default" --env-file "$envfile" logistics-simulator:bootstrap python -c '
import os,time,httpx
from uuid import uuid4
with httpx.Client(base_url="http://logistics-web",auth=("operator",os.environ["LOGISTICS_PASSWORD"]),timeout=5) as c:
 status=c.get("/api/status").json();r=status["run"]
 body=dict(run_id=r["id"],epoch=r["epoch"],due_at=max(r["granted"],r["requested"])+3,action="request",route="WAREHOUSE-DISPATCH",sku="PRODUCT",quantity=2,correlation_id=str(uuid4()))
 response=c.post("/api/transport/commands",json=body,headers={"Idempotency-Key":str(uuid4())});response.raise_for_status();id=response.json()["id"]
 for attempt in range(150):
  snap=c.get("/api/transport").json()
  if any(x["id"]==id and x["status"]=="completed" for x in snap["commands"]):break
  time.sleep(.2)
 else:raise AssertionError("Independent worker did not complete transport")
 print("logistics V1 independently deployed worker completed a transport command using external SQL/broker URLs")'
