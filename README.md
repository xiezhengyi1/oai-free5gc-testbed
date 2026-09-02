# OAI + free5GC 融合仿真环境

本项目在一台 Linux 服务器上使用 Docker Compose 组织 OAI gNB、OAI nrUE、free5GC、边缘/云应用、链路仿真和监控组件。项目把严格校验的 YAML 场景编译为独立运行目录，再按固定顺序完成核心网、RAN、UE、业务流和监控系统的启动。

当前固定版本如下：

| 组件            | 版本或要求                            |
| --------------- | ------------------------------------- |
| 宿主机          | Ubuntu 22.04 LTS x86_64，CPU 支持 AVX |
| OAI             | `2026.w35`                            |
| free5GC Compose | `v4.1.0`                              |
| gtp5g           | `v0.9.5`                              |
| Python          | `3.12`                                |
| Docker Compose  | `2.36.0` 及以上                       |

## 1. 服务器目录结构

所有目录必须位于 `/home/yyx/6gcore` 下，并保持同级：

```text
/home/yyx/6gcore/
├── openairinterface5g/        # OAI 源码，固定在 2026.w35
├── free5gc/                   # free5GC 核心源码；本项目不直接读取此目录
├── free5gc-compose/           # free5GC 部署与配置，固定在 v4.1.0
└── oai-free5gc-testbed/       # 本仿真环境
```

`free5gc` 和 `free5gc-compose` 是两个不同的目录。本项目从 `free5gc-compose/config` 和 `free5gc-compose/cert` 读取基础配置；`free5gc` 仅作为独立的核心网源码目录保留，不参与版本检查和运行时配置渲染。

所有场景文件都显式声明 OAI 和 free5GC Compose 的绝对路径。程序不会自动猜测或切换到其他目录。

## 2. 仿真环境包含什么

一次完整运行包含：

- free5GC：MongoDB、NRF、AMF、SMF、UPF、AUSF、NSSF、PCF、UDM、UDR、NEF、CHF 和 WebUI；
- OAI：基于 RFsim 的 gNB 和 nrUE；
- N6 业务：边缘应用、云应用、TCP/UDP/HTTP 流量；
- 链路仿真：云回传时延、抖动、丢包率和带宽限制；
- 可观测性：Prometheus、cAdvisor、Grafana、RAN Exporter、会话跟踪和快照服务；
- 控制入口：Action Gateway，用于接收策略、资源和生命周期动作。

启动阶段严格按以下状态推进：

```text
CREATED
  → CORE_READY
  → PFCP_READY
  → GNB_READY
  → UE_REGISTERED
  → PDU_READY
  → TRAFFIC_READY
  → TELEMETRY_READY
  → RUNNING
```

任一阶段失败时，运行状态会转为 `FAILED`，启动日志写入对应运行目录。

## 3. 首次构建

以下步骤只需要在服务器首次部署或固定版本发生变化时执行。

### 3.1 准备 OAI 和 free5GC Compose

如果服务器上还没有这两个仓库：

```bash
mkdir -p /home/yyx/6gcore

git clone --branch 2026.w35 --depth 1 \
  https://gitlab.eurecom.fr/oai/openairinterface5g.git \
  /home/yyx/6gcore/openairinterface5g

git clone --branch v4.1.0 --depth 1 \
  https://github.com/free5gc/free5gc-compose.git \
  /home/yyx/6gcore/free5gc-compose
```

如果仓库已经存在，则检出指定标签：

```bash
git -C /home/yyx/6gcore/openairinterface5g fetch origin tag 2026.w35
git -C /home/yyx/6gcore/openairinterface5g switch --detach 2026.w35

git -C /home/yyx/6gcore/free5gc-compose fetch origin tag v4.1.0
git -C /home/yyx/6gcore/free5gc-compose switch --detach v4.1.0
```

确认标签正确，并确认两个上游目录没有未提交修改：

