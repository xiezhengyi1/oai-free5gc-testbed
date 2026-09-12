# AM / URSP 二期实现与验收（2026-09-09）

## 交付范围

这是实际 PCF—AMF—OAI UE NAS 链路的有限标准子集，不是一期间接 policy-state 模拟，也不是完整 Release 17 一致性认证。

URSP：Multiagents → action-gateway 订阅校验 → PCF 独立 UE policy association → Namf N1N2MessageTransfer（UPDP）→ AMF 安全保护的 DL NAS TRANSPORT → OAI UE 解析、持久化和分类 → UL NAS MANAGE UE POLICY COMPLETE → AMF → PCF。UE 根据 RSD 选择已经建立且 DNN/S-NSSAI 匹配的 PDU session；traffic-sidecar 只把业务 socket 绑定到 UE 返回的接口，不在 sidecar 重做 URSP 决策。

AM：使用真正的 AM policy association，PCF notification → AMF → NGAP UEContextModificationRequest（Index to RFSP）→ gNB 上下文更新及 Response。AM association 与 UE policy association 分开管理。RFSP 不等于带宽、QoS 或切片订阅开关；单频 RFsim 未实现 RFSP 到频段/RAT 重选映射。

允许的 URSP 描述符：IPv4 远端 CIDR、TCP/UDP 协议、远端单端口、match-all；RSD 支持优先级、DNN、显式 SST+SD。最多 32 条规则、每条 8 个 RSD、一个 HPLMN 和一个 UPSC。UPSC 是 section 标识，不是版本；管理接口另有单调 version 和 CAS expectedVersion，NAS 用 PTI 关联事务。

不支持：应用 OS/App ID、FQDN、IPv6、Ethernet、SSC/ATSSS、漫游多 PLMN、多 section、由规则动态创建 PDU session、CM-IDLE 分页递送、完整 UE-policy notification/终止回调、独立 UE state indication 的全部过程、RFSP 驱动真实切换。未实现项应拒绝或明确不可验收，不能报告成功。当前 AM 管理入口只开放 RFSP；allowed/target NSSAI 是真实上下文/订阅信息，不把它们伪造成 PCF 可任意增加的切片权限。

## 版本与目录

服务器根目录：`/home/yinyuexi/xiezhengyi`。

| 组件 | 使用的基线 | 改造目录 |
|---|---|---|
| PCF | v1.4.0 / f74d8fda（配套 free5GC v4.1.0） | `ue-policy-work/pcf` |
| AMF | v1.4.0 / f2a5096a（配套 free5GC v4.1.0） | `ue-policy-work/amf` |
| NAS Go 依赖 | v1.2.0 | `ue-policy-work/nas`，AMF go.mod 本地 replace |
| OAI UE/gNB | 2026.w35 / b77bf169 | `openairinterface5g-build` |
| 网关、流量、快照 | 原改动检查点 d16d95f | `oai-free5gc-testbed` |
| 智能体适配 | 原改动检查点 1541a9c | `Multiagents` |

用户正在 clone 的 `free5gc` 是 v4.2.3 后续提交 9cc5c810，与现有 v4.1.0 镜像不匹配，未混用、未改写。`free5gc-compose-v4.1.0-testbed` 基础仓库未改；覆盖配置仅写入新测试床 run。所有改造独立提交在 `codex/standard-ue-policy` 分支；最终提交和镜像 ID 见同目录版本清单。

## 已验证结果

- `phase2-isolated`，UE `ue-5`，实际 SUPI `imsi-208930000000009`。
- 同一 TCP/8080 业务：embb / PDU 1 / SST 1 SD 000001 → urllc / PDU 2 / SST 2 SD 000001；随后 Multiagents 正式模型又成功切回。
- 网关同时要求 PCF Complete、正确 PTI/UPSC/规则、UE 路由读回、实际 session DNN/S-NSSAI/IP/TEID/UPF、新采样窗口和正向业务吞吐，才返回 verified。
- RFSP=64 和后续 65 到达 gNB；AMF 收到 UEContextModificationResponse。验收范围为 `gnb_context_and_ngap_response`，`radio_mapping=none`。
- 抓包独立观察到 TCP/8080 在 N3 `10.230.32.30`、`.31` 两个 UPF 上的双向 GTP-U。原始 capture 的 UE IP 为 `10.231.60.2`、`10.231.61.2`，TEID 见证据。重注册后 IP/TEID 可变化，不将旧抓包字段冒充当前值。
- 5 类负例：未订阅 DNN、未订阅切片、旧版本、重复 precedence、未知 SUPI，均被拒绝且不改变已完成的 PCF version。
- 测试床 51 项单测；Multiagents 最终 17 项集成/翻译测试；PCF codec/store 测试；AMF 相关包和 NAS message 测试通过。OAI 全量 UE/gNB 目标构建通过；独立 C 解析器通过 ASan/UBSan、金向量、截断和逐位扰动测试。不是完整上游全量测试集。

交付前额外覆盖了空切片：业务全部迁出后，该切片时延、抖动、丢包率为 null（无观测），不是 0；Multiagents 接受这一明确语义且不生成伪数值指标。最终正式适配器复验 `multiagents-20260909T103059.914265Z/` 两项操作均成功，包含迁回后的拓扑/切片归属快照。

证据目录：`artifacts/runs/phase2-isolated/ue-policy/evidence/`。保留首轮 AM 失败记录（gNB decoder 未放行 procedure 40）与修复后的成功记录；不能只保留成功结果。`20260909T100430.406690Z/` 是双项成功验收，`multiagents-20260909T101030.256583Z/` 是正式适配器两操作反馈。`gtpu-path-summary.json` 从原始 pcap 解码得出。`any` 抓包可能重复，且存在内核丢包，不能用于精确吞吐统计。NAS 有安全保护，抓包不是独立的明文 NAS 一致性解码认证。

