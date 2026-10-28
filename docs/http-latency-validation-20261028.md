# HTTP 服务端修复与真实时延验收

**原 20 ms HTTP 时延项通过。** 当前服务器运行 `http-nodelay-20261028-1`，运行版本为 `http-nodelay-20261028`。正式业务流在 12 个不重叠窗口中均低于原阈值；结构化结果、镜像身份和逐文件证据哈希见 [验收摘要](http-latency-validation-20261028.json)。

## 修改与条件

运行代码只改 `testbed/traffic/app_server.py`：为 `Handler` 设置 `disable_nagle_algorithm=True`，让接受的 HTTP 连接启用 `TCP_NODELAY`，避免响应头和小正文分写时等待延迟 ACK。新测试通过真实连接验证该选项已生效，并验证多个不同长度响应及 health 请求可以复用同一连接、正文完整。

客户端、原延迟计时范围、采样方式、1200 字节正文、配置负载、20 ms 阈值均保持原样，未启用 QUICKACK。新旧 `source-scenario.yaml` 逐字节相同，仍为 2 UE、2 UPF、4 PDU、6 条 HTTP/TCP/UDP 流；OAI 与 free5GC 镜像 ID 未变，应用配额保持 1 CPU。所有运行容器中的 93 份 Python 源码与宿主一致。

部署前验证旧场景已回到原策略、会话及内核资源状态，采集三个修改前窗口，然后停止旧场景并保存私有回滚配置、Mongo 备份、日志和卷。未向正在运行的冻结场景热更新代码。

## 实测

正式指标仍为“请求开始至完整响应读完”的 HTTP 事务时间，经原快照窗口聚合。12 个观测窗口及补充探针阶段耗时约 126 秒。

| 正式业务流 | 修改前三个窗口 | 修改后十二个窗口 | 修改后窗口均值 |
|---|---:|---:|---:|
| UE1 HTTP | 53.63–55.14 ms | **4.69–6.96 ms** | **5.87 ms** |
| UE2 HTTP | 53.96–57.56 ms | **5.13–7.45 ms** | **6.45 ms** |

每个窗口都要求关联完整、数据新鲜、availability=1，六条流收包数均持续增长。额外通过原 UE 数据路径分别发送 64 次普通 HTTP 请求，客户端保持原 TCP 选项：样本 P95 为 **9.38/10.91 ms**，样本最大值为 **12.10/12.16 ms**。探针结果另存，不替代正式业务指标。

Linux 回归 **133 项通过**。URSP 往返、RFSP `64→65→64`、QoS 新增/修改/释放、六个反向用例全部通过；UE2 原生策略保持不变，同 PDU 的其他流保持正确 QFI/5QI。两套 UPF 的所有 PDR/FAR/QER/URR 属性和 ID 精确恢复，验收期间相关容器未重建或重启。

本次通过的是 **20 ms 时延项**。窗口平均和有限探针样本不构成长期 P99 保证；原带宽、抖动、丢包数据完整保留。HTTP 实测下行约 **0.936–0.990 Mbps**，尚不能称为严格达到全部 1 Mbps 带宽要求，也不把时延通过扩大为完整业务 SLA 通过。

## 证据

服务器运行证据位于 `/home/xzy/MergedSystem/TestBed/artifacts/runs/http-nodelay-20261028-1/evidence/`：`oai-live-acceptance/` 保存协议闭环与恢复，`http-latency-validation/` 保存十二个正式窗口、普通客户端原始样本及内核终态。构建、回归、修改前快照与停止记录位于 `experiments/http-nodelay-20261028/`，本机同名忽略目录保存证据副本。

验证入口为 `scripts/operations/verify_oai_acceptance.py`、`verify_http_latency.py`、`record_http_validation.py`，均保留原始检查点并拒绝覆盖。本轮未启动模型、训练或已暂停的数据采集。此前 [延迟诊断](http-latency-diagnosis-20261028.md) 与 [重建镜像验收](oai-acceptance-20261028.md) 保留为历史证据。
