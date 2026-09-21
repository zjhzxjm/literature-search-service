# 首版交付路线图

状态：2026-09-21 重新收敛。项目定位从“Jina 全量检索路线”调整为 **Claim→Evidence 导向、backend-agnostic 的可复现文献检索基础设施**。

GitHub open issues 是执行状态来源；本文维护总体目标、依赖顺序和决策门。任何 milestone 归属都不自动授权 GPU、全量写入、部署或生产切换。

## 项目目标

项目从 SciClaims 的 literature search 组件拆分需求出发，首要应用场景为：

```text
Claim
  → high-recall literature retrieval
  → candidate articles
  → downstream Evidence Lab / verification
```

检索层只负责候选召回和 provenance，不负责 SUPPORT / CONTRADICT / NEI。

成功标准不是“某个向量模型可以把 PubMed 建完”，而是：

1. 同一 corpus/topic 可重复派生多个 retrieval projection；
2. Claim 的 gold evidence document 能以足够高 recall 被召回；
3. 查询结果能追溯到 PMID、语料版本、backend/model/index identity 和同版本文本；
4. 被选择 backend 可以正确处理 PubMed 新增、修订和删除；
5. 规模化成本与实际 retrieval 收益匹配。

## 核心架构原则

### Backend-agnostic

当前基线/候选：

- Elasticsearch/BM25：SciClaims-style `title + abstract` baseline；
- Jina-ColBERT-v2：当前已完成最多工程验证的 late-interaction 候选；
- MedCPT：在 #32 进入 biomedical retrieval 对照。

Jina 是当前工程化候选，不再是项目唯一主线。ES 不再标记为 legacy。

### Corpus identity 与 backend projection 分离

```text
PubMed source/version
  → normalized corpus
  → topic definition/version
      ├─ ES projection
      ├─ Jina projection
      └─ MedCPT / future projection
```

topic identity 由源语料、PMID 集合、筛选规则和文本版本定义；model/revision/index 参数属于各自 projection。

## 当前执行顺序

| 阶段 | 任务 | 目的 | 后续门 |
|---|---|---|---|
| 1 | #24 / PR #25 | 生成可复现关键词专题语料 | 不涉及模型选择 |
| 2 | #26 / PR #27 | 正式化 Jina 8K backend/build profile | 保留 ES baseline 和 backend-agnostic factory |
| 3 | #30 | Jina 真实专题库 build/reload/query/manifest 闭环 | 只证明候选可运行 |
| 4 | #32 | Claim→Evidence Retrieval Value Gate | 决定后续 backend 投入 |
| 5 | #11 | 对被选择 backend 实现专题增量 | #32 前保持 HOLD |
| 6 | #28 | 条件性 Jina RTX3060/WSL2 规模化门禁 | 仅当 #32 选 Jina 且 #11 Jina 路线通过 |
| 7 | 后续新 issue | 被选择 backend 的全量/服务化 | 单独授权 |

### 当前父任务

**#7：Claim→Evidence 检索基础设施主线：专题库→价值门→后端决策→全量**

#7 是当前主线父任务；复杂设计与核心代码由 owner 负责。johnmuin 只执行明确标记 `Execution gate: READY` 且已冻结命令/停止条件的任务。

## Gate A：专题 corpus 与 Jina 候选闭环

### #24 — 专题语料

必须保存：

- source corpus identity；
- keywords / any|all / case sensitivity；
- PMID 集合；
- collection/mapping hash；
- filter manifest。

不得把 Jina model/revision 写成 topic corpus 本身的 identity。

### #26 — Jina profile

Jina 当前固定验证 profile：

- model: `jinaai/jina-colbert-v2`
- revision: `a9dc5cd7293d4c71dbbba04829923ba4d0e4f6ea`
- doc_maxlen=8192
- dim=128
- nbits=2
- query_maxlen=32
- index_bsize=8
- kmeans_niters=4

