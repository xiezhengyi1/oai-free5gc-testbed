from pathlib import Path
import json
import subprocess
import sys
import time

BASE=Path('/home/xzy/testbed')
BED=BASE/'oai-free5gc-testbed'
RUN=BASE/'experiments/am-rfsp-20261008/run'
sys.path.insert(0,str(BED))
from testbed.adapters.free5gc.subscriber_adapter import SubscriberAdapter
import httpx
compose=['docker','compose','-f',str(RUN/'generated/compose.yaml')]
core=['mongodb','free5gc-nrf','free5gc-ausf','free5gc-nssf','free5gc-pcf','free5gc-udm',
      'free5gc-udr','free5gc-amf','free5gc-smf','free5gc-webui','free5gc-chf',
      'amr-free5gc-upf-slice-1','amr-free5gc-upf-slice-2','amr-video-4k-app']
subprocess.run(compose+['up','-d',*core],check=True)
time.sleep(15)
for row in json.loads((RUN/'generated/subscribers.json').read_text()):
    SubscriberAdapter('http://127.0.0.1:25000').upsert(row)
started_at = time.time()
subprocess.run(compose+['up','-d','cu','du0','ue'],check=True)
deadline=time.monotonic()+150
while time.monotonic()<deadline:
    stats=RUN/'runtime/cu/nrRRC_stats.log'
    if stats.exists() and stats.stat().st_mtime >= started_at and stats.read_text().count('status established')==2:
        break
    time.sleep(2)
assert stats.stat().st_mtime >= started_at and stats.read_text().count('status established')==2, 'AM UE did not establish both sessions'
subprocess.run(compose+['up','-d','du1'],check=True)
time.sleep(8)
print('AM_READY',flush=True)
