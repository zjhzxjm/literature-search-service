# ColBERT 单分片实验工具

包内入口：`python -m literature_search_service.colbert_build`。这是首次整理的
实验入口，不是全量服务、通用恢复器或受资源监督的作业系统。

## 按关键词生成专题建库输入

`python -m literature_search_service.corpus_filter` 可以从一个已经冻结并带哈希清单的
`collection.tsv + id-pmid.u64 + expected.json` 流式筛选出专题子语料库。原始输入只读，
命中的记录会从 local PID 0 开始连续重编号，同时保留 PMID。输出目录必须不存在。

首版使用**字面子串匹配**，默认 Unicode 大小写不敏感；`--mode any` 表示命中任意关键词，
`--mode all` 表示同一篇标题+摘要必须包含全部关键词。可重复传 `--keyword`，也可以用
UTF-8 文本文件每行提供一个关键词。筛选字段就是实际 ColBERT collection 中的规范化
`title + abstract` 文本，不执行 PubMed 查询语法、stemming、正则或同义词扩展。

```sh
python -m literature_search_service.corpus_filter \
  --collection "$FULL_COLLECTION" \
  --mapping "$FULL_MAPPING" \
  --expected "$FULL_EXPECTED" \
  --output "$FILTERED_INPUTS" \
  --keyword "large language model" \
  --keyword "retrieval augmented generation" \
  --mode any
```

关键词较多时：

```sh
python -m literature_search_service.corpus_filter \
  --collection "$FULL_COLLECTION" --mapping "$FULL_MAPPING" \
  --expected "$FULL_EXPECTED" --output "$FILTERED_INPUTS" \
  --keyword-file keywords.txt --mode all
```

输出包含：

- `collection.tsv`：筛选后的完整建库文本，local PID 连续；
- `id-pmid.u64`：新的 local PID 到原 PMID 的二进制映射；
- `expected.json`：可直接交给 `colbert_build verify/build` 的记录数与 SHA-256；
- `filter.json`：源输入身份、完整关键词配置、匹配模式和结果身份。

源 collection/mapping 的结构或哈希不匹配时命令失败；0 命中同样失败并不发布空输出。
因此专题库可以独立留存 `filter.json + expected.json` 作为可重现证据，而不用修改原全量语料。

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
