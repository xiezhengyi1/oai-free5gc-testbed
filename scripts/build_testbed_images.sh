#!/usr/bin/env bash
set -euo pipefail

repository_root=/home/yinyuexi/xiezhengyi/oai-free5gc-testbed
test "$(pwd -P)" = "$repository_root"

docker pull docker:28.5.2-cli
DOCKER_CONFIG=/tmp/testbed-docker-config docker build -t oai-free5gc-testbed/control:0.1.0 \
  -f deployment/docker/control.Dockerfile .
DOCKER_CONFIG=/tmp/testbed-docker-config docker build -t oai-free5gc-testbed/traffic-sidecar:0.1.0 \
  -f deployment/docker/traffic-sidecar.Dockerfile .
DOCKER_CONFIG=/tmp/testbed-docker-config docker build -t oai-free5gc-testbed/app:0.1.0 \
  -f deployment/docker/app.Dockerfile .
DOCKER_CONFIG=/tmp/testbed-docker-config docker build -t oai-free5gc-testbed/link-emulator:0.1.0 \
  -f deployment/docker/link-emulator.Dockerfile .

docker pull mongo:4.4
for nf in amf ausf chf nef nrf nssf pcf smf udm udr upf webui; do
  docker pull "free5gc/$nf:v4.1.0"
done
docker pull prom/prometheus:v3.12.0
docker pull ghcr.io/google/cadvisor:v0.57.0
docker tag ghcr.io/google/cadvisor:v0.57.0 gcr.io/cadvisor/cadvisor:v0.57.0
docker pull grafana/grafana:13.1.0
