# PubMed 文献检索服务首版设计

状态：首版结构与运行方式已确认，实施中。确认采用 Python/FastAPI、本地 SQLite 导入账本、独立导入 CLI、单导入写者及每日批次逐步可见；检索接口保留 ColBERT 与 Elasticsearch，优先 ColBERT。确认不等于全量建库或部署授权。

当前实施第一个增量：PubMed 核心字段解析、SciClaims Elasticsearch 查询对照及 ColBERT 接口适配。不开展双检索器评测；后续导入账本、HTTP API 和年度切换按增量推进。

## 已确认范围

使用用户已下载的 NCBI PubMed baseline 和 updatefiles 全新建库。每年重新建立年度库，年内按官方文件顺序应用新增、修订和删除。下载同步程序不属于本项目首版范围。

首版以 SciClaims 文献检索部分的代码实现为复用基准，服务独立命名并允许其他应用使用。作者的演示或完整语料不作为初始数据。不扩展 MeSH、作者、期刊等高级筛选，不迁移声明抽取、精炼及大模型核验。以下源码核查说明其公开仓库实际提供的 Elasticsearch 路径和 ColBERT 接入分支，不据此宣称论文实验使用了哪个后端。

## 上游基准和复用清单

基准仓库：[expertailab/sciclaims-backend](https://github.com/expertailab/sciclaims-backend)，固定 commit `915946f21ef12fb3187ac9e1ed22ce9fcd76768b`。以下结论基于该版本源码。

### 公开仓库实际提供的路径

- README 第 9–16 行要求先建立 Elasticsearch 索引，再填写配置并启动服务。README 中索引脚本路径少了 `processing/`，实际文件位于下表所示路径。
- 受版本管理的 `sciclaims_backend/service_config.ini` 提供 `[elastic]` 段，没有 `[colbert]` 段。
- `modeling/utils.py:25–40` 存在 ColBERT 分支：检测 `[colbert]` 后导入外部 `colbert.Searcher` 并传入配置；否则选择 Elasticsearch。两段同时存在时优先 ColBERT。这里只是后端选择，不是混合召回或两阶段重排。
- 已检查该 commit 的全部受版本管理文件：未提供 ColBERT 建库脚本、checkpoint 配置或专用配置示例；`requirements.txt` 也未声明 ColBERT 依赖。变量名 `n_colbert_results` 被两种后端共用，不能据此推断实际运行 ColBERT。
- 公开代码中可直接追踪的完整准备路径是 JSONL → ES 索引；服务另外把 JSONL 加载为内存字典，以检索返回的 `doc_id` 读取文献。它没有独立的文献检索 HTTP API，HTTP 入口是完整声明核验。

以上仅描述指定版本公开代码，不否定作者可能在仓库外准备过 ColBERT 模型和索引。本项目保留两种检索接口；ColBERT 实际环境与小样本运行由独立验证工作提供证据，不据此自动认可全库部署。

| 来源 | 实际行为 | 处理建议 |
|---|---|---|
| `sciclaims_backend/processing/es_indexing.py` 的 `ESSearcher.search` | `multi_match` 查询 `title`、`abstract`；返回整数 ID、零起始排名、原始 `_score` | 核心查询和结果语义复用 |
| 同文件的 `index` 和 `main` | `doc_id` 作 ID；索引标题和用空格连接的摘要；逐条导入 JSONL | 复用文本组织规则；输入改为 PubMed XML，ID 改为 PMID，写入改为受控 bulk |
| `sciclaims_backend/modeling/utils.py` 的 `init_searcher` | ColBERT 外部接入分支和 Elasticsearch 分支；所附配置使用 Elasticsearch | 保留两种接入，配置 ColBERT 时优先选择；ColBERT 建库参数等待实际验证 |
| 同文件的 `init_verification_dataset` | 整个 JSONL 读入内存字典，以 `doc_id` 查文献 | 不搬入全量内存字典；新服务按 PMID 读取 |
| `sciclaims_backend/processing/utils.py` 的 `run_claim_analysis` | 消费搜索结果；应用层将分数除以 100，再读取内存数据并核验 | 属于消费方，不迁入检索服务；服务返回原始分数 |
| `sciclaims_backend/run_claim_analysis_service.py` | Flask 核验服务；结果数默认 3、允许 1–10；启动时加载模型 | 不复制整个服务，只参考结果数约束 |
| 前期全量实验脚本 | bulk 建库、检查点、ES mget 读取 | 仅评估机制；它们不是作者原始实现，不直接搬入固定路径脚本 |

上游 `requirements.txt` 声明 `elasticsearch~=8.13.0`，还有模型相关依赖。新项目仅引入实际需要的依赖，不整包复制。上游 LICENSE 为 MIT；迁入其代码或实质性片段时保留版权与许可文本，增加第三方声明。新项目自身许可证仍需单独选择。

## Elasticsearch 行为对照与明确差异

保留以下查询体，不添加权重、过滤、分词扩展或显式重排：

```json
{"multi_match": {"query": "<query>", "fields": ["title", "abstract"]}}
```

建议首版 API 的 `k` 默认 3，范围 1–10，与上游核验服务一致；底层 `ESSearcher.search` 的默认值实际为 10。上游不传请求 `size`，仅对返回命中执行 `[:k]`。首版在 1–10 范围内保留该行为，不悄悄把它扩展成任意 top-k API。非空查询和参数校验属于新服务合同。

API 建议把 PMID 表示为字符串，避免把来源标识当算术量；上游把 `_id` 转成整数是明确的接口差异。排名从 0 开始，分数保留为原始 Elasticsearch `_score`，不叫置信度。需要上游三列表格式的客户端可在客户端边界适配，不建立第二套服务数据模型。

原标题和摘要的嵌套 XML 文本应按顺序提取；摘要各段使用一个空格连接成检索文本，不注入标签或其他摘要。保留分段标签、顺序及版权信息作为非检索元信息的方案待确认。没有摘要的合法记录仍可按标题检索。数学表达、空标题、异常标识的转换与拒绝规则在解析合同中明确并用合成样本验证。

相同代码在不同语料、Elasticsearch 版本、分片和统计状态下不保证相同分数或排名。高保真验收必须使用相同语料、mapping、引擎版本和分片设置；PubMed 全库结果不与作者语料结果作逐条相等承诺。8.13 系列作为原实现对照环境，正式部署版本需结合维护状态和行为对照另定。

## ColBERT 更新可见性与文本一致性（R0 部分已确认）

搜索始终使用已发布索引版本对应的文献文本。一次请求中的索引、内部 ID 到 PMID 的映射及返回的标题摘要必须属于同一已发布版本，不能用旧向量命中后返回独立更新的新文本。

新增、修订和删除在对应索引更新发布后对搜索生效。来源解析或文献保存完成不等于搜索已生效；状态接口须明确区分来源处理进度、已发布的搜索进度，以及尚未发布的更新。以下是已确认的行为约束，不是已实现的功能：

| 变更 | 对应索引更新发布前 | 对应索引更新发布后 |
|---|---|---|
| 新增文献 | 不因来源已处理而提前出现在搜索中 | 按新索引参与检索 |
| 修订文献 | 使用原已发布向量及其匹配文本 | 使用修订后的向量及其匹配文本 |
| 删除文献 | 仍按原已发布版本处理，不承诺来源到达后立即消失 | 不再作为该已发布版本的搜索命中返回 |

每日批次仍可通过小批次发布逐步可见，不要求整日更新一次性原子发布；但同一次搜索请求不能混用不同发布版本。更新准备或验收未完成时，不将其标记为搜索可见，也不提前替换该搜索所用的文本或映射。

本次确认只确定上述可见性与一致性语义。文献存储引擎、标准化中间文件、文本版本标识、旧版本保留期限、发布切换及故障恢复机制仍待 R0/R2 讨论和验收；不因此确认具体数据库、每日全库复制或现有 ColBERT 更新器可用。下面的 ES 年度索引及批量覆盖机制不能直接充当 ColBERT 的实现。

## ColBERT 构建与文本布局（R0 待联合评估）

先联合评估离线构建资源和正式 API 主机的查询约束，再决定是否分片。实验采用分片只证明该实验布局可运行，不构成正式物理存储决策。构建时的编码批次、官方索引 chunk、独立搜索分片及文本存储文件是不同概念，不要求一一对应。

比较单一逻辑索引、少量独立索引以及分批构建后统一查询的方案。分别核算采样与聚类、编码压缩、全局倒排构建、文件合并的峰值内存和暂存空间；确认跨机器阶段交接能否使用固定版本的官方能力，以及需要增加的编排、校验和恢复成本。多节点总内存不等于单进程可用内存，登录节点资源也不自动等于计算作业额度。

查询预算以正式 API 主机为边界，包含常驻倒排和文档长度结构、模型、活跃映射文件页、文本读取、并发及新旧版本切换。离线主机的额外内存不能抵消在线主机的查询开销。布局选择同时考虑初始构建、每日更新及查询成本，不能单独按建库是否完成决定。

当前比较保留独立在正式查询主机上完成 baseline 构建的路径，不以前置的大内存辅助主机作为必要条件。单一逻辑索引若采用受限内存构建，必须分别覆盖文本输入、训练采样、全局倒排与查询文件合并；只解决一个阶段不能判定全量可用。减少训练样本属于训练配置变化，流式文件合并则应以产物与查询等价性验收，两者不能混为同一种优化。

少量独立索引可降低单次构建峰值，但在线成本应按实际质心数量、候选读取及打分测量；固定实现的质心数按二次幂取整，索引数量变化不保证总质心数同比变化。合成质心选择测试仅用于分解成本，不能代替全量 API、文本读取或可靠每日更新验收。目前未确认任何一种物理布局。

文本读取须按命中的 PMID 和内容版本批量返回与索引一致的标题摘要，并避免查询进程常驻全库文本。文本布局可以独立于向量布局，只需通过发布版本保持一致；暂不确认每个搜索分片对应一个文本文件。SQLite 只读不可变文件、其他支持按键读取的文件布局或独立文本存储均为候选，比较读取性能、写入暂存、版本保留及维护成本后只实现一种。

若选择 SQLite 文件，必须遵守其网络文件系统约束：不在共享存储上使用 WAL；immutable 模式仅适用于整个引用期间保证不变的文件，不能代替发布和文件存活管理。具体存储引擎、标准化中间文件、内容版本标识、恢复与清理规则仍待确认。

参考：[SQLite 网络文件系统说明](https://www.sqlite.org/useovernet.html)、[WAL 限制](https://www.sqlite.org/wal.html)、[只读与 immutable 参数](https://www.sqlite.org/uri.html)。

## 通用结构与 Elasticsearch 实现方案

通用结构采用 Python 包、FastAPI 查询层、可选择的检索后端，以及本地 SQLite 导入账本。以下 ES 数据存储、bulk、别名切换细节仅适用于 Elasticsearch 路径；ColBERT 索引的保存、增量与切换不能直接套用这些机制。其模型与索引版本、文献存储、映射持久化和一致性方案在验证后补齐，当前未确定 Elasticsearch 是否承担 ColBERT 的文献存储。导入通过单独 CLI 进程运行，不放进 HTTP 请求；单机单导入写者，首版不引入任务队列或独立 PostgreSQL 文献副本。

| 部件 | 职责和真值边界 |
|---|---|
| 已下载 XML 文件及校验信息 | 外部来源事实；按保留策略支持重放，不由本服务下载或改写 |
| PubMed 解析模块 | 唯一的字段转换逻辑，年度和每日入口共用 |
| Elasticsearch 年度索引 | 服务使用的当前文献投影；保存可返回的标题摘要和来源定位，可以从源文件重建 |
| SQLite 账本 | 记录建库批次、文件校验值、执行状态与检查点；不再保存一份全量文献正文 |
| 查询 API | 查询与按 PMID 读取，返回具体建库批次；不接受任意 ES DSL 或数据写入 |

收益：保留现有检索能力，减少重复正文存储和服务组件。成本：必须设计好导入账本与 ES 写入之间的恢复流程，且需要足够的源文件保留期。限制：单写者和单机账本不适合直接扩展为多机导入。

较低成本方案是 CLI 加 ES 直连，但客户端会依赖 ES 凭据和内部索引布局，不符合独立服务的目标。另一方案是 PostgreSQL 保存全量文献、ES 只作搜索投影，适用于未来复杂编辑或多来源治理，但当前增加存储和双存储一致性成本。Flask 也能提供查询 API；建议 FastAPI 是为了请求校验和 OpenAPI 文档，不影响底层检索语义。

### 导入和恢复约束

- baseline 集合完整并通过来源校验后，才允许把年度库标为可用；后续更新按编号处理。下载完成判定机制不在本轮设计范围内。
- 同一 PMID 的后续记录完整替换当前投影，不对非空字段进行补丁合并。删除不存在的 PMID 按幂等操作处理。
- 同一文件中的事件保留来源次序；失败文件未恢复前不处理后续文件。相同文件号但校验值变化必须显式报冲突。
- ES 写入逐项检查成功后才推进账本检查点。两者不具备跨存储事务；发生崩溃时从未确认位置重放，不宣称恰好一次执行。
- 源文件、校验值、解析器版本和已确认记录位置决定恢复上下文；gzip 初版允许重新顺序解压到检查点，不假定支持任意偏移续读。
- 每日更新允许查询短暂看到正在应用批次的部分变化；状态要区分最近完整文件和正在处理文件。若要求每日批次完全原子可见，需要额外设计，当前未承诺。
- 年度新库独立建设，追上明确更新边界并验证后切换读取入口；短期保留旧库。切换由 ES 别名状态确定，账本恢复时与其核对，避免两个“当前库”真值冲突。
- 查询响应返回实际读取的建库批次；连续的搜索和文献读取可指定该批次，避免年度切换混用两个库。年度批次本身不提供年内逐文献历史快照。

### 接口形态建议

- `POST /v1/search`：查询文本与 `k`，返回实际建库批次和有序命中，每条含 PMID、排名、分数及标题摘要。直接返回本次命中的文本，避免核验方再次读取时碰到年内修订。
- `GET /v1/articles/{pmid}`：读取当前文献，可指定尚在保留期的建库批次；缺失、已删除和过期批次的响应合同在实现前明确。
- 健康和数据状态入口：区分进程存活、可查询、最近完成文件和导入失败。部署默认私有访问，认证及网络边界在部署方案中确定。

## 建议目录（尚未创建代码骨架）

```text
literature-search-service/
├── README.md
├── pyproject.toml
├── .gitignore
├── .env.example
├── LICENSE
├── THIRD_PARTY_NOTICES.md
├── src/literature_search_service/
│   ├── config.py
│   ├── contracts.py
│   ├── pubmed.py
│   ├── search.py
│   ├── ingest.py
│   ├── ledger.py
│   ├── api.py
│   └── cli.py
├── tests/
│   ├── fixtures/
│   ├── unit/
│   └── integration/
├── docs/
│   └── design/pubmed-search-v1.md
└── deploy/
```

先用少量职责清晰的模块，只有实现规模需要时再拆子包。`tests/fixtures` 只放合成小型 XML 和预期输出。`deploy` 在部署方式确定后添加配置模板；LICENSE 在许可证选定后添加。目录示意不表示所有文件立即创建。

公开文档仅保留通用设计、来源和验收规则。真实机器路径、内部会话、资源盘点、数据及运行日志放在仓库外；源语料、ES 数据目录、SQLite 账本和密钥不进入 Git。

## 执行路线图

增量顺序、依赖、当前状态、验收门槛和下一项执行计划统一见[首版交付路线图](../roadmap.md)。本文件只维护技术合同和实现约束，不另行维护一份增量计划。

## 官方参考

- [PubMed FTP README 和使用条款](https://ftp.ncbi.nlm.nih.gov/pubmed/README.txt)
- [PubMed 下载与更新顺序](https://pubmed.ncbi.nlm.nih.gov/download/)
- [PubMed DTD 文档](https://dtd.nlm.nih.gov/ncbi/pubmed/doc/out/250101/index.html)
- [SciClaims 基准检索源码](https://github.com/expertailab/sciclaims-backend/blob/915946f21ef12fb3187ac9e1ed22ce9fcd76768b/sciclaims_backend/processing/es_indexing.py)
- [SciClaims 基准许可证](https://github.com/expertailab/sciclaims-backend/blob/915946f21ef12fb3187ac9e1ed22ce9fcd76768b/LICENSE)
- [Elasticsearch multi-match](https://www.elastic.co/guide/en/elasticsearch/reference/8.19/query-dsl-multi-match-query.html)（行为参考，部署版本尚未冻结）
- [FastAPI 功能与 OpenAPI 支持](https://fastapi.tiangolo.com/features/)


## 第一增量实现边界

已实现 Python 包、流式 XML/gzip 核心字段解析、来源有序 upsert/delete 事件，以及保留 SciClaims 查询体和原始排名分数的检索封装。搜索直接返回本次命中的标题摘要；HTTP API 尚未实现。

解析器保留空标题但拒绝缺失 ArticleTitle；无摘要生成空摘要；PMID 与 Version 要求为正十进制标识。删除事件保留一组 PMID 和顶层记录序号。分段标签、类别及版权信息保留在内部 Article 中，OtherAbstract 不注入主摘要。MathML 只保留文本节点顺序，不解释数学含义。未知顶层记录显式失败。标准外部 DTD 声明允许存在但不联网读取；自定义实体声明拒绝。此实现不是完整 DTD 验证器，也不替代文件 MD5 检查。

源文件成功必须以迭代器完整消费且无异常为前提，前面已产出事件不能代表整个文件成功。解析器不写库、不更新检查点；这些由第二增量负责。

已提供合成 XML 与请求级测试，以及显式指定隔离 ES 8.13 实例的真实索引对照测试。后者会创建并删除唯一测试索引，不能指向生产环境。未执行的集成测试不计为通过；第一增量的检索高保真验收仍需真实引擎对照完成。

本次本地验证：22 个测试通过，1 个真实 Elasticsearch 集成测试因未提供隔离实例而跳过；Python 包的 editable 安装成功。源码请求级验证通过不代表实际引擎排名对照已经完成。


## ColBERT 优先接入（当前要求）

首版保留两种检索后端；与 SciClaims 一致，提供 ColBERT 配置时优先创建 ColBERT Searcher，仅未配置时选择 Elasticsearch。配置为空、依赖缺失、模型或索引加载失败都应报错，不静默切换后端。两后端不混合召回、不重排、不要求同时运行。

接口实现为 `SearchBackend.search(query, k)`，结果沿用 `SearchHit`，增加 `backend` 标识。ES 返回零起始排名；ColBERT 保留原始排名（已核对的官方版本为一起始），两者均保留各自原始分数，不相互比较或归一化。客户端若需要统一列表序号，可使用结果顺序，不把它与原生 rank 混为一谈。

`ColBERTSearch` 接收官方 Searcher 与 `article_lookup(internal_doc_id)`；后者必须从同一个索引对应的数据版本中返回 Article。内部编号不是 PMID，映射缺失应使查询失败，不能跳过。适配层不构造全量内存映射，不决定映射存储实现，也不承诺当前接口能自动检测调用方传入错误版本的映射。持久化索引版本绑定是后续接线的验收项。

`create_search_backend` 延迟导入 ColBERT；ES-only 使用不需要安装 torch/ColBERT。ColBERT 初始化参数原样传给官方 Searcher，不写死模型、GPU、截断长度或索引位置；也不自动下载或构建索引。当前仅提供 Python 接口，还不是可启动的 ColBERT HTTP 服务。

独立运行验证尚未作为本项目的已通过证据导入。因此目前不锁定 ColBERT 依赖版本或 Python/CUDA 组合；现有包要求 Python >=3.11，是否兼容验证环境也须核对后明确，接口单测通过不代表环境兼容。ColBERT 每日增量仍需落实修订/删除与索引映射的一致性，不能将查询接入完成称为增量维护完成。

实现依据：[官方 Searcher 源码](https://github.com/stanford-futuredata/ColBERT/blob/cc4f3dc91c0b45d2d08c251d9d95178285c65f1c/colbert/searcher.py)。其少量命中时可能返回比 ID 更多的 rank，适配器允许尾部多余 rank，拒绝缺失 rank 或 ID/score 长度不一致。

ColBERT 接口调整后本地验证：35 个测试通过，1 个 ES 真实索引对照测试跳过。新增测试覆盖配置优先级、加载失败不回退、延迟导入、内部 ID 映射、原生排名分数、空结果与结果长度校验；未执行 ColBERT 实际模型测试。