```bash
git -C /home/yyx/6gcore/openairinterface5g describe --tags --exact-match
git -C /home/yyx/6gcore/free5gc-compose describe --tags --exact-match
git -C /home/yyx/6gcore/openairinterface5g status --short
git -C /home/yyx/6gcore/free5gc-compose status --short
```

前两条命令应分别输出 `2026.w35` 和 `v4.1.0`，后两条命令应没有输出。

### 3.2 放置本项目

将本项目完整上传或克隆到：

```text
/home/yyx/6gcore/oai-free5gc-testbed
```

后续所有构建和启动命令都从该目录执行：

```bash
cd /home/yyx/6gcore/oai-free5gc-testbed
```

初始化、一键启动和项目镜像构建脚本会检查当前物理路径，不能从其他目录执行。

### 3.3 初始化 Ubuntu 宿主机

执行：

```bash
cd /home/yyx/6gcore/oai-free5gc-testbed
bash scripts/bootstrap_host.sh
```

该脚本会完成以下工作：

1. 检查 Ubuntu 22.04 和 x86_64 架构；
2. 安装 Python 3.12、编译工具、内核头文件、网络工具和抓包工具；
3. 安装 Docker Engine、Buildx 和 Docker Compose 插件；
4. 检查 OAI `2026.w35` 与 free5GC Compose `v4.1.0` 标签；
5. 创建 `.venv` 并安装项目及开发依赖；
6. 加载 TUN、SCTP 内核模块；
7. 编译、安装并加载 gtp5g `v0.9.5`。

脚本会把当前用户加入 `docker` 用户组。执行完成后必须重新登录服务器，然后验证 Docker 权限：

```bash
docker version
docker compose version
```

两条命令都应直接成功，不能依赖 `sudo docker`。

### 3.4 配置环境变量

创建本地环境文件：

```bash
cd /home/yyx/6gcore/oai-free5gc-testbed
cp .env.example .env
chmod 600 .env
nano .env
```

`.env` 示例：

```dotenv
TESTBED_ROOT=/home/yyx/6gcore/oai-free5gc-testbed
OAI_ROOT=/home/yyx/6gcore/openairinterface5g
FREE5GC_COMPOSE_ROOT=/home/yyx/6gcore/free5gc-compose
MULTIAGENTS_DATABASE_URL=postgresql+psycopg://testbed_writer:replace-with-real-password@host.docker.internal:5432/multiagents
ACTION_GATEWAY_API_KEYS=multiagents:replace-with-strong-key,project:replace-with-strong-key
```

需要修改的关键项：

- `MULTIAGENTS_DATABASE_URL`：连接服务器上 Multiagents 使用的 PostgreSQL；
- `ACTION_GATEWAY_API_KEYS`：必须同时配置 `multiagents` 和 `project` 两个非空密钥；
- 三个路径变量：保持与本 README 的固定目录结构一致。

数据库密码中的特殊字符需要按 URL 规则编码。Action Gateway 密钥中不要使用逗号，因为逗号用于分隔两个调用方。

PostgreSQL 必须监听 Docker 容器可以访问的宿主机接口。`pg_hba.conf` 至少需要允许 `testbed_writer` 从控制网络 `172.37.0.0/24` 访问 `multiagents` 数据库，不要开放无关数据库和账号。

### 3.5 构建和拉取镜像

激活 Python 环境并加载配置：

```bash
cd /home/yyx/6gcore/oai-free5gc-testbed
. .venv/bin/activate
set -a
. ./.env
set +a
```

从 OAI `2026.w35` 源码构建 gNB 和 nrUE 镜像：

```bash
bash scripts/build_oai_images.sh
```

该脚本依次构建：

```text
ran-base:latest
ran-build:latest
oaisoftwarealliance/oai-gnb:2026.w35
oaisoftwarealliance/oai-nr-ue:2026.w35
```

