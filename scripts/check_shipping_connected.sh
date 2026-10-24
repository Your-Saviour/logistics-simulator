#!/bin/sh
# Disposable two-federate transport acceptance; controlled peers are fixtures.
set -eu
manifest=deploy/generated/simu5-shipping-connected.json
artifacts=.superpowers/sdd/simu-5-shipping
mkdir -p "$artifacts"
work() { python3 scripts/docker_guard.py --wait --minimum-gib "${SIMULATOR_MINIMUM_FREE_GIB:-20}" --label shipping-connected -- docker "$@"; }
python3 scripts/shipping_connected_compose.py
cleanup() {
    result=$?
    trap - EXIT HUP INT TERM
    docker compose -p simu5-shipping-connected -f "$manifest" logs --no-color > "$artifacts/connected-services.log" 2>&1 || true
    docker compose -p simu5-shipping-connected -f "$manifest" cp shipping-peer:/control/verified.json "$artifacts/native-verification.json" >/dev/null 2>&1 || true
    docker compose -p simu5-shipping-connected -f "$manifest" cp shipping-peer:/control/peer-state.json "$artifacts/native-peer-state.json" >/dev/null 2>&1 || true
    if work compose -p simu5-shipping-connected -f "$manifest" down --volumes; then
        :
    else
        cleanup_result=$?
        if [ "$result" -eq 0 ]; then result=$cleanup_result; fi
    fi
    exit "$result"
}
trap cleanup EXIT HUP INT TERM
if [ "${SHIPPING_CONNECTED_REUSE_IMAGES:-0}" != 1 ]; then
    work build -t logistics-simulator:bootstrap .
    work build -t logistics-simulator:simu5-shipping-adapter -f apps/adapter/Dockerfile .
    work build -t "${SHIPPING_CONNECTED_IMAGE:-logistics-simulator:simu5-shipping}" -f apps/shipping/Dockerfile .
fi
work compose -p simu5-shipping-connected -f "$manifest" up -d shipping-db shipping-broker shipping-helics-broker shipping-adapter shipping-peer shipping-api shipping-worker shipping-controller
work compose -p simu5-shipping-connected -f "$manifest" run --rm shipping-verify lifecycle
work compose -p simu5-shipping-connected -f "$manifest" restart shipping-adapter
work compose -p simu5-shipping-connected -f "$manifest" run --rm shipping-verify restart
