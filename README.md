# literature-search-service

面向应用与研究工作流的文献检索服务项目，旨在支持文献数据的增量维护与统一检索。

## 项目状态

项目处于早期开发阶段。已提供 PubMed 核心字段解析、Elasticsearch 检索封装和 ColBERT 接口适配，尚未提供 HTTP 服务、可恢复导入流程或稳定 API。

`dev` 是开发集成分支。通过 GitHub milestones 定义交付、issues 记录任务与决策、
PR 审查变更；协作规则见 [AGENTS.md](AGENTS.md)。首版不自动运行 CI 或模型任务。

[ColBERT 实验工具](tools/colbert/README.md)提供只读输入校验与显式单分片构建入口。
[实验复盘](docs/colbert-experiment-review.md)记录已完成的服务器容量实验和未完成验收。
新入口只完成合成测试；现有服务器索引不等于本仓库已交付全量检索服务。

## 目标

- 支持文献数据的增量导入与更新。
- 提供可供不同应用使用的文献检索接口。
- 明确文献标识、数据来源和更新规则，使检索结果可追溯。

以上为项目目标，具体功能与接口将随设计和实现逐步确定。安装、使用和部署文档将在对应功能可用后提供。

## 设计文档

[首版交付路线图](docs/roadmap.md)记录增量顺序、依赖、验收条件与当前状态。

[PubMed 文献检索服务首版设计](docs/design/pubmed-search-v1.md)记录技术合同、上游行为基准和实现约束。

## 前置数据工具

[PubMed 更新文件同步工具](tools/pubmed/README.md)维护现有 crontab 下载脚本，支持失败诊断、续传与校验恢复，提供导入前的原始 updatefiles。其下载进度独立于服务导入进度；当前未接入服务自动执行。


## 本地开发验证

需要 Python 3.11 或更新版本。

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[test]'
.venv/bin/python -m pytest -q
```

普通测试只使用合成数据，不访问服务器。集成测试在未设置 `LSS_TEST_ES_URL` 时跳过；指定专用、可写的 Elasticsearch 8.13 测试实例后可执行：

```sh
LSS_TEST_ES_URL=http://localhost:19200 .venv/bin/python -m pytest -q -m integration
```

集成测试会创建并删除 `lss-test-<随机标识>` 索引。请仅使用隔离测试实例。

上游代码的来源和许可见 [第三方声明](THIRD_PARTY_NOTICES.md)。本项目自身开源许可证尚未选定。


## 检索后端

提供 ColBERT 配置时优先使用 ColBERT，仅未配置时选择 Elasticsearch。模型或索引加载失败不会自动切换后端；结果中的 `backend` 标明来源，`rank` 和 `score` 保留后端原始值（ES rank 从 0 开始，ColBERT 当前对接版本从 1 开始）。

ColBERT 通过 `create_search_backend(colbert_options=..., article_lookup=...)` 接入：初始化参数转交官方 Searcher，`article_lookup` 负责把同一索引版本的内部文档编号映射为带 PMID 的 Article。索引、模型和映射必须预先准备。当前 ColBERT 依赖环境仍在独立验证，未打包或自动安装；接口测试使用替身，不代表真实模型已在本项目验证通过。
