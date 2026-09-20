# ColBERT 单分片实验工具

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

`build` 需显式调用，使用预先安装的 ColBERT 和本地 checkpoint，输出目录必须不存在：

```sh
python -m literature_search_service.colbert_build build \
  --collection "$COLLECTION" --mapping "$MAPPING" --expected "$EXPECTED" \
  --checkpoint "$CHECKPOINT" --output "$NEW_BUILD_DIR" --gpus 0 1 --doc-maxlen 256
```

该命令会使用 GPU、内存和磁盘，并生成索引。调用者必须提供资源隔离且保持输入不可变。
GPU 编号相对于调用者的 CUDA_VISIBLE_DEVICES；不会自动安装、下载、启停服务或恢复旧目录。
coalesce 使用 Indexer 返回的真实路径，通过同一 Python 的 `-m colbert.utils.coalesce`
启动，避免路径重复配置及标准库 logging 遮蔽。成功状态为
`coalesced_not_query_validated`，不能据此宣称查询验收完成。

已测试输入验证、路径交接与失败记录；build/coalesce 测试使用替身。
历史真实实验使用 Python 3.10.12，而本项目要求 Python >=3.11；新入口尚未完成目标
环境真实小样本验证。先完成环境兼容 issue，再进行受限冒烟测试；不要直接跑全量。

固定实验参数为 dim=128、nbits=2、query_maxlen=32、index_bsize=64、kmeans_niters=4。
doc_maxlen=256 是实验默认值；约 253 个正文子词后不进入向量，完整输入文件仍保留。
模型与源码版本见[实验复盘](../../docs/colbert-experiment-review.md)。

准备/分片、完整版本清单、资源 supervisor、恢复和多分片查询均由后续 issues 跟踪。
不把旧事故脚本作为正常执行入口。
