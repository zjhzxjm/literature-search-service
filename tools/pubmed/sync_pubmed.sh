#!/bin/bash
# 按编号追平本轮上游目录快照；下载进度不代表服务导入进度。
set -euo pipefail

BASE_DIR="${BASE_DIR:-/share/data10/huggingface/pubmed/2026/updatefiles}"
FILE_PREFIX="${FILE_PREFIX:-pubmed26n}"
URL_PREFIX="${URL_PREFIX:-https://ftp.ncbi.nlm.nih.gov/pubmed/updatefiles}"
MAX_RETRIES="${MAX_RETRIES:-3}"
RETRY_DELAY="${RETRY_DELAY:-10}"
IO_TIMEOUT="${IO_TIMEOUT:-60}"
DOWNLOAD_TIMEOUT="${DOWNLOAD_TIMEOUT:-1800}"

for command in wget md5sum flock timeout mktemp mv rm cat date sleep grep sed sort; do
    command -v "${command}" >/dev/null || { echo "缺少依赖: ${command}" >&2; exit 1; }
done
for value in "${MAX_RETRIES}" "${IO_TIMEOUT}" "${DOWNLOAD_TIMEOUT}"; do
    [[ "${value}" =~ ^[1-9][0-9]{0,5}$ ]] || { echo "重试次数和超时必须是正整数（最多六位）" >&2; exit 1; }
