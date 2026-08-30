#!/usr/bin/env bash
set -euo pipefail

test "$(uname -s)" = Linux
test "$(uname -m)" = x86_64
test "$(pwd -P)" = /home/yyx/6gcore/oai-free5gc-testbed
. /etc/os-release
test "$ID" = ubuntu
test "$VERSION_ID" = 22.04
test -d /home/yyx/6gcore/openairinterface5g
test -d /home/yyx/6gcore/free5gc

sudo apt-get update
sudo apt-get install -y ca-certificates curl software-properties-common
sudo add-apt-repository -y ppa:deadsnakes/ppa
sudo apt-get update
sudo apt-get install -y build-essential git iproute2 iputils-ping jq kmod \
  linux-headers-"$(uname -r)" python3.12 python3.12-dev python3.12-venv tcpdump

sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
  -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $VERSION_CODENAME stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo usermod -aG docker "$(id -un)"

git -C /home/yyx/6gcore/openairinterface5g describe --tags --exact-match | grep -Fx v2.4.0
git -C /home/yyx/6gcore/free5gc describe --tags --exact-match | grep -Fx v4.2.3
test -z "$(git -C /home/yyx/6gcore/openairinterface5g status --porcelain)"
test -z "$(git -C /home/yyx/6gcore/free5gc status --porcelain)"

python3.12 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e '.[dev]'

sudo modprobe tun
sudo modprobe sctp
gtp5g_build_dir="$(mktemp -d)"
git clone --branch v0.9.5 --depth 1 https://github.com/free5gc/gtp5g.git "$gtp5g_build_dir"
make -C "$gtp5g_build_dir"
sudo make -C "$gtp5g_build_dir" install
sudo modprobe gtp5g
