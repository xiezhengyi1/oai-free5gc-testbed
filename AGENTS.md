# 当前恢复部署约定（2026-10-28）

源码与当前仿真运行目录改为 `xzy@10.112.50.129:/home/xzy/MergedSystem/TestBed`。参考依赖在 `/home/xzy/MergedSystem/.dependencies`，Python 在 `/home/xzy/MergedSystem/.runtime/python`。下文的 `/home/xzy/testbed` 是已删除旧目录的历史记录，不能再作为当前路径。

使用 `bash with-testbed.sh <命令>` 加载私有 `configs/hosts/ibn3090.env`（指向服务器 `.env`）；不得打印或提交私有配置。真实仿真单并发，只在 ibn3090 执行。启动前检查 CPU/GPU 空闲、镜像哈希和主机配置；使用匹配实际场景的 run ID。不要自动恢复已暂停的数据采集或训练。

现有采集资料和 PostgreSQL 数据保持原位；本轮恢复测试使用独立 `mergedsystem_testbed` 数据库。源码变化仅在运行任务退出、恢复及停止后部署，记录 runtime revision；保留失败、原始快照和已执行事实。禁止为了通过测试改目标、放宽断言、超时或验收。

2026-10-28 已找回 OAI 原始基础源码、Git 对象和未提交修改，恢复副本位于 `sources/openairinterface5g`。UE/gNB、RFsim 与配套六个库已重新编译；构建比较见 `docs/oai-rebuild-20261028.md`。重建镜像已完成 NAS URSP、NGAP RFSP、QoS 新增/修改/释放及精确恢复验收，见 `docs/oai-acceptance-20261028.md`。后续修复 HTTP 服务端小包发送等待，当前运行 `http-nodelay-20261028-1`，Python 版本 `http-nodelay-20261028`，133 项回归通过；原 20 ms HTTP 时延项通过十二个窗口验证，完整业务 SLA 尚未全部验收，详见 `docs/http-latency-validation-20261028.md`。旧场景已恢复并停止，原始证据和卷保留。RFSP 仅证明控制面应答，同 5QI 多 QFI 证据不足时保持 incomplete；不得声称全部行为等价或证明历史无线故障唯一根因。

---

# 仿真主机约定

自 2026-10-08 起，所有真实仿真、RFsim、free5GC、业务流和集成验收只在 `xzy@10.112.50.129` 的 `/home/xzy/testbed` 执行。Windows 工作区用于编辑和证据保存；运行期不依赖 Windows 中转。

自 2026-10-09 起，vLLM、Multiagents 和 PostgreSQL 迁移到本机 `/home/xzy` 下对应分类目录；yinyuexi 可继续承担微调，不得启动其旧 OAI/free5GC。旧目录保留为历史证据。

部署和运行入口见 `deployment/hosts/ibn3090/README.md`。目标 CPU 不支持 AVX-512，使用已验证的 AVX2 镜像。新场景也必须沿用该主机、镜像和本机数据库配置。

历史实验脚本可能写死 yinyuexi 路径。执行前先迁移路径与生命周期操作，不能直接运行旧脚本。AM 的 RFsim 连接态频点切换结果不能表述为实际射频、跨频段、空闲态重选或业务 SLA 达成。

新机器上的脚本归入工作区 `scripts/operations/` 或 `scripts/migration/`，日志归入 `logs/build/`、`logs/migration/`、`logs/validation/` 或具体 run 的 `logs/`；实验与证据归入 `experiments/`。不在 `/home/xzy` 或工作区根部散放临时脚本、日志和安装包。目录索引见工作区 `README.md`。
