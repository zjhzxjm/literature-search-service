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

## P100 环境与已有 mmap 库的查询

P100 的计算能力为 `6.0`。从原实验 GPU 换卡后，不能照搬旧脚本的
`TORCH_CUDA_ARCH_LIST=6.1`，也不能复用未核对 Python/PyTorch ABI 的扩展缓存。
`nvidia-smi` 的 CUDA 显示不是 PyTorch 所用的 CUDA runtime；应同时记录
`torch.__version__`、`torch.version.cuda`、`torch.cuda.get_arch_list()` 和实际设备能力。

在独立运行目录配置环境（变量路径由操作员提供，不改历史环境）：

```sh
: "${P100_RUNTIME_ROOT:?set a separate runtime directory}"
: "${COLBERT_PYTHON:?set the validated Python executable}"
export TORCH_CUDA_ARCH_LIST=6.0
export TORCH_EXTENSIONS_DIR="$P100_RUNTIME_ROOT/extensions"
export CUDA_CACHE_PATH="$P100_RUNTIME_ROOT/cuda-cache"
export PYTHONDONTWRITEBYTECODE=1
export MAX_JOBS=2 OMP_NUM_THREADS=4 MKL_NUM_THREADS=4 OPENBLAS_NUM_THREADS=4
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
export PATH="$(dirname "$COLBERT_PYTHON"):$PATH"
mkdir -p "$TORCH_EXTENSIONS_DIR" "$CUDA_CACHE_PATH"
```

确认所选 PATH 中存在 `ninja`。C++ 编译器也必须与实际 PyTorch 要求相符：
本次 Python 3.12 / PyTorch 2.14 环境编译旧 ColBERT CPU 扩展时要求 C++20，
旧 GCC10 失败，需使用已验证的 GCC11，而非继续强制旧工具链。
这些设置不安装或升级 CUDA，不授权建库，也不证明 CUDA 自定义扩展已经通过。

历史 ColBERT 源码的 `Searcher` 明确禁止 `load_index_with_mmap=True` 与 GPU
ranker 同用。已有全量 mmap 库使用 `CUDA_VISIBLE_DEVICES=""`、
`RunConfig(gpus=0)` 运行 CPU 检索；这里 `gpus=0` 表示不使用 GPU，
不是选择物理 GPU 0。不要为换卡把整片索引搬到 16 GiB 显存。
P100 query encoder 可单独验证，再将查询向量送入 CPU ranker；这是混合路径，
不是全 GPU 检索，且必须核对 FP16 导致的分数/排序差异。

验收分开记录：GPU 数值与编码、CPU 扩展编译、逐片查询及同版本 PMID 映射、
项目 Python 适配器、十片合并与 HTTP。前几项通过不等于后两项完成。
逐片串行限额验证不代表十片常驻内存或并发负载验收。不得以换卡为由改变
旧索引的编码参数或恢复已 HOLD 的模型/全量任务。

### 2026-10-14 换卡回归

在独立运行目录验证两张 P100 16 GiB，驱动 580.173.02。旧 Python 3.10.12 /
torch 1.13.1+cu117 保持不变作为对照；满足项目 Python 要求的查询环境为
Python 3.12.10 / torch 2.14.0+cu126 / transformers 4.49.0 / GCC 11.4。
新 venv 只读引用已有 Python 3.12 依赖，项目及其缺失依赖安装在新 venv；
扩展、CUDA 缓存独立。这是已验证的环境组合，不是可脱离原依赖目录的独立发行包。

- 两个环境均完成现有 10 片串行 mmap 回归，记录数合计 39,928,371；
  每片 3 个历史查询，CPU 路径 30/30 组 top-3 PMID 与历史结果一致。
- 新环境 90 个命中的 PMID、原始完整标题/摘要与该片规范化 collection 对账通过；
  使用只读定点定位，不代表对全库文本做过全面校验。
- P100 上两种环境均完成真实查询编码。旧环境的 GPU 编码回放 30/30 组一致；
  新环境为 29/30，一组同分边界候选发生变化，同时观察到 FP16 路径的分数差异。
  首版仍使用通过回归的 CPU 编码与 CPU mmap 检索，不自动启用 GPU 编码。
- 固定项目基线 `deab71f` 在新 Python 3.12 环境为 77 passed、1 skipped
  （未配置真实 ES）。项目 `ColBERTSearch` 对真实第一片执行 3 条查询 ×
  k=1/3/10，共 9 次通过，使用同版本原文定点读取；不是正式文本存储实现。
- 原 prepared article 行不包含 PMID revision，验收不伪造该字段；仍需后续
  版本合同约束。未验收十片统一服务、HTTP、常驻并发、Jina、双 rank 或新 baseline。

查询进程受内存/CPU/运行时间限制，禁用 swap；所有验收进程已退出。没有重建、
覆盖或删除旧索引，也没有更改旧环境。详细执行证据随本次兼容验收 PR 保存，
原始日志和机器路径不进入 Git。