构建项目自身镜像，并拉取 free5GC、MongoDB、Prometheus、cAdvisor 和 Grafana 镜像：

```bash
bash scripts/build_testbed_images.sh
```

最后把当前服务器上的镜像摘要写入镜像锁：

```bash
testbed lock-images
```

此命令会更新 `deployment/images.lock.json` 并把 `locked` 设置为 `true`。宿主机检查和一键启动都会核验这些摘要，因此必须在全部镜像准备完成后执行。

### 3.6 构建后检查

先验证最小场景：

```bash
testbed validate scenarios/mvp/s1_single_ue_single_upf.yaml
testbed host-check --scenario scenarios/mvp/s1_single_ue_single_upf.yaml
```

`host-check` 会检查：

- Linux x86_64 和 AVX；
- `/dev/net/tun`、SCTP 和 gtp5g `0.9.5`；
- Docker Engine 和 Docker Compose 版本；
- 宿主机路由是否与场景网段冲突；
- OAI 与 free5GC Compose 的标签和工作区清洁状态；
- 所有镜像是否存在并与镜像锁一致。

只有返回结果中的 `"passed": true` 才能启动场景。

## 4. 一键启动

完成首次构建后，从项目根目录执行一条命令即可启动完整仿真：

```bash
cd /home/yyx/6gcore/oai-free5gc-testbed
bash scripts/start_scenario.sh scenarios/mvp/s1_single_ue_single_upf.yaml mvp-s1-001
```

`start_scenario.sh` 会自动加载 `.venv` 和 `.env`，随后执行宿主机检查、场景渲染和分阶段启动。命令在整个环境进入 `RUNNING` 后返回。

`mvp-s1-001` 是本次运行的 `run-id`。每次创建新实验必须使用新的 `run-id`，例如：

```bash
bash scripts/start_scenario.sh scenarios/mvp/s1_single_ue_single_upf.yaml mvp-s1-002
bash scripts/start_scenario.sh scenarios/mvp/s2_single_ue_edge_cloud.yaml mvp-s2-001
```

同一台服务器同一时刻只能运行一个场景。不同运行仍会使用相同的容器名、宿主机端口和 Linux bridge 名称，不能靠更换 `run-id` 实现并行运行。开始新实验前，先按“停止、重启和清理”一节停止并清理旧运行。

当前内置场景：

| 场景文件                                         | 用途                                 |
| ------------------------------------------------ | ------------------------------------ |
| `scenarios/mvp/s1_single_ue_single_upf.yaml`     | 单 UE、单 gNB、单边缘 UPF 的最小闭环 |
| `scenarios/mvp/s2_single_ue_edge_cloud.yaml`     | 单 UE、边缘/云双 UPF 和云回传链路    |
| `scenarios/validation/s3_resource_pressure.yaml` | 资源压力验证                         |
| `scenarios/validation/s4_policy_change.yaml`     | 策略变更验证                         |
| `scenarios/advanced/s5_two_gnb_mobility.yaml`    | 双 gNB 移动性场景                    |

### 手动分步启动

需要检查生成内容时，可以不使用一键脚本：

```bash
cd /home/yyx/6gcore/oai-free5gc-testbed
. .venv/bin/activate
set -a
. ./.env
set +a

testbed validate scenarios/mvp/s1_single_ue_single_upf.yaml
testbed render scenarios/mvp/s1_single_ue_single_upf.yaml --run-id manual-s1-001
testbed start scenarios/mvp/s1_single_ue_single_upf.yaml --run-id manual-s1-001
```

`render` 会执行以下操作：

1. 固化源场景和场景哈希；
2. 从 `free5gc-compose` 复制基础配置和证书；
3. 写入 PLMN、切片、DNN、N2/N3/N4/N6、UPF 和订阅数据；
4. 生成 OAI gNB/nrUE 配置；
5. 生成业务流、Prometheus 和 Docker Compose 配置；
6. 创建不可覆盖的运行清单和初始状态。

