# 订阅授权联动与动态 PDU session

本功能先在 `phase2-isolated` 验证，随后迁入 `s2-live-auto`；正式升级记录见 `LIVE_DYNAMIC_PDU_20260909.md`。订阅授权是独立的项目管理操作，不是 AM policy 扩权接口。

## 实现

- `GET /v1/subscription-authorizations/{supi}`：项目密钥读取真实订阅授权及摘要，不返回鉴权密钥。
- `POST /v1/actions/subscription-authorization`：项目密钥提交授权变更；智能体策略密钥返回 403。
- 请求字段：`run_id`、`snapshot_id`、`action_type="subscription_authorization_update"`、`target.supi`、`parameters.expected_digest`、`parameters.session_ids`、`parameters.policy`。
- `session_ids` 来自部署场景的 UE 会话目录，`policy` 为变更后完整 URSP。过期摘要、未知会话、撤销初始连接会话、指向未授权切片/DNN 的 URSP 都被拒绝。
- 同步 AM subscription、SM subscription、SMF selection subscription、SM policy 四个授权视图。保留留存 DNN 的 QoS/AMBR 和附加元数据；过滤已撤权的 FlowRules、QosFlows、ChargingDatas。新增授权使用场景配置的订阅默认值，不自动找回以前撤销的自定义 QoS。
- 暂停采集器和该 UE 的业务，停止 UE，提交并回读订阅，启动 UE，经真实注册接收 NAS Allowed NSSAI，重绑定 PCF 策略，再恢复业务与采集，返回经验证回执。
- 变更前订阅保存在运行目录的私有授权日志中（目录 0700，订阅备份 0600）；失败不自动回滚，也不伪造成功。失败回执和阶段日志用于显式恢复。

## 动态 PDU

UE 开启 `OAI_UE_DYNAMIC_PDU=1` 后，注册只建立初始 PDU。业务分类请求进入 OAI 的 URSP 选择器，匹配 NAS Allowed NSSAI 后优先复用已有会话；未激活的目标会话通过 NAS 任务发送真实 PDU Session Establishment Request。收到 Accept、创建 TUN 后才返回可用路由。

业务侧没有代替 UE 建立会话。业务侧负责提供已有五元组分类信息并绑定 OAI 返回的真实 TUN；DNN/S-NSSAI 和 PDU 的选择发生在 OAI 内。

UE 的 `.policy.state.json` 记录 Allowed NSSAI、会话 active/pending/error。NAS Reject 保留原因；本地请求超时记录 -1，不作为成功，不自动重试。会话采集使用实际活动会话，关联 UE IP、NGAP/QFI/TEID 与业务流，而非把场景目录当作已建立会话。

## 隔离部署与验证

```bash
.venv/bin/python scripts/deploy_dynamic_pdu_isolated.py
.venv/bin/python scripts/verify_subscription_dynamic_pdu.py
.venv/bin/python -m pytest tests/unit tests/contract -q
```

部署脚本只接受 `testbed-phase2-isolated` 和全部 `p2-` 容器，备份 compose、SMF 配置、PCF association 与 MongoDB。依赖已构建的动态 UE、控制面和业务镜像。不要在正式环境直接运行。

早期隔离 SMF 将 `urrThreshold: 1000` 调为 67108864 字节，短时验收通过，但正式多 UE 负载仍复现报告风暴，不能将 64 MiB 调整视为长期修复。正式配置使用 `urrThreshold: 0`、`urrPeriod: 10`：gtp5g 的阈值判断只对非零字节值触发，因而不产生额外 VOLTH 事件，周期用量计量仍存在。CHF、配额控制、鉴权和实际会话释放均未关闭。SMF/UPF/gtp5g 二进制未修改；底层阈值报告问题未从源码修复。

`resume_dynamic_pdu_isolated.py` 仅用于人工修复初始连接后显式继续中断的部署，不是自动兜底。它要求 UE 健康、恰有一个活动初始 PDU，随后下发策略并恢复业务。

验收脚本检查：初始一个 PDU；需求触发第二个 PDU；撤权后一个切片和一个 PDU；智能体无权修改订阅；已撤权 URSP 被拒绝；重新授权后两个切片和两个实际 PDU；业务关联完整且新鲜。

## 当前边界

- 已验证隔离 UE 以及正式 6 UE / 11 PDU 的 IPv4 环境；正式 `ue-5` 做过可逆撤权／重新授权。新增“授权”仅限已有网络和 UE 场景目录，不负责创建新切片、UPF 或 DNN 网络。
- 初始连接会话必须保留；授权变更采用受控重注册，会中断该 UE 业务，不是无损热更新。
- 授权变更期间暂停运行级会话采集器；动态配置下的策略写操作按运行串行化，同时写入返回 409。SM 重注册也停启采集器及目标业务。不是多 UE 并发写入实现。
- 动态建立与复用已验证；完整 T3580 重试、多候选 RSD 失败切换、任意网络发起释放后的重建、IPv6/多接入不是本次验收范围。
- App-ID/FQDN 匹配、真实无线重选没有包含在本次功能中。
- 本功能不允许 AM policy 任意扩大订阅权限。
