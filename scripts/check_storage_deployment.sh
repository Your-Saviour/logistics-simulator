#!/bin/sh
# Exercise persistent packaging with a fresh, disposable project and volumes.
# Existing storage-v1 deployments and credentials are never attached.
set -eu
project=simu-storage-startup-$(date +%s)
manifest=apps/storage/compose.v1.yaml
mkdir -p .superpowers/sdd/simu-2-storage
envfile=$(mktemp .superpowers/storage-startup.XXXXXX)
work() { python3 scripts/docker_guard.py --minimum-gib "${SIMULATOR_MINIMUM_FREE_GIB:-20}" --label storage-startup -- docker "$@"; }
cleanup() { docker compose -p "$project" --env-file "$envfile" -f "$manifest" --profile local down --volumes; rm -f "$envfile"; }
trap cleanup EXIT HUP INT TERM
python3 - "$envfile" <<'PY'
import secrets,sys
from pathlib import Path
p=Path(sys.argv[1]);p.chmod(0o600)
p.write_text('STORAGE_USERNAME=operator\nSTORAGE_PASSWORD='+secrets.token_hex(24)+'\nSTORAGE_PORT=0\nAUTONOMOUS_WAREHOUSE=false\n')
PY
work tag logistics-simulator:storage-migrated logistics-simulator:storage-v1
work tag logistics-simulator:storage-web-migrated logistics-simulator:storage-v1-web
work compose -p "$project" --env-file "$envfile" -f "$manifest" --profile local up -d --no-build --wait --wait-timeout 120
work run --rm --network "${project}_default" --env-file "$envfile" logistics-simulator:bootstrap python -c '
import os,time,httpx
with httpx.Client(base_url="http://storage-web",auth=(os.environ["STORAGE_USERNAME"],os.environ["STORAGE_PASSWORD"]),timeout=5) as client:
    deadline=time.monotonic()+45
    while time.monotonic()<deadline:
        try:
            if client.get("/api/health/ready").status_code==200:
                client.get("/").raise_for_status();client.get("/api/warehouse").raise_for_status()
                print("storage V1: fresh persistent packaging starts ready without manual restarts")
                break
        except httpx.HTTPError: pass
        time.sleep(.2)
    else: raise AssertionError("Persistent packaging failed readiness")'
for service in storage-api storage-worker storage-controller; do
 container=$(docker compose -p "$project" --env-file "$envfile" -f "$manifest" ps -q "$service")
 [ "$(docker inspect --format '{{.RestartCount}}' "$container")" -eq 0 ]
done
# The optional local dependencies must also permit externally addressed roles.
work compose -p "$project" --env-file "$envfile" -f "$manifest" config --quiet
echo 'storage V1: startup ordering, zero backend restarts and external profile configuration passed'
