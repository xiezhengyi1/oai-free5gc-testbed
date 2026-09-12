# AM / URSP 正式仿真环境同步验收

验收日期：2026-09-09。目标：`yinyuexi@8.129.108.34` 上的 `s2-live-auto`，不是隔离环境。

## 本次完成范围

当前已实现的 SM / AM / NAS URSP 改动已同步到正式仿真环境，完成端到端验收，运行状态恢复为 `RUNNING`。

- 3 个 gNB、6 台 OAI UE、11 个 PDU 会话、11 条业务流。
- 6 台 UE 的当前 UE policy association 均为 `complete`，每台 UE 均有唯一的当前 AM association 和 UE policy association。
- 11 条流的会话关联均为 `complete`、`stale=false`，均有实际应用吞吐。TCP 上行业务按上行吞吐验收，不要求不存在的应用下行负载。
- URSP：`ue-5 / video-4k-stream-1` 经标准 NAS 下发，实际从 `embb` 切到 `urllc`，再恢复 `embb`；两次回执均为 `verified`。更新监控镜像后，整轮验收再次通过。
- AM：RFSP=64 已经 PCF → AMF → NGAP 下发到 gNB，并收到 gNB 的响应。验收范围为 `gnb_context_and_ngap_response`；`radio_mapping=none`，不声称已经无线重选。
- Multiagents：正式环境 6 台 UE × SM / AM / URSP 三类查询，18 项全部通过；返回真实关联 ID 和非空的当前 URSP。
- SM 与 AM/URSP 共存修复已部署：SM 导致 UE 重注册后，在新 association 上重新下发原 URSP、恢复 RFSP、刷新会话观测。此变更的实际 SM 联调在隔离环境通过；本次正式环境没有额外修改订阅 QoS 来重跑 SM 写操作。

最终视频流已恢复原 `embb` 路径。`ue-5` 的 RFSP 保留为验收值 64。

## 部署及代码

工作分支：`codex/standard-ue-policy`。原有用户改动已保留；没有执行 git reset、删除用户代码、推送远端仓库或更新用户正在 clone 的另一套 free5GC。

| 组件 | 本次功能提交 | 说明 |
| --- | --- | --- |
| Multiagents | `70dd97b` | 正式环境三类策略观测验收；已有策略适配仍保留 |
| oai-free5gc-testbed | `d576edc`、`1f9dd7d` | SM 重注册策略重绑定、迁移工具、快照连接复用 |
| PCF | `1d749c3`、`68bad98` | 关联生命周期、按服务 AMF 的唯一 NF ID 发现 |
| OAI | `4720f91` | 修复短生命周期线程命名竞态 |
| AMF | `b02b431` | 沿用已验收的 NAS UE policy / AM 实现 |
| NAS | `5bea0d7` | 沿用已验收的 UE policy NAS 支持 |

正式 Compose 中的 20 个策略相关服务已固定到带镜像内容 ID 的 `s2-live-20260909-*` 标签。后续开发复用 `:uepolicy` 标签不会自动替换正式版本。版本清单保存在运行目录 `ue-policy/deployment-manifest.json`。

验证：testbed 单元测试 54 项通过，Multiagents 本轮标准策略专项测试 6 项通过，PCF SBI / UE policy 包测试及本地编译通过。OAI UE/gNB 原生构建通过。

## 迁移中发现并处理的问题

1. 原正式环境的三个 UPF 在迁移前已经崩溃。保存了日志并重新启动，最终 11 个会话及业务均恢复；未声称已经从源码修复 UPF 原有崩溃原因。
2. Docker 数据盘空间不足曾导致 Prometheus WAL 写入失败。停止后将完整监控数据库复制到根盘绑定目录，成功回放 WAL，原命名卷仍保留。未清空历史数据库。
3. OAI 的父线程在短任务线程退出后调用 `pthread_setname_np`，触发 ESRCH 退出。改为子线程进入工作函数前命名，重新编译并验证 6 台 UE 启动。
4. AMF 重启后，持久化 PCF 存在旧 UE association。新关联原子地将同 SUPI/接入类型的旧关联标为 superseded，保留历史记录但不再作为当前可下发目标。
5. NRF 的 AMF 查询在附加 GUAMI 时观察到间歇性 HTTP 200 空结果。去掉多余 GUAMI、仅按当前服务 NF ID 查询后，连续 30 次均命中。PCF 仍严格检查唯一实例及 REGISTERED 的 Namf 服务，没有加入重试或备用 AMF 路径。NRF 内部导致空结果的根因未在本次证明。
6. 快照每次 Prometheus 查询都重建 HTTP 客户端。改为复用一个客户端，同环境 20 次查询从 4.638 秒降低至 0.386 秒；整轮正式验收再次通过。

## 备份与证据

服务器运行根目录：

`/home/yinyuexi/xiezhengyi/oai-free5gc-testbed/artifacts/runs/s2-live-auto`

- 完整迁移前备份：`migration-backups/20260909T105214Z`。含配置、原容器元信息、MongoDB dump、状态与运行文件等。包含敏感配置，仅在服务器私有目录保留，未装入本地验收证据包。
- 正式最终验收：`ue-policy/evidence/live-20260909T113506Z`。
- 前一轮正式验收：`ue-policy/evidence/live-20260909T112638Z`。
- Multiagents 正式查询：`ue-policy/evidence/multiagents-live-20260909T113224Z`。
- SM 重绑定联调：相邻 `phase2-isolated/ue-policy/evidence/sm-rebind-20260909T105021Z`。
- 镜像清单：`ue-policy/deployment-manifest.json`；迁移记录：`ue-policy/migration.json`。
- 原 Prometheus 卷：`testbed-s2-live-auto_prometheus-data`；新数据路径：`ue-policy/databases/prometheus`。

隔离的 `p2-*` 环境继续保留。正式环境入口仍为 action-gateway 8080、snapshot-builder 8081、webUI 5000；未要求 Multiagents 改接隔离端口。

截至本次检查，Docker 数据盘仍使用约 99%（约 40 GB 可用），根盘约 520 GB 可用。空间仍是运行风险，不能把本次数据库迁移视为 Docker 全局存储问题已解决。

## 尚未完成的扩展范围

以下已经纳入用户要求的后续范围，但**不属于本次同步已经交付的能力**：

1. URSP 在没有可复用会话时，触发 OAI UE 动态建立对应 DNN / S-NSSAI 的 PDU，并将会话成功或拒绝反馈给路由选择过程。
2. App-ID / FQDN 的标准描述符编解码、UE 侧应用身份及域名关联、规则匹配和验证。不能把网关的应用名称或静态 IP 列表直接冒充 UE 的标准 App-ID / FQDN 执行。
3. 切片订阅授权变更、UDM/AMF Allowed NSSAI 更新和重注册/会话约束的联动。AM policy 不能越过订阅权限任意授权切片，应将订阅管理与 AM policy 分开实现和审计。
4. RFSP 到实际无线策略的映射，以及多小区环境下由真实 RRC/无线过程完成的重选验证。现有 RFSP 上下文日志不足以证明这一点。

后续应继续使用隔离环境完成这些扩展，逐项获得协议与业务路径证据后再迁入已经固定版本的正式环境。当前结论是“现有实现同步成功”，不是“SM / AM / URSP 全部标准能力已完成”。
