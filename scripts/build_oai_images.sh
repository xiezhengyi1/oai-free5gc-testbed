#!/usr/bin/env bash
set -euo pipefail

oai_root=/home/yyx/6gcore/openairinterface5g
test "$(git -C "$oai_root" describe --tags --exact-match)" = 2026.w35
test -z "$(git -C "$oai_root" status --porcelain)"

docker build --target ran-base --tag ran-base:latest \
  --file "$oai_root/docker/Dockerfile.base.ubuntu" "$oai_root"
docker build --target ran-build --tag ran-build:latest \
  --file "$oai_root/docker/Dockerfile.build.ubuntu" "$oai_root"
docker build --target oai-gnb --tag oaisoftwarealliance/oai-gnb:2026.w35 \
  --file "$oai_root/docker/Dockerfile.gNB.ubuntu" "$oai_root"
docker build --target oai-nr-ue --tag oaisoftwarealliance/oai-nr-ue:2026.w35 \
  --file "$oai_root/docker/Dockerfile.nrUE.ubuntu" "$oai_root"