## 隔离约束

所有新容器使用 `p2-` 前缀，Compose 项目 `testbed-phase2-isolated`；网络使用 `10.230.30–38.0/24`，UE 地址池 `10.231.60/61.0/24`，独立 MongoDB/Postgres/Prometheus 数据。宿主只绑定 loopback：gateway 18080、snapshot 18081、webUI 15000、Prometheus 39090。凭据在 run 下 `ue-policy/credentials.json`，不可提交或公开。

现有 `s2-live-auto` 没有停止或重启。发现的原环境 UPF nil-pointer 崩溃早于本次部署，未擅自修复。Docker 数据磁盘已满；新数据库使用 run 所在根盘 bind mount，未清理用户镜像、卷或日志。新 cAdvisor 限制采集项并禁用本地健康探针代理，未改旧监控。

隔离是网络、数据库、配置、端口和容器层面的；仍共享宿主 CPU/内存/内核与 Docker daemon，不是物理资源隔离。

## 构建与运行

在现有匹配源码和已配置 OAI 构建目录上：

```bash
cd /home/yinyuexi/xiezhengyi/oai-free5gc-testbed
bash scripts/build_standard_ue_policy.sh /home/yinyuexi/xiezhengyi
```

脚本只构建，不自动替换运行容器。OAI 使用 GCC 12.4、`/opt/asn1c/bin/asn1c`、独立目录 `cmake_targets/ue-policy-build`，配置参数为 `-GNinja -DOAI_SIMU=ON -DOAI_RF_EMULATOR=ON -DNAS_BUILT_IN_UE=ON -DE2_AGENT=OFF -DENABLE_TESTS=OFF`；复用 `.cpm` 依赖缓存。具体 C/C++ 编译器位于根目录的 `gcc-12.4/bin/`。PCF/AMF 使用 `ue-policy-work/go/bin/go`（1.24.2）。

现有隔离 run 的复验：

```bash
.venv/bin/python scripts/verify_ue_policy_live.py
.venv/bin/python scripts/verify_ue_policy_rejections.py
cd ../Multiagents
PYTHONPATH=src .venv/bin/python scripts/verify_standard_ue_policy.py
```

前两种正例会改变隔离 UE 的策略和业务路径；负例不应改变版本。每次正例保存独立时间目录。`audit_ue_policy_isolated.py` 对人工启动的隔离 run 做一次回溯就绪验收并记录 RunStore，不能当作通用启动器。

新建配置使用 `scripts/render_ue_policy_isolated.py <source-scenario.yaml> --run-id phase2-isolated --ue ue-5`，输出必须尚不存在。此脚本固定使用本页 p2 前缀及地址/端口，不能同时再建第二套 p2 环境。不要在现有 run 上重新渲染。

首次启动顺序：独立 policy-postgres/Mongo/webUI → `ue_policy_storage` 初始化 UE policy 目录所有权和 Prometheus 目录 → 按 generated/subscribers.json 向 **15000** 的独立 webUI 写入订阅 → 其余核心网和两个 UPF → 应用/gNB → UE 并确认双 PDU → 在 action-gateway 容器环境运行 `python -m testbed.orchestration.ue_policy_bootstrap`，等 PCF Complete → traffic-sidecar、session-tracker、Prometheus/cAdvisor/ran-exporter → snapshot-builder/action-gateway。所有 docker compose 命令必须明确 `-f artifacts/runs/phase2-isolated/generated/compose.yaml`。当前验收环境已经运行，无需重做以上步骤。

**不要对隔离 run 使用旧的通用 start/resume/reset API**：上游 Launcher/Readiness 仍含默认容器名和 5000 端口，本次未扩大改造为通用多环境编排器。只使用显式 Compose 文件和本页专用脚本。需要停止隔离环境时可 `docker compose -f artifacts/runs/phase2-isolated/generated/compose.yaml stop`；该操作不删除证据和数据库。不要执行带 `-v` 的 down、清理卷或删除 run。

## 持久化与恢复边界

PCF UE policy 保存 association、版本、PTI、请求、payload、递送结果；UE 保存标准二进制规则并在启动时读取。保存采用原子替换。T3501 超时重传同一事务，失败显式记为 timeout，不伪造 UE 确认。

尚未完成进程在 pending 期间崩溃后的自动事务续传；PCF 的上游 AM association 本身仍是内存状态。跨 AMF/PCF 崩溃应做受控重新注册并重新查询 association，不能继续用旧 ID。动态重注册后需重新采集 session-tracker（其上游默认是会话齐全后停止发现），本次只验收预建立双会话内的规则切换。不能据磁盘文件存在声称完整故障恢复已验收。

NAS 的 RegistrationRequest Go 类型中手工补充了生成器漏掉的半字节 PayloadContainerType，重新生成 NAS 类型时必须保留扩展及 roundtrip 测试，详见 NAS 仓库 `UE_POLICY_EXTENSION.md`。

## 标准依据

- [3GPP TS 24.501 v17.15（含 Annex D UE policy delivery）](https://www.etsi.org/deliver/etsi_ts/124500_124599/124501/17.15.00_60/ts_124501v171500p.pdf)
- [3GPP TS 24.526 v17.8（URSP 编码与选择）](https://www.etsi.org/deliver/etsi_ts/124500_124599/124526/17.08.00_60/ts_124526v170800p.pdf)
- Npcf_UEPolicyControl 使用 free5GC OpenAPI v1.2.1 对应 TS 29.525 模型；AM callback 与 NGAP 分别沿现有 TS 29.507、TS 38.413 实现扩展。
