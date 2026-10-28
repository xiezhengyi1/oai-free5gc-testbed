# 已部署 OAI 修复补丁

从采集期证据恢复，分别保留 MAC admission、DCI admission 和 gNB DRB release；应用顺序为 MAC 后 DCI，DRB 属于 gNB 独立路径。补丁不能应用到任意 OAI 版本。原始源码及前后哈希、验收边界见 [恢复核查](../../../docs/testbed-recovery/README.md) 及 provenance.json。当前缺失原 OAI 构建树，本轮使用服务器仍保留的已验收二进制镜像，并按完整镜像 ID 固定；没有宣称重新编译过完整 OAI。

MAC/DCI 的历史唯一根因尚未确证；未合入离线 parity 候选。迁移到其他 OAI 提交前必须重新审核差异和验证合法报文、HARQ 与会话恢复。