done
[[ "${RETRY_DELAY}" =~ ^(0|[1-9][0-9]{0,5})$ ]] || exit 1
[[ "${FILE_PREFIX}" =~ ^pubmed[0-9]{2}n$ ]] || exit 1
cd "${BASE_DIR}"
LOG_FILE="${PWD}/sync.log"
LAST_FILE="${PWD}/lastest"
log() { printf '%s - %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >> "${LOG_FILE}"; }

# 锁文件保持存在；flock 在进程结束后自动释放锁。
exec 9> .sync_pubmed.lock
if flock -n -E 75 9; then
    :
else
    rc=$?
    log "未启动: 无法取得运行锁，退出码=${rc}（75 表示已有实例运行）"
    exit "${rc}"
fi
if ! CURRENT_IDX=$(cat "${LAST_FILE}"); then
    log "错误: 无法读取 lastest，未下载"
    exit 1
fi
if [[ ! "${CURRENT_IDX}" =~ ^[0-9]{1,8}$ ]]; then
    log "错误: lastest 缺失或不是有效的非负数字编号，未下载"
    exit 1
fi
CURRENT_IDX=$((10#${CURRENT_IDX}))
STATE_TMP=""
LIST_TMP=""
trap 'if [[ -n "${STATE_TMP}" ]]; then rm -f -- "${STATE_TMP}"; fi; if [[ -n "${LIST_TMP}" ]]; then rm -f -- "${LIST_TMP}"; fi' EXIT

# 每次 wget 只尝试一次，由外层负责重试。总时限也覆盖持续缓慢传输。
fetch() {
    local name=$1 output=$2 resume=$3 limit=$4 rc
    if [[ "${resume}" == yes ]]; then
        set -- --continue
    else
        set --
    fi
    if timeout --kill-after=10 "${limit}" wget --no-verbose --server-response \
        --tries=1 --timeout="${IO_TIMEOUT}" "$@" \
        -O "${output}" "${URL_PREFIX%/}/${name}" >> "${LOG_FILE}" 2>&1; then
        return 0
    else
        rc=$?
        log "下载失败: ${name}，退出码=${rc}（124 为总时限，137 可能为强制终止），临时文件=${output}"
        return 1
    fi
}

# 只接受绑定当前文件名的单条摘要，不执行外部 MD5 文件中的路径。
read_expected_md5() {
    local line hash name
    line=$(cat "${MD5_PART}")
    if [[ "${line}" =~ ^MD5\(([^\)]+)\)=[[:blank:]]*([[:xdigit:]]{32})$ ]]; then
        name=${BASH_REMATCH[1]}; hash=${BASH_REMATCH[2]}
    elif [[ "${line}" =~ ^([[:xdigit:]]{32})[[:blank:]]+\*?([^[:space:]]+)$ ]]; then
        hash=${BASH_REMATCH[1]}; name=${BASH_REMATCH[2]}
    else
        log "错误: ${FILENAME}.md5 格式无效或包含多条记录"
        return 1
    fi
    if [[ "${name}" != "${FILENAME}" ]]; then
        log "错误: MD5 文件名不匹配，预期=${FILENAME}，实际=${name}"
        return 1
    fi
    EXPECTED=${hash}
}

verify() {
    local actual
    [[ -f "$1" ]] || return 1
    actual=$(md5sum -- "$1") || return 1
    actual=${actual%% *}
    if [[ "${actual,,}" == "${EXPECTED,,}" ]]; then
        return 0
    fi
    log "校验不一致: $1，expected=${EXPECTED}，actual=${actual}"
    return 1
}

attempt_download() {
    fetch "${FILENAME}.md5" "${MD5_PART}" no "${IO_TIMEOUT}" || return 1
    read_expected_md5 || return 1
    # 兼容旧版已下载文件，也支持文件发布成功但进度写入前中断的恢复。
    if verify "${FILENAME}"; then
        log "复用已校验文件: ${FILENAME}"
    else
        fetch "${FILENAME}" "${PART}" yes "${DOWNLOAD_TIMEOUT}" || return 1
        if ! verify "${PART}"; then
            log "丢弃校验失败的临时文件，下次从头下载: ${PART}"
            rm -f -- "${PART}"
            return 1
        fi
        mv -f -- "${PART}" "${FILENAME}" || return 1
    fi
    mv -f -- "${MD5_PART}" "${FILENAME}.md5" || return 1
    log "校验成功: ${FILENAME}"
}

# 每轮只获取一次目录快照，运行中新增的文件留到下一轮。
LIST_TMP=$(mktemp "${PWD}/.sync_pubmed.list.XXXXXX")
listing_ok=no
for ((attempt=1; attempt<=MAX_RETRIES; attempt++)); do
    if fetch "" "${LIST_TMP}" no "${IO_TIMEOUT}"; then
        listing_ok=yes
        break
    fi
    if (( attempt < MAX_RETRIES )); then sleep "${RETRY_DELAY}"; fi
done
if [[ "${listing_ok}" != yes ]]; then
    log "错误: 无法读取上游目录，lastest 保持 ${CURRENT_IDX}"
    exit 1
fi
# 只解析当前年度的 XML 下载链接，排除摘要、统计文件及页面中的其他数字。
if ! indices=$(grep -oE "href=[\"']${FILE_PREFIX}[0-9]{1,8}\\.xml\\.gz[\"']" "${LIST_TMP}" |
    sed -E 's/.*n([0-9]+)\.xml\.gz.*/\1/' | sort -nu); then
    log "错误: 上游目录没有可识别的 ${FILE_PREFIX} XML 链接，lastest 保持 ${CURRENT_IDX}"
    exit 1
fi
declare -A available
LATEST_IDX=0
while IFS= read -r idx; do
    idx=$((10#${idx}))
    available[${idx}]=yes
    if (( idx > LATEST_IDX )); then LATEST_IDX=${idx}; fi
done <<< "${indices}"
if (( CURRENT_IDX > LATEST_IDX )); then
    log "错误: 本地编号 ${CURRENT_IDX} 超过上游最大编号 ${LATEST_IDX}，请检查年度或目录"
    exit 1
fi
log "本轮同步范围: 当前=${CURRENT_IDX}，上游=${LATEST_IDX}，待处理=$((LATEST_IDX - CURRENT_IDX))"
while (( CURRENT_IDX < LATEST_IDX )); do
    NEXT_IDX=$((CURRENT_IDX + 1))
    if [[ "${available[${NEXT_IDX}]:-}" != yes ]]; then
        log "错误: 上游目录缺少连续编号 ${NEXT_IDX}，停止且不跳号，lastest 保持 ${CURRENT_IDX}"
        exit 1
    fi
    FILENAME="${FILE_PREFIX}${NEXT_IDX}.xml.gz"
    PART="${FILENAME}.part"
    MD5_PART="${FILENAME}.md5.part"
    STATS="${FILE_PREFIX}${NEXT_IDX}_stats.html"
    downloaded=no
    for ((attempt=1; attempt<=MAX_RETRIES; attempt++)); do
        log "开始尝试下载 ${FILENAME} (第 ${attempt}/${MAX_RETRIES} 次)"
        if attempt_download; then
            downloaded=yes
            break
        fi
        if (( attempt < MAX_RETRIES )); then
            log "等待 ${RETRY_DELAY} 秒后重试 ${FILENAME}"
            sleep "${RETRY_DELAY}"
        fi
    done
    if [[ "${downloaded}" != yes ]]; then
        log "错误: 达到最大重试次数，下载 ${FILENAME} 失败，lastest 保持 ${CURRENT_IDX}"
        exit 1
    fi
    # stats 是辅助文件；失败明确告警，但不阻塞已校验 XML 的进度。
    if fetch "${STATS}" "${STATS}.part" no "${IO_TIMEOUT}"; then
        if ! mv -f -- "${STATS}.part" "${STATS}"; then
            log "警告: 无法保存统计 HTML，XML 校验已成功"
        fi
    else
        log "警告: 统计 HTML 未取得，XML 校验已成功"
    fi
    STATE_TMP=$(mktemp "${LAST_FILE}.tmp.XXXXXX")
    printf '%s\n' "${NEXT_IDX}" > "${STATE_TMP}"
    mv -f -- "${STATE_TMP}" "${LAST_FILE}"
    STATE_TMP=""
    CURRENT_IDX=${NEXT_IDX}
    log "更新索引至 ${CURRENT_IDX}"
done
log "本轮已追平: lastest=${CURRENT_IDX}，上游快照=${LATEST_IDX}"
