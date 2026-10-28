#!/usr/bin/env bash
set -euo pipefail
repo="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$repo"
revision="${1:-recovery-20261028}"
mkdir -p logs/build
docker build --network=none --pull=false --build-arg BASE=oai-free5gc-testbed/control:lifecycle-macstats-20261017 -f deployment/docker/recovery.Dockerfile -t "mergedsystem/testbed-control:$revision" . > logs/build/control-recovery.log 2>&1
docker build --network=none --pull=false --build-arg BASE=oai-free5gc-testbed/traffic-sidecar:lifecycle-http-success-20261018 -f deployment/docker/recovery.Dockerfile -t "mergedsystem/testbed-traffic:$revision" . > logs/build/traffic-recovery.log 2>&1
docker build --network=none --pull=false --build-arg "TRAFFIC_BASE=mergedsystem/testbed-traffic:$revision" -f deployment/docker/recovery-app.Dockerfile -t "mergedsystem/testbed-app:$revision" . > logs/build/app-recovery.log 2>&1
