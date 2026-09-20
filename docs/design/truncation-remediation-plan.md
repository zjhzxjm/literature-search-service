# 截断调查事实与可复现数据（#7 只读调查）

状态：**事实记录与实验数据，不含方案**。修复路线、passage 聚合/排名合同、
go/no-go、资源线与全量重跑策略属 owner 决策，不在本文件内冻结（审查意见与
#18 证据回传后移交）。历史运行环境与构建凭据的证据链见 #18 结果评论。

## 1. 三层事实（只读核实，2026-09-20）

核实途径：仓库内代码与文档 + 对实验工作区实际脚本的只读审查（来源指纹见
[实验复盘](../colbert-experiment-review.md)；实际执行 worker 为复盘所录
finish2 worker `649300be…` 的直系变体，编码调用逐行核对）+ 两次
tokenizer-only 小样本测量。未加载模型、未使用 GPU、未扫描全量语料。

### 1.1 原文保存

完整保留。`collection.tsv` 每行为 `PID\t标题 摘要`；`articles.jsonl` 按行保存
`[PID, PMID, 标题, 摘要]` 四元组；另有 `id-pmid.u64`、`source-position.u32`。
仅空白规范化（`' '.join(split())`），无删字。空标题且空摘要的 36,617 条单独
登记于 `nonsearchable.jsonl`，不静默丢弃。

### 1.2 prepare 统计口径

`truncated_tokenizer_gt255 = 19,393,571`（39,928,371 的 48.57%）。口径：同一
AutoTokenizer、`add_special_tokens=True`（含 [CLS]/[SEP]）、不截断计数
`> 255`，等价于**正文 > 253 token**；按批 512 条累计。

证据链（依 #18 回传）：该统计与 Indexer 编码发生在**同一 worker 进程**，使用
**同一 checkpoint 目录**（`AutoTokenizer.from_pretrained(<checkpoint>)` 与
`Indexer(checkpoint=<同一目录>)`）；实际运行环境的两个 colbert 副本
（PYTHONPATH source 与 site-packages 0.2.22）在截断相关文件上 diff 一致；
tokenizer 为 BertTokenizer（do_lower_case、无 bos/eos，CLS/SEP 各占 1）。
在该证据链下，此口径与 1.3 的实际编码阈值一致，可作为**被截断文档的计数**；
它不含每篇丢失量的分布，分布见 §2。

### 1.3 实际 embedding 截断

- **文档侧正文容量 ≤ 253**：`doc_maxlen=256`，实际 ColBERT 源码（复盘指纹
  `cc4f3dc9`）`DocTokenizer.tensorize` 先以 `max_length=doc_maxlen-1` 调 HF
  tokenizer（默认加 [CLS]/[SEP]），再前插 [D]，故 [D]+[CLS]+[SEP] 占 3。
- **查询侧正文容量 ≤ 29**：`query_maxlen=32`，同结构（[Q]+[CLS]+[SEP] 占 3）。
  查询在检索时编码、不入索引（结构性事实；调整效果未评估）。
- **截断模式** `longest_first`，从序列尾部切；文本顺序为**标题 + 单空格 +
  摘要**。因此当标题本身不超过窗口时（常见情形），被截断的是摘要尾部；
  样本中标题 >253 的占比约 **0.0005%**（存在但极罕见），此时标题尾部同样
  被截断、摘要可能完全不入窗口。
- 模型结构具备 512 位置容量（`max_position_embeddings=512`、tokenizer
  `model_max_length=512`）。这**仅是结构事实**：256→512 的检索质量、显存/
  内存、吞吐与索引体量均未经检验。

## 2. 长度分布测量（tokenizer-only，CPU，未加载模型）

方法：对冻结 collection/articles 以步长 199 等距抽样 200,000 行，同一模型
tokenizer（`add_special_tokens=True`、不截断）测量；正文长度已扣除 CLS/SEP。

### 2.1 正文（标题+空格+摘要）

| 指标 | 值 |
|---|---|
| 正文 > 253（与全量统计 48.57% 对账） | **48.64%**（吻合） |
| 正文 > 509 | 5.38% |
| 正文 > 761 | 0.33% |
| 分位数 p50 / p90 / p99 / p99.9 / max | 246 / 458 / 655 / 915 / 2178 |
| 未截断平均正文长度 | 234.0 token |
| 253 窗口未覆盖的文本量占比 | 28.4% |
| 509 窗口未覆盖占比 | 2.08% |
| 向量总量比例（509 窗口 / 253 窗口，样本口径） | 1.362x |

### 2.2 标题（单独测量）

| 指标 | 值 |
|---|---|
| 标题 > 253 | 0.0005%（max 318） |
| 标题 > 29（查询正文容量） | **18.79%** |
| 标题分位数 p50 / p90 / p99 | 20 / 34 / 51 |

### 2.3 限制

等距抽样单次执行；样本隐含平均向量数与既有预算假设值
（`vectors_per_record_assumed=156.44`）及按实际索引体量反推值存在 ±8% 级
差异，比例的置信度高于绝对值；分段（passage）相关数量依赖 passage 语义
定义（整体切块 vs 标题重复+摘要切块），本文件不提供分段预算。

## 3. 证据链与来源

| 证据 | 来源 |
|---|---|
| 编码参数（doc_maxlen=256、query_maxlen=32、dim=128、nbits=2、index_bsize=64、kmeans_niters=4、nranks=2） | 实际执行 worker.py build() 第 58 行 + run-config.json |
| 模型身份 | colbert-ir/colbertv2.0 @ `c1e84128`（run-config model_revision）；tokenizer BertTokenizer、model_max_length 512 |
| ColBERT 源码版本 | `cc4f3dc9`（code-revision.json，含签名验证 payload；tarball 源码，非 git checkout） |
| 截断语义代码 | 该源码 `DocTokenizer.tensorize` / `QueryTokenizer.tensorize`（两副本一致） |
| 统计口径代码 | resume worker.py prepare()（同进程同 checkpoint 写 `prepared.json`） |
| 10 个逻辑索引状态 | shard-1…9 各自 completed；第 10 个 subset（build 与 finish 分布于两个目录）；10 路统一查询验收未做 |

## 4. 边界与移交

- 本轮未执行 GPU/建库/核心实现修改；抽样测量的命令形态与限制见 §2。
- 修复路线、passage 语义、聚合/排名合同、资源线、验收判据与重跑策略由
  owner 基于 #18 证据与本文数据冻结；本文数据可直接复用于任意路线的预算
  推导（方法：向量数 = Σ min(正文, 窗口−3) + 3×记录数）。
