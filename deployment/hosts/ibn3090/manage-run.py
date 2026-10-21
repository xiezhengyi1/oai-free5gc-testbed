"""Run on ibn3090 to manage its prepared S2 testbed without deleting run state."""
from pathlib import Path
import argparse
import json
from testbed.orchestration.launcher import Launcher
from testbed.state.run_store import RunStore

parser = argparse.ArgumentParser()
parser.add_argument('action', choices=['start', 'resume', 'stop', 'status'])
args = parser.parse_args()
bed = Path('/home/xzy/testbed/oai-free5gc-testbed')
run = bed / 'artifacts/runs/ibn3090-s2-20261008'
if args.action == 'status':
    result = RunStore(run).current()
else:
    launcher = Launcher(run, compose_env_file=bed / '.env')
    result = getattr(launcher, args.action)()
print(json.dumps(result.model_dump(mode='json'), indent=2))
