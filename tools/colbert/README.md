# Jina-ColBERT-v2 建库工具

包内入口：`python -m literature_search_service.colbert_build`。这是首次整理的
实验入口，不是全量服务、通用恢复器或受资源监督的作业系统。

`verify` 只读、无需 ColBERT。输入为完整规范化标题摘要的 TSV，以及每行两个
little-endian uint64（本地 PID、PMID）的二进制映射。expected JSON 必须来自
已冻结的准备阶段，字段为 `records`、`collection_sha256`、`mapping_sha256`。
它检查哈希、行数、连续本地 PID、映射对齐及非空文本，不证明跨分片无重复或来源正确。

```sh
python -m literature_search_service.colbert_build verify \
  --collection "$COLLECTION" --mapping "$MAPPING" --expected "$EXPECTED"
```

`build` 需显式调用，使用预先安装的 colbert-ai 和本地 Jina-ColBERT-v2 checkpoint，输出目录必须不存在。该 Jina backend 的默认 build profile 为 8K；这不是项目级唯一检索默认：

```sh
python -m literature_search_service.colbert_build build \
  --collection "$COLLECTION" --mapping "$MAPPING" --expected "$EXPECTED" \
  --checkpoint "$JINA_CHECKPOINT" --output "$NEW_BUILD_DIR" --gpus 0
```

需要覆盖默认值时可显式传入全部参数；下面示例与当前冻结的 Jina profile 等价，不代表 RTX3060 吞吐已经验收：

```sh
python -m literature_search_service.colbert_build build \
  --collection "$COLLECTION" --mapping "$MAPPING" --expected "$EXPECTED" \
  --checkpoint "$JINA_CHECKPOINT" --checkpoint-revision "$JINA_REVISION" \
  --output "$NEW_BUILD_DIR" --gpus 0 \
  --dim 128 --nbits 2 --doc-maxlen 8192 --query-maxlen 32 \
  --index-bsize 8 --kmeans-niters 4
```

长上下文值不会仅凭 CLI 数字放行：工具会从本地 `config.json` /
`tokenizer_config.json` 读取可用 context metadata；声明的 `doc_maxlen` 超过
checkpoint 本地上限时会在启动 GPU 之前失败。若 checkpoint 没有可核验的上下文元数据，
超过 512 的值同样拒绝。构建回执会保存 checkpoint config 哈希、可选 revision 和全部实际参数。

该命令会使用 GPU、内存和磁盘，并生成索引。调用者必须提供资源隔离且保持输入不可变。
GPU 编号相对于调用者的 CUDA_VISIBLE_DEVICES；不会自动安装、下载、启停服务或恢复旧目录。
coalesce 使用 Indexer 返回的真实路径，通过同一 Python 的 `-m colbert.utils.coalesce`
启动，避免路径重复配置及标准库 logging 遮蔽。成功状态为
`coalesced_not_query_validated`，不能据此宣称查询验收完成。

已测试输入验证、路径交接与失败记录；build/coalesce 测试使用替身。
历史 ColBERTv2 256-token 实验、Python 3.10 环境和旧分片资产仅作为历史证据保留，
见[实验复盘](../../docs/colbert-experiment-review.md)，不再作为当前 Jina profile 的默认值。

当前 Jina profile 的真实专题库 build/reload/query 由 #30 验收；Claim→Evidence retrieval
价值由 #32 与 Elasticsearch/BM25、MedCPT 同口径比较。完成价值门前不要启动全量建库。
