# 正式环境订阅授权与动态 PDU 升级

目标：服务器 `/home/yinyuexi/xiezhengyi/oai-free5gc-testbed/artifacts/runs/s2-live-auto`。用户已明确授权正式升级。隔离 `p2-*` 运行没有被本次迁移脚本重启。

## 功能与验证范围

- 6 台 OAI UE 注册时各建立一个初始 PDU，原 URSP 下发完成后由业务需求触发其余会话，恢复为 11 个真实 PDU 和 11 条业务流。
- 保留升级前的订阅授权、完整 URSP 和 RFSP；`ue-5` RFSP 仍为 64。关联 ID 因重注册而更新，不把旧 ID 冒充新连接。
- 正式 `ue-5` 通过撤权／重新授权测试：两个授权切片及 PDU → 一个 → 两个。项目角色可以修改订阅，智能体角色无权扩权；已撤权 URSP 被拒绝。
- AM/URSP 路径切换与恢复，以及 Multiagents 对 6 UE 的 SM / AM / URSP 共 18 项只读查询，通过现有验收脚本检查。
- 单元和契约测试 64 项通过。本轮没有额外改变正式订阅 QoS 来做 SM 写入测试；为动态模式补充了 SM 重注册时采集器和业务的停启。
- 为运行级采集器的一致性，动态模式下策略写操作串行，竞争返回 409。订阅变更会受控重注册，不承诺无损切换。

## 配置与迁移过程

回滚点：`migration-backups/dynamic-20260909T132102Z`，含 generated 配置、容器信息、MongoDB dump、PCF association 和私有完整订阅／策略备份。备份保留在服务器私有目录，未打包到公开验收材料。

升级前 SMF 已退出 137、`oai-nrue-4` 已因 OAI 断言退出，RAN exporter 也停止。本次恢复了这些组件。CHF 当时卡在计费文件服务重连；重启 CHF 后重新登录成功，没有停用计费。

正式多 UE 下发现 64 MiB 用量阈值仍会触发报告风暴，导致新的 PDU 建立超时。失败回执 `action-0c984d97b6da00da3b4c` 及对应日志保留；随后显式恢复原订阅，保留最新 AKA 序列号，再恢复全链路并复测。

最终 SMF 配置采用 `urrThreshold: 0` 和 `urrPeriod: 10`，关闭额外字节阈值触发但保留周期计量。当前 gtp5g 阈值判断要求非零 volume；未修改内核模块、SMF 或 UPF 二进制。CHF 和配额控制仍开启，不将这次配置调整描述为底层阈值报告代码已修复。

首次成功授权联动证据：`ue-policy/evidence/subscription-dynamic-20260909T133511Z`。最终版本、备份、镜像内容 ID 和末次验收路径见 `ue-policy/deployment-dynamic-pdu.json`；持续运行报告见 `ue-policy/evidence/pfcp-soak-*`。

## 运维入口

入口保持不变：网关 8080、快照 8081、WebUI 5000。Multiagents 无需切换地址。

```bash
.venv/bin/python scripts/verify_subscription_dynamic_pdu.py s2-live-auto
.venv/bin/python scripts/verify_live_policy_migration.py
.venv/bin/python scripts/verify_live_pfcp_soak.py
```

`upgrade_dynamic_pdu_live.py` 按 prepare / deploy / ues / policies / traffic 显式分阶段。已完成的 prepare 不重复执行；不要在有新业务策略后随意重放历史 policies 阶段。`restore_live_verification_subscriber.py` 是本次失败测试的显式修复工具，仅用于相应备份上下文，不是自动回滚机制。

如需要回退：先停止策略写入和业务，保存新的检查点，再使用本次回滚点恢复旧 Compose/UE 镜像与初始全会话行为；移出动态标记并重注册、重新绑定策略。不要直接覆盖当前 MongoDB 为旧 dump，否则会回退 AKA 序列号和后来订阅更改。原始备份保留用于人工核对。

## 不包含的能力

新增授权仍限已经部署的会话目录，必须保留初始连接会话。不包含新建网络切片/UPF、App-ID/FQDN 匹配、真实无线重选、完整 PDU 重试和网络发起释放恢复。
