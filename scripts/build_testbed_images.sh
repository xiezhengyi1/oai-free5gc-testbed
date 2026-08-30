#!/usr/bin/env bash
set -euo pipefail

repository_root=/home/yyx/6gcore/oai-free5gc-testbed
test "$(pwd -P)" = "$repository_root"

docker pull docker:28.5.2-cli
docker build -t oai-free5gc-testbed/control:0.1.0 \
  -f deployment/docker/control.Dockerfile .
docker build -t oai-free5gc-testbed/traffic-sidecar:0.1.0 \
  -f deployment/docker/traffic-sidecar.Dockerfile .
docker build -t oai-free5gc-testbed/app:0.1.0 \
  -f deployment/docker/app.Dockerfile .
docker build -t oai-free5gc-testbed/link-emulator:0.1.0 \
  -f deployment/docker/link-emulator.Dockerfile .

docker pull mongo:4.4
for nf in amf ausf chf nef nrf nssf pcf smf udm udr upf webui; do
  docker pull "free5gc/$nf:v4.1.0"
done
docker pull prom/prometheus:v3.12.0
docker pull gcr.io/cadvisor/cadvisor:v0.57.0
docker pull grafana/grafana:13.1.0
