# OAI 源码找回、构建与镜像比较

> 本文保留构建阶段的结论。后续已切换重建镜像，并完成指定 RFsim 场景的真实闭环和恢复验收，当前状态见 [验收报告](oai-acceptance-20261028.md)。下文“当前运行”指构建结束时的历史状态。

已从 Windows 迁移备份找回真实基础源码，保留原有 UE policy/NAS、RFSP、AM 与 SDAP 修改，并叠加后续有执行证据的修复，重新编译 UE/gNB 和 RFsim 目标。两套候选镜像已生成并通过离线检查。它们尚未替换当前运行镜像，也未完成真实 NAS UE policy/RFSP 业务闭环验收。

结构化结果见 [构建与比较摘要](oai-rebuild-20261028.json)。完整源码位于本机 `TestBed/sources/openairinterface5g` 和服务器 `/home/xzy/MergedSystem/TestBed/sources/openairinterface5g`。后续按用户要求，4,325 份源码文件已作为普通文件纳入本仓库，同时保留补丁链和 [逐文件清单](../sources/README.md)；原独立 Git 元数据只保留在本机及服务器，不嵌套提交 `.git`。

## 找回的材料

- 来源：LAPTOP-9VCVUKCD 的 `.codex-migrate-testbed-20261008/sources.tar.gz`。原件保留，服务器及本机另存恢复副本。
- 原档 135,569,909 字节，SHA-256 为 `186e2a5043f524af7add6b0cc0732e0b25276ca5d33c50d83b68563914715f37`，三端一致。
- 原分支 `codex/standard-ue-policy`，HEAD `56ffb40e275ba584a3032b926203c4ec03890497`。Git 对象完整性检查通过；17 个当时未提交的源码/构建修改保留，不能仅检出 HEAD 而丢掉这些修改。
- UE policy 编解码、路由服务、NAS 集成、NGAP RFSP 与 RRC RFSP 文件均在。Windows 上的 RFSP 验收源码哈希 10/10 匹配。
- 归档省略的 14 个受版本控制的 `cmake_targets` 文件已从 Git 对象恢复；其他干净上游辅助文件沿用固定上游版本。

原始迁移归档含其他测试床材料和私有配置，只保存在忽略目录中，权限 600，不提交。另生成的 OAI 独立源码归档 SHA-256 为 `d990218034548f6d9d56d1b9a176ac71767a93872b17a1f0a5817e6a595d1e38`，用于本机恢复工作副本。

## 可重放源码

官方基线为 `2026.w35` / `ceccfc8ffa4340d5bdc08a9fc84d2e6ab3f9472c`。按 [recovery-chain.json](../patches/oai/recovery-chain.json) 顺序应用基础恢复、MAC、DCI、DRB 及运行期修复五个补丁。已从干净上游实际重放，4,325 个源码文件与本次构建输入逐字节一致；比较排除 Git 元数据、依赖缓存和未启用的 flexric 子模块。

`recovered-base.patch` 包含原 UE policy、RFSP 等基础实现及未提交修改；`recovered-runtime.patch` 补齐后续 RRC 统计发布、事务观测和 QoS 更新/读回修改。MAC/DCI/DRB 六个被修复文件与历史验收源码逐字节核对，保留原断言，不合入曾被拒绝的 LDPC parity 候选。

## 构建与验证

使用 GCC 12.3.0、AVX2 开启、AVX-512 关闭；asn1c 固定提交 `940dd5fa9f3917913fd487b13dfddfacd0ded06e`。构建 `nr-softmodem`、`nr-uesoftmodem`、RFsim 及六个运行库，不启用 GPU、E2 Agent，也不声称重新构建所有物理 SDR 驱动。

构建进程限制在控制侧 CPU `0-3,16-19`，最多 8 个编译任务、nice 19，射频专用核心保持隔离。恢复文件保留历史时间戳，已显式更新所有变更源文件/头文件的构建时间戳，确保增量编译不会漏掉内容变化。

| 检查 | 本轮结果 |
|---|---|
| UE policy | 原有独立测试通过：固定 NAS 编码、路由分类、Complete/Reject、所有截断及逐位扰动；ASan/UBSan 无错误 |
| MAC admission | 61,231 个合法控制、188 字节非法长度及 guard page 检查通过 |
| DCI admission | 6,144 个时序/RNTI 控制通过，MAC 状态保持、原最小时序约束保留 |
| DRB 释放编码 | 6 组真实 ASN.1 编解码控制通过，包括仅释放 DRB 的消息 |
| 待释放 DRB | 7 组作用域、去重、活动 DRB 保护与清理控制通过，使用本次实际 RRC 源码 |
| 候选镜像 | 两套镜像的命令入口及动态库解析检查通过 |

初次 pending DRB harness 的独立链接缺少原生入口对象，已保留失败日志，改为完整原生链接后通过。初次 Dockerfile 直接使用 config ID 被 BuildKit 当作仓库名，失败日志保留；随后改用已核对完整 ID 的本地基础标签，离线构建通过。未改 Docker 全局代理或镜像源。

## 与现有镜像的差异

| 项目 | 比较结果 |
|---|---|
| gNB 函数 | 13,843 个函数集合一致，函数大小全部一致 |
| UE 函数 | 4,903 个函数集合一致，其中 4,897 个大小一致 |
| UE 的 5 个 NAS/鉴权相关函数 | 日志源码路径前缀长度变化 73 字节，影响日志指针指令与对齐；按明确规则归一化后指令形式一致。该检查不证明全部数据及语义等价 |
| UE 的 RRC 编码函数 | 新 UE 也链接了带 DRB 仅释放修复的共享编码器；旧 UE 仍保留较早编码对象。6 组独立编码控制通过 |
| 镜像文件系统 | 每套候选仅改变主程序、六个重建库及 ldconfig 辅助缓存；比较排除三个容器生成的主机配置文件 |

两套候选标签：

- `mergedsystem/oai-gnb:recovered-source-20261028`
- `mergedsystem/oai-nr-ue:recovered-source-20261028`

ELF 与镜像哈希均不等于旧版本，因此不能称为逐字节复刻。候选复用已核验的原运行基础层，替换本次源码构建的程序和六个库；它们也不等于从空白系统重新制作了所有依赖层。真实 UE policy 下发/完成确认、RFSP 交互、多 PDU 路由和恢复仍需在安全切换边界另行验收，离线测试不代替这些结果。

## 文件与复验入口

服务器证据目录：`/home/xzy/MergedSystem/TestBed/experiments/oai-rebuild-20261028/`。其中保存原档、原 Git 状态、构建日志、源码哈希、ELF/镜像文件清单、原生测试输出及失败重试记录。本机同名目录保存恢复归档与证据副本，均由 `.gitignore` 排除。

重新构建使用新的输出目录，不覆盖本轮证据：

```bash
cd /home/xzy/MergedSystem/TestBed
bash scripts/operations/build_recovered_oai.sh \
  sources/openairinterface5g \
  experiments/oai-rebuild-NEW/build \
  experiments/oai-rebuild-20261028/toolchain/asn1c/bin/asn1c \
  experiments/oai-rebuild-20261028/cpm
```

本轮结束时再次读取真实快照：原场景 `merged-recovery-protocols-20261028-1` 的 HTTP/TCP/UDP 三条流仍完整、新鲜、可用；原 OAI 容器 ID、启动时间和镜像保持不变，应用 CPU 配额仍为已恢复的 1。没有恢复模型采集、训练或改写原执行/恢复证据。
