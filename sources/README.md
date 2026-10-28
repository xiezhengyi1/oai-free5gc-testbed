# 已恢复的 OAI 源码

`openairinterface5g/` 保存本次 UE/gNB、RFsim 和六个运行库实际使用的完整源码，共 **4,325 个文件、92,914,384 字节**。这些文件以普通 Git 文件提交，克隆 TestBed 即可取得；它们不是指向本机目录的 gitlink。

官方基线为 `2026.w35` / `ceccfc8ffa4340d5bdc08a9fc84d2e6ab3f9472c`，恢复归档的独立 Git HEAD 为 `56ffb40e275ba584a3032b926203c4ec03890497`。当前源码还保留原未提交改动，并叠加已经验收的 MAC/DCI/DRB 和运行期修改。修改顺序及来源见 [补丁链](../patches/oai/recovery-chain.json)，逐文件字节哈希见 [源码清单](oai-source-manifest.json)。本机、服务器及提交内容按该清单核对。

上游原始版权、[CSSL 许可证](openairinterface5g/LICENSE) 及通知文件随源码保留，OAI 子目录沿用其自身许可。TestBed 的其他文件不因此改变许可证。

原本机和服务器工作副本的独立 `.git` 元数据不进入父仓库；新克隆使用 TestBed 自身的 Git 元数据。构建脚本同时记录 Git 根目录、提交和实际输入字节哈希，区分两种布局。依赖 `.cpm` 缓存、生成的构建文件和未启用的可选 flexric 子模块不在本清单中；本轮构建明确关闭 E2 Agent。

源码恢复与构建工具链见 [构建报告](../docs/oai-rebuild-20261028.md)，当前运行和验收见 [HTTP 修复验收](../docs/http-latency-validation-20261028.md)。迁移归档、私有环境、鉴权材料、镜像文件和原始仿真日志另行保存在忽略目录中。
