#!/bin/sh
set -eu
cd "$(dirname "$0")/../../.."
compose() { docker compose -p logistics-go-test -f apps/logistics/compose.test.yml "$@"; }
probe() { docker run --rm --network logistics-go-test_default -v "$PWD/apps/logistics/tests:/tests:ro" node:24.13.0-alpine node /tests/probe.mjs "$1"; }
compose up -d --wait db broker
compose build api web
compose up -d api worker controller web
# Probe retry stays inside a container; the host only orchestrates Docker.
docker run --rm --network logistics-go-test_default node:24.13.0-alpine node -e 'for(let i=0;i<60;i++){try{const r=await fetch("http://api:8000/api/health/live");if(r.ok)process.exit(0)}catch{}await new Promise(r=>setTimeout(r,1000))}process.exit(1)'
probe prepare
compose stop broker
probe resume
sleep 2
probe broker-down
compose up -d --wait broker
probe broker-recovered
compose stop db
probe database-down
compose up -d --wait db
probe database-recovered
probe web
