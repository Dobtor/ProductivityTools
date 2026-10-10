#!/usr/bin/env bash
# run_ships_without_tests_check.sh — 沒有 tests/ 也裝得起來嗎
#                                    （完工判準 ships-without-tests）。
#
# ☠️ 為什麼需要這一支：部署方式是 **docker + github pull + PaaS**
#    （見 docs/DEPLOYMENT_FOOTPRINT.md）。`git pull` 會帶下**每一個追蹤
#    檔案**，包含 81 MB 的 tests/fixtures。要在正式機排掉 tests/ 就得先有
#    一件事成立：**出貨程式不依賴 tests/**。那件事「看起來成立」不夠——
#    只要有人哪天從 models/ import 了 tests/ 裡的東西（本模組的
#    tests/session_probe.py 已經是跨模組公開介面，那條線是真的存在的），
#    正式機就會在排掉 tests/ 之後開不起來，而**本機永遠不會重現**。
#
# 做法：
#   1. 用 `git archive HEAD` 把兩個模組的**追蹤檔案**攤到探針目錄
#      （不是 rsync 工作樹——那會把 node_modules 等未追蹤的東西一起帶進去，
#       量到的就不是 `git pull` 會給的東西）
#   2. 刪掉兩個模組的 tests/ 目錄
#   3. 確認 static/tests/ **還在**（見下面的陷阱）
#   4. 用只指向探針目錄的 addons-path 裝進一個乾淨 DB
#   5. 斷言兩個模組都是 installed
#
# ☠️ 陷阱：排除樣式寫成 `tests/` 會把 `static/tests/` 一起排掉。
#    `static/tests/tours/*.js` 在 manifest 的 web.assets_tests bundle 裡，
#    被排掉的話 tour 資產就斷了。所以第 3 步是**必要的**守衛，不是裝飾。
#
# 退出碼：0 通過 / 1 排掉 tests/ 之後裝不起來 / 2 環境不具備
set -u
# ☠️ 全形標點緊跟 $VAR 會被當成變數名的一部分——中文訊息裡一律用 ${VAR}。

cd "$(dirname "$0")/../.."
CORE_DIR="$PWD"
REPO_ROOT="$(cd .. && pwd)"
PROBE_DIR="$REPO_ROOT/_deploy_probe"

ODOO_CONTAINER="${ODOO_CONTAINER:-qcodoo}"
PG_CONTAINER="${PG_CONTAINER:-qcpg}"
DB="${SHIPS_DB:-shipsnotests}"
# ☠️ addons-path **不可以**含 /mnt/pt（repo 根）——那樣 Odoo 會從原路徑
#    找到帶 tests/ 的那一份，探針就白做了。只給探針目錄。
PROBE_MOUNT="${PROBE_MOUNT:-/mnt/pt/_deploy_probe}"
ADDONS_PATH="${SHIPS_ADDONS_PATH:-/usr/lib/python3/dist-packages/odoo/addons,$PROBE_MOUNT}"
PG_ARGS="--db_host=${PG_HOST:-$PG_CONTAINER} --db_user=odoo --db_password=odoo"
COMMON="--without-demo= --workers=0 --max-cron-threads=0 --http-port=8094 --stop-after-init"

cleanup() { rm -rf "$PROBE_DIR"; }
trap cleanup EXIT

for c in "$ODOO_CONTAINER" "$PG_CONTAINER"; do
    docker ps --format '{{.Names}}' 2>/dev/null | grep -qx "$c" || {
        echo "✗ 環境不具備：容器 ${c} 沒在跑（退出碼 2，不是通過）"; exit 2; }
done
command -v git >/dev/null || { echo "✗ 環境不具備：沒有 git"; exit 2; }

echo "=== 1. 用 git archive HEAD 攤出追蹤檔案 ==="
rm -rf "$PROBE_DIR"
mkdir -p "$PROBE_DIR"
# 量的是 HEAD（= `git pull` 會送到正式機的東西），不是工作樹。
# make done 的 git-clean 判準保證這兩者在判決當下是同一份。
git -C "$REPO_ROOT" archive HEAD dobtor_doc_editor dobtor_doc_import \
    | tar -x -C "$PROBE_DIR" || {
        echo "✗ git archive 失敗"; exit 1; }
FULL_KB=$(du -sk "$PROBE_DIR" | awk '{print $1}')
echo "  追蹤檔案總計 ${FULL_KB} KB"

echo "=== 2. 刪掉兩個模組的 tests/ ==="
for m in dobtor_doc_editor dobtor_doc_import; do
    [ -d "$PROBE_DIR/$m/tests" ] || { echo "✗ 探針裡找不到 ${m}/tests——git archive 的範圍不對"; exit 1; }
    rm -rf "$PROBE_DIR/$m/tests"
done
SLIM_KB=$(du -sk "$PROBE_DIR" | awk '{print $1}')
echo "  排掉 tests/ 之後 ${SLIM_KB} KB（省 $((FULL_KB - SLIM_KB)) KB）"

echo "=== 3. static/tests/ 必須還在（陷阱守衛）==="
# `--exclude='tests/'` 這種沒錨定的樣式會連 static/tests/ 一起排掉，
# 而 static/tests/tours/*.js 在 manifest 的 web.assets_tests bundle 裡。
TOURS=$(ls "$PROBE_DIR/dobtor_doc_editor/static/tests/tours/"*.js 2>/dev/null | wc -l | tr -d ' ')
if [ "$TOURS" = "0" ]; then
    echo "✗ static/tests/tours/*.js 不見了——排除樣式沒錨定，連 static/tests 也排掉了"
    exit 1
fi
echo "  ✓ static/tests/tours/*.js 還有 ${TOURS} 支"

echo "=== 4. 裝進乾淨 DB（addons-path 只指向探針）==="
docker exec "$PG_CONTAINER" psql -U odoo -d postgres \
    -c "DROP DATABASE IF EXISTS $DB;" >/dev/null 2>&1
docker exec "$ODOO_CONTAINER" test -d "$PROBE_MOUNT" || {
    echo "✗ 環境不具備：容器裡看不到 ${PROBE_MOUNT}"
    echo "  （探針目錄必須落在掛進容器的路徑下，用 PROBE_MOUNT 指定）"
    exit 2; }
docker exec "$ODOO_CONTAINER" odoo -d "$DB" $PG_ARGS \
    --addons-path="$ADDONS_PATH" -i dobtor_doc_editor,dobtor_doc_import \
    $COMMON --log-level=warn >/tmp/ships_without_tests.log 2>&1

echo "=== 5. 斷言兩個模組都 installed ==="
RC=0
for m in dobtor_doc_editor dobtor_doc_import; do
    STATE=$(docker exec "$PG_CONTAINER" psql -U odoo -d "$DB" -t -A -c \
        "select state from ir_module_module where name='$m';" 2>/dev/null | tr -d '[:space:]')
    if [ "$STATE" = "installed" ]; then
        echo "  ✓ ${m} = installed"
    else
        echo "  ✗ ${m} = '${STATE}'（應為 installed）"
        RC=1
    fi
done

if [ "$RC" != "0" ]; then
    echo "✗ 排掉 tests/ 之後裝不起來。見 /tmp/ships_without_tests.log"
    grep -aiE 'error|traceback|ImportError|ModuleNotFound' /tmp/ships_without_tests.log \
        | head -10 | sed 's/^/        /'
    exit 1
fi

echo
echo "✓ 沒有 tests/ 也裝得起來：${FULL_KB} KB → ${SLIM_KB} KB"
exit 0
