# 仿真主机约定

自 2026-10-08 起，所有真实仿真、RFsim、free5GC、业务流和集成验收只在 `xzy@10.112.50.129` 的 `/home/xzy/testbed` 执行。Windows 工作区用于编辑和证据保存；运行期不依赖 Windows 中转。

自 2026-10-09 起，vLLM、Multiagents 和 PostgreSQL 迁移到本机 `/home/xzy` 下对应分类目录；yinyuexi 可继续承担微调，不得启动其旧 OAI/free5GC。旧目录保留为历史证据。

部署和运行入口见 `deployment/hosts/ibn3090/README.md`。目标 CPU 不支持 AVX-512，使用已验证的 AVX2 镜像。新场景也必须沿用该主机、镜像和本机数据库配置。

历史实验脚本可能写死 yinyuexi 路径。执行前先迁移路径与生命周期操作，不能直接运行旧脚本。AM 的 RFsim 连接态频点切换结果不能表述为实际射频、跨频段、空闲态重选或业务 SLA 达成。

新机器上的脚本归入工作区 `scripts/operations/` 或 `scripts/migration/`，日志归入 `logs/build/`、`logs/migration/`、`logs/validation/` 或具体 run 的 `logs/`；实验与证据归入 `experiments/`。不在 `/home/xzy` 或工作区根部散放临时脚本、日志和安装包。目录索引见工作区 `README.md`。