这些是 **Jina projection 参数**，不是全项目唯一检索合同。

### #30 — 真实专题闭环

流程：

```text
topic corpus
  → verify
  → Jina build/coalesce
  → reload/query
  → PMID/text version check
  → projection manifest/receipt
```

#30 完成后进入 #32，不直接进入复杂 Jina 增量。

## Gate B：#32 Claim→Evidence Retrieval Value Gate

这是当前最重要的技术决策门。

至少比较：

1. SciClaims-style Elasticsearch/BM25；
2. Jina-ColBERT-v2；
3. MedCPT。

第一指标：

- gold evidence document Recall@10；
- Recall@50；
- Recall@100。

辅助指标：

- MRR / gold evidence rank；
- 冷/暖查询延迟；
- index size；
- build cost；
- update/rebuild cost；
- 漏召回类型。

公开 claim-evidence 数据用于可重复回归；同时需要一组 PubMed-grounded claim→gold PMID/evidence 小样本验证真实用途。

不以标题自检索、普通 relevance score 或“能建库”代替 evidence recall。

Hybrid/rerank 只有在单后端 error analysis 显示互补后才进入实验。

## Gate C：#11 被选择 backend 的专题增量

#32 前保持 HOLD。

通用语义必须支持：

- PubMed 新增；
- 完整修订；
- 删除；
- 重放同一 updatefile；
- 同名文件 hash 变化 fail closed；
- 查询时新旧版本不混用；
- 发布/账本中断恢复；
- PMID 作为长期外部身份。

Backend-specific 机制后置到选择完成后。

若 Jina 被选择，先比较受控重建、delta/tombstone、现成 multivector update/delete 方案，不预先自行实现复杂 PLAID delta lifecycle。

## Gate D：规模化

### #28 — Jina 条件性门禁

只有同时满足：

- #32 选择 Jina；
- #11 的 Jina 增量路线通过；

才启动 RTX3060/WSL2 代表性 10k 规模化测试。

若 #32 选择其他 backend，#28 关闭为 `not planned`。

即使 #28 通过，也只说明 Jina 全量候选可行；39,928,371 条正式执行必须另建 issue、另行授权。

## 已冻结但不代表 backend 选择的事实

- Jina tokenizer 全量审计：4 / 39,928,371 条超过 8K；
- P40 已证明 Jina 可运行，但不作为全量主力；
- 旧 ColBERTv2 256/512 截断路线不恢复；
- GTE/PyLate 全量路线停止，历史结果保留；
- 不允许静默截断后宣称完整覆盖；
- backend/model/index 任何变化必须形成可追溯的新 projection/version。

## Milestone 5 当前语义

M5 现在承载**Claim→Evidence retrieval backend 选择与专题闭环**，而不是“Jina 必然走到 39.9M”。

当前 M5 关键 issues：

- #7 父任务；
- #24 专题语料；
- #26 Jina profile；
- #30 Jina 专题闭环；
- #32 Claim→Evidence value gate；
- #11 条件性专题增量；
- #28 条件性 Jina 规模化门禁。

旧 milestone 中已关闭为 `not planned` 的 ColBERTv2 分片、supervisor、十片查询、512 重建等只保留历史证据，不重新恢复。

## 执行与协作

- open issue 的 `Execution gate` 是执行授权；
- `HOLD` 时不得因已有代码/实验继续运行；
- 大型 GPU、全量建库、数据改写和生产部署必须有单独明确授权；
- 代码、测试和文档通过 PR 进入 `dev`；
- 模型、语料、索引、内部路径和日志留在仓库外；
- 单元测试通过不等于真实 backend、检索质量或全量规模化已验收。

## 当前下一步

当前顺序是：

```text
#24 / #26
  → #30
  → #32
  → backend decision
  → #11
  → conditional scale gate
```

在 #32 完成前，不启动 Jina 39.9M 全量，不实现重型 Jina 增量体系，也不把任何 backend 宣布为最终胜者。
