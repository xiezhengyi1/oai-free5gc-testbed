"""Package the native OAI build and select it in the two prepared testbed runs."""
from pathlib import Path
import hashlib
import json
import shutil
import subprocess
import yaml

BASE = Path('/home/xzy/testbed')
SOURCE = BASE / 'openairinterface5g-build'
BUILD = SOURCE / 'cmake_targets/ibn3090-build'
RUNTIME = BASE / 'runtime/avx2-20261008'
RUNTIME.mkdir(parents=True, exist_ok=True)
LIBRARIES = ['libparams_libconfig.so', 'libdfts.so', 'libcoding.so',
             'libldpc.so', 'libldpc_orig.so', 'librfsimulator.so']
for name in ['nr-softmodem', 'nr-uesoftmodem', *LIBRARIES]:
    shutil.copy2(BUILD / name, RUNTIME / name)
    subprocess.run(['strip', '--strip-debug', str(RUNTIME / name)], check=True)

images = {}
base_digests = {}
for role, binary in [('gnb', 'nr-softmodem'), ('nr-ue', 'nr-uesoftmodem')]:
    original = 'oaisoftwarealliance/oai-' + role + ':2026.w35-uepolicy'
    inspection = json.loads(subprocess.check_output(['docker', 'image', 'inspect', original]))[0]
    base_digests[original] = inspection['Descriptor']['digest']
    name = 'oai-free5gc-testbed/oai-' + role + ':20261008-avx2'
    dockerfile = RUNTIME / ('Dockerfile.' + role)
    dockerfile.write_text(
        'FROM ' + original + '\n'
        + 'LABEL testbed.base.digest="' + base_digests[original] + '"\n'
        + 'COPY ' + binary + ' /opt/oai-' + role + '/bin/' + binary + '\n'
        + 'COPY ' + ' '.join(LIBRARIES) + ' /usr/local/lib/\n'
        + 'RUN ldconfig\n'
    )
    subprocess.run(['docker', 'build', '--network=none', '-f', str(dockerfile),
                    '-t', name, str(RUNTIME)], check=True)
    result = subprocess.run(['docker', 'run', '--rm', '--entrypoint',
                             '/opt/oai-' + role + '/bin/' + binary, name, '--help'],
                            text=True, capture_output=True)
    (RUNTIME / (role + '-help.log')).write_text(result.stdout + result.stderr)
    # The gNB help path calls exit_fun (255); the UE help path returns 0.
    assert result.returncode == {'gnb': 255, 'nr-ue': 0}[role], (role, result.returncode)
    assert 'Help for section' in result.stdout
    images[original] = name

for relative in ['experiments/am-rfsp-20261008/run',
                 'oai-free5gc-testbed/artifacts/runs/ibn3090-s2-20261008']:
    path = BASE / relative / 'generated/compose.yaml'
    compose = yaml.safe_load(path.read_text())
    for service in compose['services'].values():
        if service['image'] in images:
            service['image'] = images[service['image']]
            service['volumes'] = [volume for volume in service['volumes']
                                  if '/am-rfsp-20261008/bin/' not in volume]
    path.write_text(yaml.safe_dump(compose, sort_keys=False))

manifest = {
    'host': 'ibn3090', 'source_commit': subprocess.check_output(
        ['git', '-C', str(SOURCE), 'rev-parse', 'HEAD'], text=True).strip(),
    'source_diff_sha256': hashlib.sha256(subprocess.check_output(
        ['git', '-C', str(SOURCE), 'diff', 'HEAD'])).hexdigest(),
    'build_flags': {'AVX512': False, 'AVX2': True, 'compiler': 'gcc-12'},
    'base_image_manifest_digests': base_digests,
    'binaries_sha256': {name: hashlib.sha256((RUNTIME / name).read_bytes()).hexdigest()
                       for name in ['nr-softmodem', 'nr-uesoftmodem', *LIBRARIES]},
    'images': {new: json.loads(subprocess.check_output(['docker', 'image', 'inspect', new]))[0]['Id']
               for new in images.values()},
}
(RUNTIME / 'build-manifest.json').write_text(json.dumps(manifest, indent=2))
print(json.dumps(manifest, indent=2))
