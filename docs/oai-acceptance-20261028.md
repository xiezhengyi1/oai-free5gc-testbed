# 重建 OAI 镜像真实功能验收

**通过本次 RFsim 场景的功能验收。** 本轮场景 `oai-acceptance-20261028-4` 使用重建的 UE/gNB 镜像和 `oai-acceptance-20261028-v4` Python 版本，现已恢复并停止。后续 HTTP 服务端修复及当前运行状态见 [HTTP 修复验收](http-latency-validation-20261028.md)。本轮完整结果、镜像 ID、容器身份、快照和证据哈希见 [结构化报告](oai-acceptance-20261028.json)；源码及构建比较见 [构建记录](oai-rebuild-20261028.md)。

## 实测结果

场景为 1 gNB、2 UE、2 UPF、4 条预建立 PDU 会话、6 条 HTTP/TCP/UDP 业务流。UE1 的 UDP 为操作对象，UE2 为保护对象。验收前将 UE1 的 RFSP 从初始值 0 初始化为 64；闭环恢复至验收基线 64，UE2 始终保持 0。

| 项目 | 结果与证据 |
|---|---|
| 注册与多 PDU | 两台 UE 各建立 `mec`、`mecalt` 两条会话，NAS 初始策略 Complete；四条会话全程保持原身份、IP 和 TEID |
| URSP | 目标 UDP 经 NAS 策略从 PDU1/`mec`/edge UPF 转到 PDU2/`mecalt`/alternate UPF，再恢复；实际收发持续，其他业务保留原路由 |
| RFSP | `64→65→64`，PCF/AMF 下发后均有 gNB 的 NGAP 应答；`radio_mapping=none` |
| QoS 新增与修改 | 目标 UDP 从默认 QFI1/5QI9 新增 QFI2/DRB3，5QI `1→2`；同 PDU 内 TCP/HTTP 保持 QFI1/5QI9/DRB1 |
| UPF 实际配置 | UL/DL SDF 的应用 IP、端口 5202、QER 引用及 QFI 一致；内核 QER 的双向 MBR=2 Mbps、GBR=0.5 Mbps |
| QoS 删除与恢复 | 通过带期望状态与明确 owned IDs 的原生 scoped restore 删除新增规则；UE 日志确认释放 DRB3，gNB 随后收到 RRCReconfigurationComplete |
| 保护与资源恢复 | UE2 策略、会话和内核规则保持不变；最终两套 UPF 各 4 PDR、4 FAR、4 QER、4 URR，所有返回属性字节及 ID 与基线完全一致；四条会话回到原状态 |
| 反向请求 | 未订阅 DNN、未订阅切片、过期版本、重复优先级、错误调用主体、未知 UE 共六项均拒绝，原生策略未变 |
| 最终健康 | 三个连续窗口中六条流收包数均增长，关联完整、新鲜、availability=1；验收期间 14 个相关容器未重建或重启，应用 CPU 配额保持 1 |
| 源码与回归 | Linux **132 项通过**；Gateway、快照、session-tracker、两个 sidecar 和应用共六个容器，各 93 份 Python 源码与宿主一致 |

最后窗口 UDP 双向约 1.97 Mbps，TCP 上行约 0.993 Mbps，HTTP 下行约 0.170–0.175 Mbps。HTTP 延迟约 54.5–56.2 ms，高于场景声明的 20 ms；本报告验收的是功能执行和恢复，**不表示业务 SLA 已满足**。

后续通过隔离回环和真实路径 ACK 对照，定位出主要额外延迟来自 HTTP 响应头/正文分写与 TCP 等待的配合，见 [HTTP 延迟诊断](http-latency-diagnosis-20261028.md)。原业务实现未改，诊断数据不替换本轮验收结果。

## 发现并修复的问题

- 备用切片无流量时，QoS 聚合对空列表调用 `min()` 导致快照任务退出；现在没有需求或测量时保留空值。
- 原解析器只识别 `assigned DRB`，漏掉真实 `updated DRB`；现能按事件更新并缓存最新状态。
- 原快照把同 PDU 最后一次 QoS 更新套给所有流；现保留原生 QoS 列表，按该流的 PCC/默认 QoS 关联唯一原生 QFI/DRB。多个 QFI 同 5QI 时标为 incomplete，不猜测。
- PCF 更新先于原生 DRB 证据时，Gateway 读取缺字段抛出 KeyError；现沿用原 watchdog 截止时间等待证据，缺证据仍不能成功。
- 启动重试只复用内容完全相同且已 Complete 的初始 NAS 策略，不覆盖其他既有策略。
- 固定 PCF 镜像的恢复接口比较 Go 对象，GET 却省略已初始化的空 map。恢复客户端按该镜像实际初始化结构保留 `traffContDecs` 和基线 `pccRules` 的空 map；CAS 和 owned 范围校验仍由原生接口执行。原 PCF 未在本轮重编译。

第 1 次启动失败、第 2 次暴露的流关联错误、第 3 次等待窗口异常，以及失败请求、执行事实、原生恢复证据均保留。每次部署运行代码前，先完成原场景恢复和停止；第 4 次用独立 run 完整通过，不把旧结果改成新版本结果。

## 证据与范围

服务器原始证据：`/home/xzy/MergedSystem/TestBed/artifacts/runs/oai-acceptance-20261028-4/evidence/oai-live-acceptance/`。操作、构建、回归及前几次失败记录在 `experiments/oai-acceptance-20261028/`；本机同名忽略目录保存证据副本。私有环境与生成凭据不进入报告或 Git，旧场景日志、卷和固定镜像保留。

准备、分阶段验证和报告生成分别位于 `scripts/operations/prepare_oai_acceptance.py`、`verify_oai_acceptance.py`、`record_oai_acceptance.py`；内核读回使用只读 `read_gtp_resources.py`。脚本绑定本次场景，拒绝覆盖原检查点。

本次证明重建镜像能完成上述真实协议与数据面流程；镜像/ELF 与旧版本仍非逐字节一致。未验证按需创建 PDU、真实射频切换、空闲态重选或所有 SDR 驱动；MAC/DCI 非法输入覆盖沿用构建阶段的原生离线控制。模型推理、Management 模型闭环、训练及已暂停采集未启动。
