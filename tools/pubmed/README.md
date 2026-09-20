# PubMed 原始更新文件同步工具

`sync_pubmed.sh` 是现有 crontab 下载脚本的维护版本，每轮读取一次上游目录快照，从 `lastest + 1` 按编号连续下载到快照中的最新文件。同一天发布多个文件以及前几天积压的文件都会处理，不按发布日期限制范围。

本工具由既有下载脚本整理而来；原始 SHA-256 为 `c3f255a28c428f934dbf841d90b845e2ed1fea5cbfed07ec2b617865047c4959`。原运行环境的脚本和调度配置尚未更新。

## 运行条件与配置

目标环境为 Linux，依赖 Bash 4+、GNU wget、GNU coreutils 的 `timeout`/`md5sum`、util-linux 的 `flock`，以及 `grep`、`sed`、`sort` 和常规文件操作命令。执行用户须对数据目录有写权限，并可访问 NCBI。

通过环境变量配置。迁移旧 cron 时必须显式设置 `BASE_DIR`；未设置或为空会在网络与文件操作前停止：

| 变量 | 默认值 | 含义 |
|---|---|---|
| `BASE_DIR` | 无，必填 | 已存在的数据目录 |
| `FILE_PREFIX` | `pubmed26n` | 年度文件名前缀 |
| `URL_PREFIX` | `https://ftp.ncbi.nlm.nih.gov/pubmed/updatefiles` | 下载地址 |
| `MAX_RETRIES` | `3` | 每次调用对同一编号最多尝试次数 |
| `RETRY_DELAY` | `10` | 两次尝试间隔秒数，可为 0 |
| `IO_TIMEOUT` | `60` | wget DNS、连接、读取超时；小型辅助文件的总时限 |
| `DOWNLOAD_TIMEOUT` | `1800` | 单次 XML 下载命令的总时限，秒 |

`lastest` 沿用原拼写，必须预先保存最后连续成功文件的非负数字编号（最多八位）。缺失或无效时停止，不自行猜测起点。切换年度时须同时调整目录、文件名前缀及起始编号。

## Linux 运行与迁移步骤

通用 Linux 主机接入顺序：

1. 确认原生工具链：Bash 4+、GNU wget、GNU coreutils（`timeout`、`md5sum`）、util-linux `flock`。用 `command -v flock` 与 `python3 -c "import shutil; print(shutil.which('flock'))"` 确认解析到系统路径而非自制 shim；缺原生工具时先由管理员安装，不以替代实现上线。
2. 把脚本放进与数据目录分离的独立位置（随仓库 checkout，或仅复制 `tools/pubmed/sync_pubmed.sh`），核对脚本 SHA-256 与交付版本一致。
3. 操作员准备已存在的数据目录：写入 `lastest`（最后连续成功编号），核对或迁入既有年度文件，执行用户对该目录有写权限。
4. 接入真实目录前，先在隔离 checkout 完成本文件“本地验证”一节的命令。
5. 首次运行显式设置 `BASE_DIR` 并观察 `sync.log` 的追平与进度推进，确认后再交给调度。

变量化运行示例（路径为占位，由操作员替换）：

```sh
BASE_DIR=/srv/pubmed/updatefiles FILE_PREFIX=pubmed26n \
  bash /opt/pubmed-sync/sync_pubmed.sh
```

crontab 条目同样必须显式传入 `BASE_DIR`（仅示例，不构成部署指令）：

```cron
17 3 * * * BASE_DIR=/srv/pubmed/updatefiles /usr/bin/bash /opt/pubmed-sync/sync_pubmed.sh
```

从旧 cron 版本迁移时按顺序执行：先让旧实例结束（停止旧 cron 触发、等待或终止旧进程、手工补齐完成），再由操作员设置新的 `BASE_DIR` 并迁移 `lastest` 与年度文件，最后替换脚本版本并恢复调度。`BASE_DIR` 未设置或为空会在任何网络与文件操作前失败；迁移期间不要以空值临时运行。

## 下载与恢复行为

1. 使用 `.sync_pubmed.lock` 防止新版脚本重叠运行。锁占用时返回 75，其余锁错误保留原退出码；锁文件不应删除，进程退出自动释放锁。
2. 获取上游年度 XML 文件列表，按编号确定本轮范围；失败或无法解析时明确报错，不能当作已追平。循环处理每个连续编号，获取其 MD5。只接受匹配当前文件名的单条 NCBI `MD5(filename)= hash` 或标准 `hash  filename` / `hash *filename` 记录。
3. 已存在的正式 XML 若通过本次 MD5 校验，直接复用；否则下载到 `.xml.gz.part`。网络中断或超时保留临时文件，下次尝试或下一次调用续传。
4. 临时文件下载完成但 MD5 不一致时，记录预期值和实际值，删除该临时文件，下一次尝试重新下载。既有正式文件在新副本通过校验前保持不变。
5. 校验成功后在同一目录重命名发布 XML 和 MD5，再尝试下载辅助 `_stats.html`。统计 HTML 失败会告警，但不阻塞 XML 下载进度。
6. 使用临时文件加重命名更新 `lastest`。下载、MD5 解析或校验失败均不推进。若 XML 已发布但进度写入前中断，下次重新验证后可复用。每个文件完成后继续下一个，直至本轮快照上限；中途耗尽重试或目录缺号时停止，不越过失败编号。

