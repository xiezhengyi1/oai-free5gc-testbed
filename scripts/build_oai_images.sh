#!/usr/bin/env bash
set -euo pipefail

oai_source=/home/yinyuexi/xiezhengyi/openairinterface5g
test "$(git -C "$oai_source" describe --tags --exact-match)" = 2026.w35
test -z "$(git -C "$oai_source" status --porcelain)"
oai_root=/home/yinyuexi/xiezhengyi/openairinterface5g-build

DOCKER_CONFIG=/tmp/testbed-docker-config DOCKER_BUILDKIT=1 docker build --build-arg TARGETARCH=amd64 --target ran-build --tag ran-build:latest --file "$oai_root/docker/Dockerfile.build.ubuntu" "$oai_root"
DOCKER_CONFIG=/tmp/testbed-docker-config DOCKER_BUILDKIT=1 docker build --build-arg TARGETARCH=amd64 --target oai-gnb --tag oaisoftwarealliance/oai-gnb:2026.w35 --file "$oai_root/docker/Dockerfile.gNB.ubuntu" "$oai_root"
DOCKER_CONFIG=/tmp/testbed-docker-config DOCKER_BUILDKIT=1 docker build --build-arg TARGETARCH=amd64 --target oai-nr-ue --tag oaisoftwarealliance/oai-nr-ue:2026.w35 --file "$oai_root/docker/Dockerfile.nrUE.ubuntu" "$oai_root"
