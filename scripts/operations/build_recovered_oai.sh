#!/usr/bin/env bash
# Compile recovered OAI sources without changing running containers or image tags.
set -euo pipefail
umask 077
repo="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
source_root=$(realpath "${1:?Usage: build_recovered_oai.sh SOURCE NEW_BUILD_DIR ASN1C CPM_CACHE}")
build_dir=$(realpath -m "${2:?new build directory required}")
asn1c=$(realpath "${3:?verified asn1c executable required}")
cpm_cache=$(realpath "${4:?verified CPM cache required}")
test "$(hostname -s)" = ibn3090
test -x "$asn1c"
test -f "$source_root/openair3/NAS/NR_UE/ue_policy.c"
test -f "$source_root/openair3/NAS/NR_UE/ue_policy_service.c"
test ! -e "$build_dir"
test ! -e "$build_dir.logs"
awk '/MemAvailable:/ {if ($2 < 8388608) exit 1}' /proc/meminfo
read -r build_cpus build_jobs < <(python3 - "$repo/deployment/hosts/ibn3090/profile.json" <<'PY'
import json, sys
p = json.load(open(sys.argv[1]))
control, radio = set(p['control_cpus']), set(p['radio_cpus'])
assert control and not control & radio
print(','.join(map(str, sorted(control))), min(len(control), 8))
PY
)
mkdir -p "$build_dir" "$build_dir.logs"
git -C "$source_root" rev-parse HEAD > "$build_dir.logs/source-head.txt"
git -C "$source_root" rev-parse --show-toplevel > "$build_dir.logs/source-git-root.txt"
git -C "$source_root" diff --binary HEAD -- . > "$build_dir.logs/source-working-tree.patch"
# A GitHub checkout uses the TestBed parent Git; restored local copies may retain
# their original independent Git. Record actual input bytes in either layout.
python3 - "$source_root" "$build_dir.logs/source-files.sha256" <<'PY'
import hashlib, pathlib, sys
root = pathlib.Path(sys.argv[1])
rows = []
for path in sorted(root.rglob('*')):
    relative = path.relative_to(root)
    if {'.git', '.cpm'} & set(relative.parts) or not path.is_file():
        continue
    rows.append(f'{hashlib.sha256(path.read_bytes()).hexdigest()}  {relative.as_posix()}\n')
pathlib.Path(sys.argv[2]).write_text(''.join(rows))
PY
gcc-12 --version > "$build_dir.logs/compiler.txt"
taskset -c "$build_cpus" nice -n 19 cmake -S "$source_root" -B "$build_dir" -GNinja \
  -DCMAKE_C_COMPILER=/usr/bin/gcc-12 -DCMAKE_CXX_COMPILER=/usr/bin/g++-12 \
  -DCMAKE_BUILD_TYPE=RelWithDebInfo -DCMAKE_EXPORT_COMPILE_COMMANDS=ON \
  -DOAI_SIMU=ON -DOAI_RF_EMULATOR=ON -DNAS_BUILT_IN_UE=ON \
  -DE2_AGENT=OFF -DENABLE_TESTS=OFF -DAVX512=OFF -DAVX2=ON \
  -DASN1C_EXEC="$asn1c" -DCPM_SOURCE_CACHE="$cpm_cache" \
  > "$build_dir.logs/configure.log" 2>&1
taskset -c "$build_cpus" nice -n 19 cmake --build "$build_dir" \
  --target nr-softmodem nr-uesoftmodem rfsimulator params_libconfig dfts coding ldpc ldpc_orig \
  --parallel "$build_jobs" > "$build_dir.logs/build.log" 2>&1
(
  cd "$build_dir"
  sha256sum nr-softmodem nr-uesoftmodem libparams_libconfig.so libdfts.so \
    libcoding.so libldpc.so libldpc_orig.so librfsimulator.so
) > "$build_dir.logs/binaries.sha256"
printf 'OAI build completed; evidence: %s\n' "$build_dir.logs"