## 5. 查看状态和服务

设置运行编号并加载环境：

```bash
cd /home/yyx/6gcore/oai-free5gc-testbed
. .venv/bin/activate
set -a
. ./.env
set +a
RUN_ID=mvp-s1-001
```

查看状态：

```bash
testbed status --run-id "$RUN_ID"
docker compose -f "artifacts/runs/$RUN_ID/generated/compose.yaml" ps
```

查看指定容器日志：

```bash
docker compose -f "artifacts/runs/$RUN_ID/generated/compose.yaml" logs --tail 200 oai-gnb-1
docker compose -f "artifacts/runs/$RUN_ID/generated/compose.yaml" logs --tail 200 oai-nrue-1
docker compose -f "artifacts/runs/$RUN_ID/generated/compose.yaml" logs --tail 200 free5gc-amf
docker compose -f "artifacts/runs/$RUN_ID/generated/compose.yaml" logs --tail 200 free5gc-smf
```

默认开放的宿主机端口：

| 地址                     | 服务           |
| ------------------------ | -------------- |
| `http://服务器地址:5000` | free5GC WebUI  |
| `http://服务器地址:3000` | Grafana        |
| `http://服务器地址:29090` | Prometheus     |
| `http://服务器地址:8081` | Snapshot API   |
| `http://服务器地址:8080` | Action Gateway |

健康检查示例：

```bash
curl -f http://127.0.0.1:8081/health
curl -f http://127.0.0.1:8080/health
```

运行完成后可执行烟雾检查：

```bash
python scripts/smoke_test.py "artifacts/runs/$RUN_ID"
```

烟雾检查要求运行状态为 `RUNNING`，并且最新快照中的业务流关联数据完整。

## 6. 停止、重启和清理

停止容器但保留容器、网络、卷和运行证据：

```bash
testbed stop --run-id "$RUN_ID"
```

删除该次运行的 Compose 卷并从相同场景重新启动：

```bash
testbed reset --run-id "$RUN_ID"
```

`reset` 会增加运行代次并保留状态历史。它适合重新运行同一个 `run-id`；新实验仍应创建新的 `run-id`。

导出运行日志、最新快照和最终报告：

```bash
testbed export --run-id "$RUN_ID"
```

完整删除该次运行创建的容器、网络和 Docker 卷：

```bash
docker compose -f "artifacts/runs/$RUN_ID/generated/compose.yaml" down --volumes
```

该命令会删除此运行的 MongoDB、Prometheus 和 Grafana 卷；运行目录中的配置、状态和日志不会被自动删除。

如果准备使用新的 `run-id` 启动下一个实验，必须先对旧运行执行上述 `down --volumes`，使固定 bridge 网段、容器名和宿主机端口得到释放。

## 7. 运行产物

每次运行都位于：

```text
artifacts/runs/<run-id>/
```

主要内容：

```text
source-scenario.yaml              # 本次运行使用的源场景
manifest.json                     # 版本、哈希和运行清单
current-state.json                # 当前状态
state.jsonl                       # 完整状态转换历史
generated/compose.yaml            # 最终 Docker Compose
generated/free5gc-config/         # 本次运行的 free5GC 配置
generated/oai-config/             # gNB 和 nrUE 配置
generated/subscribers.json        # 自动注册的订阅数据
generated/traffic-profiles.json   # 业务流定义
logs/startup.log                  # 启动失败时的 Compose 日志
metrics/                          # 指标数据
pcaps/                            # 抓包数据
snapshots.jsonl                   # 统一状态快照
```

统一快照中每个 slice 都包含显式的双向总带宽/保证带宽容量、当前分配负载和最差 flow KPI；每个 gNB 包含 CPU、内存、NR 总 PRB 容量与实测利用率；每个 UPF 包含 CPU/内存容量与 cAdvisor 利用率。

