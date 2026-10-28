#!/usr/bin/env bash
# Rebuild the pinned server checkout; never starts or stops any container.
set -euo pipefail
base=${1:?Usage: build_standard_ue_policy.sh /absolute/path/to/xiezhengyi}
test "${base:0:1}" = /
export PATH="$base/ue-policy-work/go/bin:$PATH"
cd "$base/ue-policy-work/nas"
go test ./nasMessage
cd "$base/ue-policy-work/pcf"
go test ./internal/uepolicy ./internal/sbi/...
CGO_ENABLED=0 go build -o ../pcf-bin ./cmd/main.go
cd "$base/ue-policy-work/smf"
go test ./internal/context ./internal/sbi/processor
CGO_ENABLED=0 go build -o ../smf-bin ./cmd/main.go
cd "$base/ue-policy-work/amf"
go test ./internal/gmm ./internal/sbi/...
CGO_ENABLED=0 go build -o ../amf-bin ./cmd/main.go
cd "$base/ue-policy-work"
docker build -f "$base/oai-free5gc-testbed/deployment/docker/pcf-policy.Dockerfile" -t free5gc/pcf:v4.1.0-uepolicy .
docker build -f "$base/oai-free5gc-testbed/deployment/docker/smf-policy.Dockerfile" -t free5gc/smf:v4.1.0-uepolicy .
docker build -f "$base/oai-free5gc-testbed/deployment/docker/amf-policy.Dockerfile" -t free5gc/amf:v4.1.0-uepolicy .
cd "$base/openairinterface5g-build"
cmake --build cmake_targets/ue-policy-build --target nr-uesoftmodem nr-softmodem rfsimulator -j 8
docker build -f ue-policy.Dockerfile -t oaisoftwarealliance/oai-nr-ue:2026.w35-uepolicy .
docker build -f gnb-policy.Dockerfile -t oaisoftwarealliance/oai-gnb:2026.w35-uepolicy .
cd "$base/oai-free5gc-testbed"
.venv/bin/pytest -q tests/unit
docker build -f deployment/docker/control-refresh.Dockerfile -t oai-free5gc-testbed/control:uepolicy .
docker build -f deployment/docker/traffic-policy.Dockerfile -t oai-free5gc-testbed/traffic-sidecar:uepolicy .
cd "$base/Multiagents"
PYTHONPATH=src .venv/bin/pytest -q tests/test_testbed_integration.py tests/test_standard_ue_policy.py
