# PubMed 原始更新文件同步工具

`sync_pubmed.sh` 是现有 crontab 下载脚本的维护版本，仍然每次只处理下一个编号。本次完善失败恢复与诊断，不提供自动追赶积压的循环。

原始脚本于 2026-09-10 从 `pg-xujm:/share/data10/huggingface/pubmed/2026/updatefiles/sync_pubmed.sh` 复制；原始 SHA-256 为 `c3f255a28c428f934dbf841d90b845e2ed1fea5cbfed07ec2b617865047c4959`。当前文件已修改，不再是逐字相同的副本。远端脚本和 crontab 尚未更新。

## 运行条件与配置

目标环境为 Linux，依赖 Bash 4+、GNU wget、GNU coreutils 的 `timeout`/`md5sum`、util-linux 的 `flock`，以及常规文件操作命令。执行用户须对数据目录有写权限，并可访问 NCBI。

可通过环境变量覆盖配置，无需改变原有无参数 cron 调用方式：

| 变量 | 默认值 | 含义 |
|---|---|---|
| `BASE_DIR` | `/share/data10/huggingface/pubmed/2026/updatefiles` | 已存在的数据目录 |
| `FILE_PREFIX` | `pubmed26n` | 年度文件名前缀 |
| `URL_PREFIX` | `https://ftp.ncbi.nlm.nih.gov/pubmed/updatefiles` | 下载地址 |
| `MAX_RETRIES` | `3` | 每次调用对同一编号最多尝试次数 |
| `RETRY_DELAY` | `10` | 两次尝试间隔秒数，可为 0 |
| `IO_TIMEOUT` | `60` | wget DNS、连接、读取超时；小型辅助文件的总时限 |
| `DOWNLOAD_TIMEOUT` | `1800` | 单次 XML 下载命令的总时限，秒 |

`lastest` 沿用原拼写，必须预先保存最后成功文件的非负数字编号（最多八位）。缺失或无效时停止，不自行猜测起点。切换年度时须同时调整目录、文件名前缀及起始编号。

## 下载与恢复行为

1. 使用 `.sync_pubmed.lock` 防止新版脚本重叠运行。锁占用时返回 75，其余锁错误保留原退出码；锁文件不应删除，进程退出自动释放锁。
2. 获取下一个 XML 文件的 MD5。只接受匹配当前文件名的单条 NCBI `MD5(filename)= hash` 或标准 `hash  filename` / `hash *filename` 记录。
3. 已存在的正式 XML 若通过本次 MD5 校验，直接复用；否则下载到 `.xml.gz.part`。网络中断或超时保留临时文件，下次尝试或下一次调用续传。
4. 临时文件下载完成但 MD5 不一致时，记录预期值和实际值，删除该临时文件，下一次尝试重新下载。既有正式文件在新副本通过校验前保持不变。
5. 校验成功后在同一目录重命名发布 XML 和 MD5，再尝试下载辅助 `_stats.html`。统计 HTML 失败会告警，但不阻塞 XML 下载进度。
6. 使用临时文件加重命名更新 `lastest`。下载、MD5 解析或校验失败均不推进。若 XML 已发布但进度写入前中断，下次重新验证后可复用。

保留 `.part` 文件是为了恢复，不代表下载完成；下游只能消费通过校验的正式文件，并维护自身导入进度。该工具不处理 baseline、解析、索引或服务导入账本，项目也未自动调用它。

## 日志与限制

`sync.log` 追加尝试编号、wget HTTP 响应和错误、退出码、校验结果及进度。单个 wget 使用 `--tries=1`，重试由脚本统一管理；退出码 124 表示达到总时限，137 可能表示随后被强制终止。持续缓慢传输也受总时限约束，超时后可续传，但不保证在网络持续异常时下载成功。

当前仍直接请求下一个编号；若尚未发布，404 会作为下载失败记录并保持进度。本次没有增加 FTP 列表扫描、自动补齐、并行下载或自动调度。

新锁只约束使用同一锁的新版本实例，不能阻止正在运行的旧脚本。上线前须等旧版手工补齐和 cron 实例退出，再替换远端脚本，避免两版同时写入。尚未执行此上线操作。

## 本地验证

```sh
bash -n tools/pubmed/sync_pubmed.sh
.venv/bin/python -m pytest -q tests/test_sync_pubmed.py
```

测试使用临时目录、合成文件、仅绑定 `127.0.0.1` 的 HTTP 服务和真实 wget；覆盖成功、两种 MD5 格式、断线续传、损坏后重下、HTTP/校验失败、总超时、统计文件失败、进度恢复和锁互斥。不访问 NCBI 或服务器数据目录。

macOS 没有 util-linux `flock` 时，测试使用 Python `fcntl.flock` 对继承的文件描述符加锁；Linux 使用实际 `flock` 命令。本地测试不等于目标服务器原生工具和文件系统验收。

### 2026-09-10 验证记录

- 隔离回归：18 项通过；本地 `bash -n` 通过。
- 真实下载：本地时间 17:32:36 至 17:34:11，从默认 NCBI 地址取得 `pubmed26n1340.xml.gz`（6,836,533 字节）、MD5 和统计 HTML，均返回 HTTP 200；首轮尝试成功。
- MD5 为 `edfedc08afe50bce7b6a55dbe2654c91`，脚本校验通过；额外执行 `gzip -t` 通过。临时目录内 `lastest` 从 1339 推进到 1340，没有下载 1341，没有遗留 XML `.part`。
- 实测使用上述 macOS 锁辅助实现；Bash、wget、timeout 和 MD5 校验实际执行。真实 NCBI 下载未发生中断，续传及失败恢复的证据来自隔离故障测试。
- 真实语料、MD5、统计 HTML、日志、临时锁和测试辅助文件在验证后清理；仅保留本节汇总，不将下载数据纳入 Git。
- 尚未替换或执行远端新版脚本，未修改生产进度和 crontab；目标环境完整运行验收仍未完成。