相同 `run-id` 的清单不能被新的 `render` 覆盖，避免实验配置和证据被静默替换。

## 8. 修改或新增场景

建议复制最接近的现有场景后修改：

```bash
cp scenarios/mvp/s1_single_ue_single_upf.yaml scenarios/mvp/my-scenario.yaml
nano scenarios/mvp/my-scenario.yaml
testbed validate scenarios/mvp/my-scenario.yaml
```

场景采用严格 Schema，未声明字段、错误版本、重复地址、重叠网段、无效 DNN/切片引用、错误业务端口或资源目标都会在启动前被拒绝。

修改场景时重点检查：

- `sources`：必须保持 Linux 服务器上的绝对路径；
- `versions`：OAI 为 `2026.w35`，free5GC Compose 为 `v4.1.0`，gtp5g 为 `v0.9.5`；
- `networks`：不能与服务器已有路由或其他 Docker 网络冲突；
- `plmn`、`slices`、`dnn`、UE 订阅和 UPF 用户地址池必须一致；
- `slices[].capacity` 必须显式声明 UL/DL 总带宽和保证带宽（Mbps），不从当前 flow 负载反推；
- `resources.containers` 必须覆盖场景中的 UPF、gNB、nrUE 和业务容器；
- `flows` 中 UDP 使用端口 `5202`，TCP 使用 `5201`，HTTP 使用目标服务声明的端口。

## 9. 常见问题

### Docker 权限不足

如果出现 `/var/run/docker.sock: permission denied`，说明当前登录会话还没有加载新的 `docker` 组。退出 SSH 后重新登录，再运行 `docker version`。

### 镜像锁未生成

如果 `host-check` 报告 `deployment/images.lock.json has not been locked`：

```bash
. .venv/bin/activate
testbed lock-images
```

### OAI 或 free5GC 源码检查失败

检查标签和本地修改：

```bash
git -C /home/yyx/6gcore/openairinterface5g describe --tags --exact-match
git -C /home/yyx/6gcore/openairinterface5g status --short
git -C /home/yyx/6gcore/free5gc-compose describe --tags --exact-match
git -C /home/yyx/6gcore/free5gc-compose status --short
```

本项目要求两个上游目录位于指定标签且工作区干净。请先自行保存或提交已有修改，再恢复固定版本。

### gtp5g 版本不匹配

```bash
modinfo -F version gtp5g
```

必须输出 `0.9.5`。否则重新执行 `bash scripts/bootstrap_host.sh` 安装固定版本。

### 网段冲突

`host-check` 会把场景网段与宿主机路由比较。出现 `host route conflicts` 时，修改场景内对应 CIDR 和固定 IP，然后重新执行 `testbed validate` 和 `testbed host-check`。

### 启动中途失败

先查看状态和自动收集的启动日志：

```bash
testbed status --run-id "$RUN_ID"
less "artifacts/runs/$RUN_ID/logs/startup.log"
```

再使用运行目录中的 Compose 文件查看失败服务：

```bash
docker compose -f "artifacts/runs/$RUN_ID/generated/compose.yaml" ps -a
docker compose -f "artifacts/runs/$RUN_ID/generated/compose.yaml" logs --tail 300
```

### 宿主机端口被占用

启动前确保 `5000`、`3000`、`29090`、`8080` 和 `8081` 没有被其他服务占用：

```bash
sudo ss -lntp | grep -E ':(5000|3000|29090|8080|8081)\\b'
```

## 10. 开发校验

修改 Python、模板或场景后执行：

```bash
cd /home/yyx/6gcore/oai-free5gc-testbed
. .venv/bin/activate
python -m pytest -q
python -m ruff check .
bash -n scripts/*.sh
```

项目不会自动修改 OAI 或 free5GC Compose 上游目录。每次运行使用的最终配置都写入自己的 `artifacts/runs/<run-id>/generated/` 目录。
