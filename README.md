# literature-search-service

面向 Claim 核验、证据发现及其他科研工作流的**可复现、版本化文献检索基础设施**。

项目最初从 SciClaims 的 literature search 组件拆分需求出发：把“Claim → 候选文献”的检索能力从单一应用中独立出来，使不同下游系统可以复用同一套 PubMed 语料、版本和检索接口，而不绑定某一个 verification pipeline 或某一种 retrieval model。

## 首要应用场景

当前第一优先场景是：

```text
Claim
  → literature-search-service
  → high-recall candidate articles
  → Evidence Lab / verification
  → evidence localization + SUPPORT / CONTRADICT / NEI
```

本项目负责候选文献召回、PMID/语料/索引版本和 provenance；Claim 的 SUPPORT / CONTRADICT / NEI 判定属于下游 Evidence Lab / verification 层，不进入本项目核心合同。

## 项目状态

项目处于早期开发阶段。当前已提供：

- PubMed 核心字段解析；
- SciClaims-style Elasticsearch 查询封装；
- ColBERT/Jina 适配与建库实验工具；
- 冻结 corpus 的关键词专题筛选能力正在通过 PR #25 收敛；
- Jina-ColBERT-v2 8K build/profile 正在通过 #26 / PR #27 重定为正式候选 backend。

尚未提供稳定 HTTP API、完整可恢复增量发布或正式全量检索服务。

`dev` 是开发集成分支。GitHub issues/milestones 维护任务与决策，PR 负责代码审查；协作规则见 [AGENTS.md](AGENTS.md)。

## 设计原则

### 1. Backend-agnostic

检索基础设施不绑定某一个模型。

当前候选/基线包括：

- **Elasticsearch/BM25**：保留 SciClaims-style `title + abstract` 完整文本 baseline；
- **Jina-ColBERT-v2**：当前已投入最多工程验证的 late-interaction 候选；
- **MedCPT**：计划在 Claim→Evidence benchmark 中作为 biomedical retrieval 专用候选评测。

不同 backend 必须通过统一查询/结果合同暴露；初始化失败不得静默切换；原始 score 不跨 backend 直接比较。

### 2. Corpus 与 index 分离

专题语料身份不等于某个 retrieval index。

同一个冻结 corpus/topic 可以派生多个检索 projection：

```text
topic corpus/version
  ├─ Elasticsearch index
  ├─ MedCPT projection
  ├─ Jina-ColBERT index
  └─ future backend
```

更换 backend 不应改变 PMID、专题筛选规则或源语料版本。

### 3. 可追溯、可重放

正式检索结果最终应能够追溯到：

- PMID / article version；
- corpus/topic version；
- backend / model revision；
- index/build identity；
- query result rank / raw score；
- 对应的同版本文本。

## 当前路线

当前不再以“能否把 39.9M PubMed 建成 Jina index”作为项目成功标准。

执行顺序：

1. **#24 / PR #25**：建立可复现关键词专题语料；
2. **#26 / PR #27**：正式化 Jina-ColBERT-v2 8K backend/build profile，同时保留 backend-agnostic 架构和 ES baseline；
3. **#30**：完成一个真实 Jina 专题检索闭环；
4. **#32**：做 Claim→Evidence Retrieval Value Gate，比较 ES/BM25、Jina、MedCPT；
5. **#11**：只对 #32 选择的 backend 实现专题新增/修订/删除/恢复；
6. **#28**：仅当 #32 选择 Jina 且 #11 的 Jina 增量成立时，才进入 RTX3060/WSL2 全量候选门禁；
7. 全量执行任务只有在 retrieval value、增量语义和资源成本都得到证据后才创建。

#32 的首要指标是 **gold evidence document Recall@K**，而不是标题自检索、普通语义相似度或“模型能运行”。

详细依赖和停止条件见 [首版交付路线图](docs/roadmap.md)。

## 目标

- 支持 PubMed 文献数据的可重复导入、专题派生和后续增量维护；
- 为不同应用提供统一、可替换 backend 的检索接口；
- 使检索结果与 PMID、语料版本、索引版本和实际返回文本保持一致；
- 优先优化 Claim→Evidence candidate retrieval 的 evidence recall；
- 为 Evidence Lab、SciClaims-like verification、系统综述、LBD 等下游提供稳定基础层。

## 非目标

当前不在本项目内实现：

- Claim extraction；
- SUPPORT / CONTRADICT / NEI verification；
- evidence sentence/CEU 判定；
- RAG/综述生成；
- 自研 retrieval model；
- 以通用消费者产品为目标的“另一个 PubMed/Elicit/Consensus”。

## 设计文档

- [首版交付路线图](docs/roadmap.md)
- [PubMed 文献检索服务首版设计](docs/design/pubmed-search-v1.md)
- [ColBERT/Jina 实验复盘](docs/colbert-experiment-review.md)

历史设计文档可能保留早期 ColBERT/ES 方案用于追溯；若与当前执行顺序冲突，以 open issues 和 roadmap 为准。

## 前置数据工具

[PubMed 更新文件同步工具](tools/pubmed/README.md)维护现有 crontab 下载脚本，支持失败诊断、续传与校验恢复，提供导入前的原始 updatefiles。下载进度独立于检索服务的发布进度。

## 本地开发验证

需要 Python 3.11 或更新版本。

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[test]'
.venv/bin/python -m pytest -q
```

普通测试使用合成数据。需要真实 Elasticsearch 对照时，只允许连接隔离、可写的测试实例：

```sh
LSS_TEST_ES_URL=http://localhost:19200 .venv/bin/python -m pytest -q -m integration
```

集成测试会创建并删除 `lss-test-<随机标识>` 索引，禁止指向生产实例。

模型、真实语料、索引、服务器路径、运行日志和密钥不进入公开仓库。

上游代码的来源和许可见 [第三方声明](THIRD_PARTY_NOTICES.md)。本项目自身开源许可证尚未选定。
