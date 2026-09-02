#!/usr/bin/env bash
set -euo pipefail

repository_root=/home/yyx/6gcore/oai-free5gc-testbed
test "$(pwd -P)" = "$repository_root"

scenario_path=${1:?usage: bash scripts/start_scenario.sh SCENARIO_PATH RUN_ID}
run_id=${2:?usage: bash scripts/start_scenario.sh SCENARIO_PATH RUN_ID}

. .venv/bin/activate
set -a
. ./.env
set +a

exec testbed start "$scenario_path" --run-id "$run_id"
