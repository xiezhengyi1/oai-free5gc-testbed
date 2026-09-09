# 二期源码与镜像清单

2026-09-09，服务器 `/home/yinyuexi/xiezhengyi`。这些是实现提交；后续只补充文档的提交不改变以下实现基线。

| 仓库 | 实现提交 | 分支 |
|---|---|---|
| Multiagents | 58e43ef（主改造 97bf3a1，加空切片回归修复） | codex/standard-ue-policy |
| oai-free5gc-testbed | d918e1d | codex/standard-ue-policy |
| openairinterface5g-build | 6deba55 | codex/standard-ue-policy |
| ue-policy-work/pcf | 8a421e4 | codex/standard-ue-policy |
| ue-policy-work/amf | b02b431 | codex/standard-ue-policy |
| ue-policy-work/nas | 5bea0d7 | codex/standard-ue-policy |

原有 Multiagents、测试床改动分别保存在检查点 1541a9c、d16d95f。OAI 原有 CPM/Dockerfile.build、依赖缓存与 flexric 保持原样，未夹带进二期提交。新构建目录为独立 `cmake_targets/ue-policy-build`。未推送远端 Git 托管服务。

| 镜像 | Image ID（sha256） |
|---|---|
| free5gc/pcf:v4.1.0-uepolicy | 87d1153aea8aedc1f72181875e12a55ef563ca82b9e31d621607ffeb2b8f328b |
| free5gc/amf:v4.1.0-uepolicy | 454e04de2403cb52a9bd233da755081e99ffaf190223707abd11e37fd9a1abf7 |
| oaisoftwarealliance/oai-nr-ue:2026.w35-uepolicy | 101e8743c952af3b233837d3b3974baba79efdc7674a1dc874cda6e31ef960e3 |
| oaisoftwarealliance/oai-gnb:2026.w35-uepolicy | 36589f3041f231cb08c3820b23fcdad99cf4ffccd9ae1b1d92be6f471a099c4d |
| oai-free5gc-testbed/control:uepolicy | 516daa8c486e6f5c87d204c80f61f5c4375d374f01536e16be373a1d491512e4 |
| oai-free5gc-testbed/traffic-sidecar:uepolicy | 53ea3c159e5491d2595eef800fa1a50f51267bd5b29eb836113c7110e4a0ed1b |

最终统一构建日志：服务器 `/tmp/ue-policy-final-build.log`，交付时也复制到 run 的 evidence 目录。生成的场景、凭据、策略磁盘状态、数据库和抓包未加入源码提交。复现实验只针对 `phase2-isolated`，旧 `s2-live-auto` 不在操作范围。
