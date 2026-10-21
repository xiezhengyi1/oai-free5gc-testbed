# 仿真工作区

本目录是 ibn3090 的仿真工作区：`/home/xzy/testbed`。

| 内容 | 目录 |
|---|---|
| 日常启停脚本 | `scripts/operations/` |
| 迁移、安装与诊断脚本 | `scripts/migration/` |
| 编译日志 | `logs/build/` |
| 安装、中转、镜像传输日志 | `logs/migration/` |
| 验收日志 | `logs/validation/` |
| 安装包及原始清单 | `archives/install/` |
| 原机夹具输入 | `archives/source-fixtures/` |
| Python 与 AVX2 产物 | `runtime/` |
| AM 实验 | `experiments/am-rfsp-20261008/` |
| 完整 S2 场景及其日志、状态 | `oai-free5gc-testbed/artifacts/runs/ibn3090-s2-20261008/` |
| 源码 | 根目录中各自命名的 Git 工程目录 |

运行方法、主机分工、中转端口和验收结果见 [部署手册](oai-free5gc-testbed/deployment/hosts/ibn3090/README.md)。

日常入口：

```bash
cd /home/xzy/testbed
oai-free5gc-testbed/.venv/bin/python scripts/operations/manage-run.py status
oai-free5gc-testbed/.venv/bin/python scripts/operations/manage-run.py resume
oai-free5gc-testbed/.venv/bin/python scripts/operations/manage-run.py stop
```

新脚本按用途存入 `scripts/`，新日志按用途和实验名称存入 `logs/` 或具体 run 的 `logs/`。不要在 `/home/xzy` 根部或本目录根部散放临时脚本和日志。历史迁移脚本包含一次性初始化、密钥轮换等操作，保留作记录，不可批量重跑。
