#!/usr/bin/env bash
set -euo pipefail
repo="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
set -a
source "$repo/configs/hosts/ibn3090.env"
set +a
exec "$@"
