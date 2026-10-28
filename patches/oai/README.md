# OAI 源码恢复与补丁链

2026-10-28 从 Windows 的 10 月 8 日迁移归档找回原始基础源码及 Git 对象，HEAD 为 `56ffb40e275ba584a3032b926203c4ec03890497`，17 份未提交修改保留。按用户后续保存源码的要求，父仓库同时保存 `sources/openairinterface5g` 的 4,325 份完整源码文件和可重放补丁链；源码逐文件清单见 [sources](../../sources/README.md)。本机及服务器原独立 Git 元数据继续保留，但其 `.git`、依赖缓存和迁移原始归档不提交。

以官方 `2026.w35` / `ceccfc8ffa4340d5bdc08a9fc84d2e6ab3f9472c` 为起点，按 `recovery-chain.json` 顺序应用：

1. `recovered-base.patch`：找回的 UE policy/NAS、RFSP、SDAP 等基础修改，包含当时未提交源码。
2. `mac-admission.patch`：MAC 入站边界及解码状态修复。
3. `dci-admission.patch`：DCI HARQ 反馈时序入站校验。
4. `drb-release.patch`：gNB DRB 释放与 RRC 编码修复。
5. `recovered-runtime.patch`：后续统计发布与 QoS 更新/观察修改。

补丁链已从干净上游重放，4,325 个源码文件与本次实际构建输入一致；不含 Git 元数据、依赖缓存及可选 flexric 子模块。UE/gNB、RFsim 及六个运行库已从恢复源码编译，重建镜像已完成真实功能验收，当前运行状态见 [HTTP 修复验收](../../docs/http-latency-validation-20261028.md)。构建详情见 [构建比较](../../docs/oai-rebuild-20261028.md)，原始修复材料哈希继续保留在 provenance.json。

MAC/DCI 的历史唯一根因尚未确证；未合入离线 parity 候选。迁移到其他 OAI 提交前必须重新审核差异和验证合法报文、HARQ 与会话恢复。