保留 `.part` 文件是为了恢复，不代表下载完成；下游只能消费通过校验的正式文件，并维护自身导入进度。该工具不处理 baseline、解析、索引或服务导入账本，项目也未自动调用它。

## 日志与限制

`sync.log` 追加尝试编号、wget HTTP 响应和错误、退出码、校验结果及进度。单个 wget 使用 `--tries=1`，重试由脚本统一管理；退出码 124 表示达到总时限，137 可能表示随后被强制终止。持续缓慢传输也受总时限约束，超时后可续传，但不保证在网络持续异常时下载成功。

已追平时正常退出，不请求尚未发布的下一编号。执行期间新增的上游文件留到下次运行。配置好数据目录后可以沿用原调度频率。日志记录当前编号、上游快照上限、待处理数量及最终追平状态。

前提是 `lastest` 可信：脚本不审计或补回该编号以前被删除、遗漏或损坏的文件。如果曾手工调高进度并跳过文件，应先核实最后连续成功的编号；不能直接把 `lastest` 改成上游最大编号。积压较多时单轮可能运行较久，运行锁覆盖整轮。

新锁只约束使用同一锁的新版本实例，不能阻止正在运行的旧脚本。上线前须等旧版手工补齐和 cron 实例退出，再替换远端脚本，避免两版同时写入。尚未执行此上线操作。

## 本地验证

```sh
bash -n tools/pubmed/sync_pubmed.sh
.venv/bin/python -m pytest -q tests/test_sync_pubmed.py
```

测试使用临时目录、合成文件、仅绑定 `127.0.0.1` 的 HTTP 服务和真实 wget；覆盖成功、两种 MD5 格式、断线续传、损坏后重下、HTTP/校验失败、总超时、统计文件失败、进度恢复和锁互斥。不访问 NCBI 或服务器数据目录。

macOS 没有 util-linux `flock` 时，测试使用 Python `fcntl.flock` 对继承的文件描述符加锁；Linux 使用实际 `flock` 命令。本地测试不等于目标服务器原生工具和文件系统验收。

### 2026-09-10 单文件版本验证记录（提交 c2da227）

- 隔离回归：18 项通过；本地 `bash -n` 通过。
- 真实下载：本地时间 17:32:36 至 17:34:11，从默认 NCBI 地址取得 `pubmed26n1340.xml.gz`（6,836,533 字节）、MD5 和统计 HTML，均返回 HTTP 200；首轮尝试成功。
- MD5 为 `edfedc08afe50bce7b6a55dbe2654c91`，脚本校验通过；额外执行 `gzip -t` 通过。临时目录内 `lastest` 从 1339 推进到 1340，没有下载 1341，没有遗留 XML `.part`。
- 实测使用上述 macOS 锁辅助实现；Bash、wget、timeout 和 MD5 校验实际执行。真实 NCBI 下载未发生中断，续传及失败恢复的证据来自隔离故障测试。
- 真实语料、MD5、统计 HTML、日志、临时锁和测试辅助文件在验证后清理；仅保留本节汇总，不将下载数据纳入 Git。
- 尚未替换或执行远端新版脚本，未修改生产进度和 crontab；目标环境完整运行验收仍未完成。

### 多文件版本验证

本地 `bash -n` 与 `git diff --check` 通过；26 项隔离测试通过，测试临时目录已自动清理。新增同日多个编号的排序与去重、中途失败后下次恢复、已追平、目录请求失败、目录无法解析、缺号停止、运行中新增文件留到下一轮、本地进度超过上游等隔离用例。单文件版本的真实 NCBI 下载记录只证明当时的下载与校验流程，不代表新循环已做全量实测。

## 目标 Linux 验证记录

### 2026-09-20 隔离 Linux 环境验证（基线 8e11bcb，#12）

- 主机：隔离 Ubuntu 22.04.2 LTS，项目 venv 内 Python 3.12.10。工具链：GNU Bash 5.1.16、GNU Wget 1.21.2、GNU coreutils 8.32（`timeout`/`md5sum`）、util-linux `flock` 2.37.2。
- `shutil.which('flock')` 解析到 `/usr/bin/flock`，`dpkg -S` 确认属 util-linux 包；锁互斥与释放用例使用原生 `flock`，未启用 Python shim。
- 命令与结果：`.venv/bin/python -m pip install -e '.[test]'` 成功；`bash -n tools/pubmed/sync_pubmed.sh` 通过；`.venv/bin/python -m pytest -q tests/test_sync_pubmed.py` 收集 28 项、全部通过、零跳过（17.66s）；`git diff --check` 通过。全量 `.venv/bin/python -m pytest -q` 为 77 通过、1 跳过（未配置一次性真实 Elasticsearch 实例的集成用例，符合预期）。
- 被测脚本 SHA-256：`450a632d1ea8df95ca7ef52ae08f5bcb49e92e637c4de09b3edca1c5aa9dae00`，与基线 `8e11bcb` 的 `tools/pubmed/sync_pubmed.sh` 一致，下载器行为未被修改。
- 覆盖确认：两种 MD5 格式、断线续传（当轮重试与下次调用）、损坏重下、失败不推进、进度恢复、目录快照固定、缺号停链、锁互斥与释放，以及 `BASE_DIR` 缺失或为空在任何文件与网络操作前失败，均有对应通过用例。
- 未执行指向真实 PubMed 数据目录或默认 NCBI 地址的同步；未修改 crontab、生产目录或共享数据；验证所用 checkout、venv 与临时数据在记录汇总后清理。
