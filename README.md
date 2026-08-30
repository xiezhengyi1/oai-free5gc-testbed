# OAI + free5GC unified testbed

This repository compiles one strict YAML scenario into an immutable run directory and a
Docker Compose deployment for real OAI RFsim, free5GC, N6 applications, telemetry, and the
unified action gateway.

The Linux deployment layout is fixed for the first acceptance environment:

```text
/home/yyx/6gcore/
├── openairinterface5g/        # OAI, tag 2026.w35
├── free5gc/                   # free5GC core source repository
├── free5gc-compose/           # deployment/config repository, tag v4.1.0
└── oai-free5gc-testbed/       # this repository
```

The paths are still declared in every scenario. The compiler never guesses source roots,
container names, networks, DNNs, or targets.

## First Linux setup

Ubuntu 22.04 x86_64 is the acceptance host. Prepare the pinned upstream checkouts if they are
not already present, then copy this repository to its sibling path:

```bash
mkdir -p /home/yyx/6gcore
git clone --branch 2026.w35 --depth 1 \
  https://gitlab.eurecom.fr/oai/openairinterface5g.git \
  /home/yyx/6gcore/openairinterface5g
git clone --branch v4.1.0 --depth 1 \
  https://github.com/free5gc/free5gc-compose.git \
  /home/yyx/6gcore/free5gc-compose
```

`free5gc` and `free5gc-compose` are different repositories. The testbed reads configuration
only from `/home/yyx/6gcore/free5gc-compose`; the sibling `/home/yyx/6gcore/free5gc` checkout
is retained as the user's free5GC core source tree and is not version-checked by the testbed.

From the testbed repository, run:

```bash
cd /home/yyx/6gcore/oai-free5gc-testbed
bash scripts/bootstrap_host.sh
```

The bootstrap adds the current user to the `docker` group. Start a new login session once it
finishes. Copy `.env.example` to `.env`, set the PostgreSQL URL used by the sibling Multiagents
deployment, replace both action-gateway API keys, then continue:

```bash
cd /home/yyx/6gcore/oai-free5gc-testbed
. .venv/bin/activate
cp .env.example .env
# Edit .env before exporting it.
set -a; . ./.env; set +a
bash scripts/build_oai_images.sh
bash scripts/build_testbed_images.sh
testbed lock-images
testbed host-check --scenario scenarios/mvp/s1_single_ue_single_upf.yaml
testbed validate scenarios/mvp/s1_single_ue_single_upf.yaml
testbed render scenarios/mvp/s1_single_ue_single_upf.yaml --run-id smoke-001
testbed start scenarios/mvp/s1_single_ue_single_upf.yaml --run-id smoke-001
testbed status --run-id smoke-001
```

`MULTIAGENTS_DATABASE_URL` is consumed inside Docker, so the example uses
`host.docker.internal` and Compose maps it to the Linux host gateway. PostgreSQL must listen
on the host-facing interface, and `pg_hba.conf` must authorize only the `testbed_writer`
account and the declared `172.37.0.0/24` control network for the Multiagents database.

`render` copies the tagged free5GC base configuration from the explicitly declared sibling
repository into the run artifact, then applies the compiled PLMN, slice, DNN, N2/N3/N4/N6,
UPF, and subscriber settings. The generated Compose file only mounts files inside that run.

## Run artifacts

Every run lives at `artifacts/runs/<run-id>/`. Source YAML, compiled JSON, generated configs,
manifest, state transitions, logs, actions, receipts, snapshots, metrics, pcaps, and the final
report are scoped to the run id. A run id cannot be rendered over an existing manifest.

## Security and control ownership

Multiagents may submit policy actions. Project may submit resource or lifecycle actions. Only
the action gateway owns Docker/free5GC/OAI write adapters. Requests require an API key identity,
an existing run id, an immutable snapshot id, an explicit target, and a postcondition check.

Grafana is for humans. Agents consume the Snapshot API (Multiagents) or the Prometheus and
diagnostic contracts (project).
