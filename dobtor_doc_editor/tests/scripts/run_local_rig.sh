#!/usr/bin/env bash
# run_local_rig.sh — host 端入口：在本機兩容器 rig（Odoo + Postgres，另一個
# 容器跑瀏覽器 tour）上跑 dobtor_doc_editor 的全部測試。
#
# 與同目錄另兩支的分工：
#   run_backend_tests.sh  在**容器內**跑、只跑指定 tag（CI 用）
#   run_tour_tests.sh     在**容器內**跑、只跑瀏覽器 tour，會自檢瀏覽器
#   run_local_rig.sh      這一支，在**host** 上跑，docker exec 進去，跑全部
#
# 用法：
#   bash tests/scripts/run_local_rig.sh prepare   # 看環境、選用套件現況
#   bash tests/scripts/run_local_rig.sh install   # 乾淨安裝 + 跑測試
#   bash tests/scripts/run_local_rig.sh test      # 只重跑測試（模組已裝）
#   bash tests/scripts/run_local_rig.sh tour      # 只跑瀏覽器 tour
#   bash tests/scripts/run_local_rig.sh all       # test 然後 tour
#   bash tests/scripts/run_local_rig.sh reset     # 砍掉測試庫重來
#
# 容器名與連線參數全部可用環境變數覆寫（預設是這台機器上既有的 rig）：
#   ODOO_CONTAINER=qcodoo  WEB_CONTAINER=qcweb  PG_CONTAINER=qcpg
#   ODOO_DB=docedit  TOUR_DB=uitest
#   PG_HOST=<PG_CONTAINER>  PG_USER=odoo  PG_PASSWORD=odoo
#   ADDONS_PATH=…  HTTP_PORT=8099  TOUR_PORT=8071
# 例（另一組容器）：
#   ODOO_CONTAINER=odoo18 PG_CONTAINER=pg15 ODOO_DB=mytest \
#     bash tests/scripts/run_local_rig.sh test
#
# 旗標依 memory/odoo18_local_test_rig_docker.md 的血淚記錄：
#   --without-demo=   必須是空值（odoo.conf 的 without_demo=True 會造成大量假失敗）
#   --workers=0 --max-cron-threads=0 --stop-after-init
#   不要用 --no-http（同樣會造成假失敗）
#
# 為什麼 tour 要另一個容器：後端那個容器裡沒有可用的瀏覽器，Odoo 會把 tour
# 「跳過」而不是失敗——整份測試仍然全綠，但前端一步都沒跑。tour 的環境需求
#（arm64 沒有 Linux Chrome、Ubuntu 24.04 的 chromium 是 snap stub、要以 root
# 跑否則 chromium SIGTRAP）記在 memory/odoo18_tour_rig_apple_silicon.md。
set -u

MODULE=dobtor_doc_editor

ODOO_CONTAINER="${ODOO_CONTAINER:-qcodoo}"
WEB_CONTAINER="${WEB_CONTAINER:-qcweb}"
PG_CONTAINER="${PG_CONTAINER:-qcpg}"

ODOO_DB="${ODOO_DB:-docedit}"
TOUR_DB="${TOUR_DB:-uitest}"

# 容器之間用容器名連線，所以 PG_HOST 預設就是 pg 容器名。
PG_HOST="${PG_HOST:-$PG_CONTAINER}"
PG_USER="${PG_USER:-odoo}"
PG_PASSWORD="${PG_PASSWORD:-odoo}"

ADDONS_PATH="${ADDONS_PATH:-/usr/lib/python3/dist-packages/odoo/addons,/mnt/dm,/mnt/ds,/mnt/pt,/mnt/fw}"
# 模組在容器裡的掛載點（check_env 要確認它真的看得到）。
MODULE_MOUNT="${MODULE_MOUNT:-/mnt/pt/$MODULE}"

HTTP_PORT="${HTTP_PORT:-8099}"
# tour 容器裡本來就有一個 HTTP 伺服器佔著 8069，測試要另給一個埠。
TOUR_PORT="${TOUR_PORT:-8071}"

PG_ARGS="--db_host=$PG_HOST --db_user=$PG_USER --db_password=$PG_PASSWORD"
COMMON="--without-demo= --workers=0 --max-cron-threads=0 --http-port=$HTTP_PORT --stop-after-init"
TOUR_TAGS="/$MODULE:TestDocEditorPanelsTour,/$MODULE:TestBrowserAvailable"

die() { echo "✗ $*" >&2; exit 1; }

require_container() {
  docker ps --format '{{.Names}}' | grep -qx "$1" || die "容器 $1 不在執行中"
}

check_env() {
  docker info >/dev/null 2>&1 || die "Docker daemon 沒在跑（請先啟動 Docker）"
  require_container "$ODOO_CONTAINER"
  require_container "$PG_CONTAINER"
  # 模組必須真的在容器裡看得到（memory：不要靠 cp/mount 沒報錯就當它在）
  docker exec "$ODOO_CONTAINER" test -f "$MODULE_MOUNT/__manifest__.py" \
    || die "$MODULE_MOUNT 在 $ODOO_CONTAINER 內看不到（檢查 volume 掛載）"
  echo "✓ Docker / $ODOO_CONTAINER / $PG_CONTAINER / 模組掛載 都就緒"
}

check_web_env() {
  docker info >/dev/null 2>&1 || die "Docker daemon 沒在跑（請先啟動 Docker）"
  require_container "$WEB_CONTAINER"
  require_container "$PG_CONTAINER"
  docker exec "$WEB_CONTAINER" test -f "$MODULE_MOUNT/__manifest__.py" \
    || die "$MODULE_MOUNT 在 $WEB_CONTAINER 內看不到（檢查 volume 掛載）"
  # 以下兩項缺任何一個，tour 都只會被「跳過」，看起來還是綠的。
  docker exec "$WEB_CONTAINER" sh -c 'command -v chromium >/dev/null' \
    || die "$WEB_CONTAINER 裡沒有 chromium（見 memory/odoo18_tour_rig_apple_silicon.md）"
  docker exec "$WEB_CONTAINER" python3 -c 'import websocket' 2>/dev/null \
    || die "$WEB_CONTAINER 裡沒有 websocket-client（pip install --break-system-packages websocket-client）"
  echo "✓ $WEB_CONTAINER / $PG_CONTAINER / 模組掛載 / chromium / websocket-client 都就緒"
}

run_backend() {
  local mode="$1" log="/tmp/${MODULE}_${1}.log"
  # shellcheck disable=SC2086
  docker exec "$ODOO_CONTAINER" odoo -d "$ODOO_DB" $PG_ARGS \
    --addons-path="$ADDONS_PATH" \
    "$mode" "$MODULE" --test-enable --test-tags "/$MODULE" \
    $COMMON --log-level=test 2>&1 | tee "$log"
  echo
  echo "=== 結果摘要 ==="
  grep -aoE '(FAIL|ERROR): [A-Za-z0-9_.]+' "$log" | sort | uniq -c | sort -rn
  local result
  result=$(grep -aE 'tests\.result:.*of [0-9]+ tests' "$log" | tail -1)
  echo "${result:-（log 裡找不到 tests.result 那一行——測試可能根本沒跑）}"
  echo "$result" | grep -qE ': 0 failed, 0 error\(s\) of [1-9][0-9]* tests' || return 1
}

run_tour() {
  local log="/tmp/${MODULE}_tour.log"
  # -u 0：以容器的 odoo 使用者跑時 chromium 會 SIGTRAP。
  # shellcheck disable=SC2086
  docker exec -u 0 "$WEB_CONTAINER" odoo -d "$TOUR_DB" $PG_ARGS \
    --addons-path="$ADDONS_PATH" \
    -u "$MODULE" --test-enable --test-tags "$TOUR_TAGS" \
    --without-demo= --workers=0 --max-cron-threads=0 \
    --http-port="$TOUR_PORT" --stop-after-init \
    --log-level=test 2>&1 | tee "$log"
  echo
  echo "=== 結果摘要 ==="
  # 這段的重點是「skipped 不能被當成過」。Odoo 跳過 tour 時不會留下任何
  # 失敗紀錄，只看 failed/error 的話會誤判成前端驗過了。
  # 錨在真的 log 行上：Odoo 的 traceback 也會印出 success_signal="tour
  # succeeded" 這串字，不錨的話失敗的執行會被判成成功（實測騙過我自己一次）
  local ok skipped failed
  ok=$(grep -acE '^[0-9]{4}-[0-9]{2}-[0-9]{2}.*tour succeeded' "$log")
  skipped=$(grep -ac 'skip\|未執行（前端未驗證）' "$log")
  failed=$(grep -acE 'tests\.result:.*[1-9][0-9]* (failed|error)' "$log")
  grep -aoE '(FAIL|ERROR): [A-Za-z0-9_.]+' "$log" | sort | uniq -c | sort -rn
  grep -aE '[0-9]+ failed, [0-9]+ error' "$log" | tail -3
  grep -aoE '\[[0-9]+/[0-9]+\] Tour [a-z_]+' "$log" | tail -1
  echo
  if [ "$failed" -gt 0 ]; then
    echo "✗ 測試失敗——詳見 $log"
    grep -a 'FAILED: \[' "$log" | tail -2
    return 1
  elif [ "$ok" -gt 0 ]; then
    echo "✓ tour 真的跑完了（tour succeeded × ${ok}）"
  elif [ "$skipped" -gt 0 ]; then
    echo "✗ tour 被跳過——前端未驗證（不要當成通過）。看 $log 的 skip 訊息"
    grep -a 'skip' "$log" | tail -5
    return 1
  else
    echo "✗ log 裡既沒有 'tour succeeded' 也沒有 skip 訊息——tour 應該是失敗了"
    return 1
  fi
}

case "${1:-test}" in

prepare)
  check_env
  echo "--- 容器內 Python 與選用套件現況 ---"
  docker exec "$ODOO_CONTAINER" python3 -c "
from importlib.util import find_spec
for pkg, pip in (('docx','python-docx'), ('docxtpl','docxtpl'), ('odf','odfpy')):
    print(('  有 ' if find_spec(pkg) else '  缺 ') + pkg + '  (pip ' + pip + ')')
"
  echo "--- soffice（DOCX 高品質匯出用）---"
  docker exec "$ODOO_CONTAINER" sh -c 'which soffice || echo "  缺 soffice"'
  echo "--- 原生報表整合測試需要的模組（沒裝的話那幾則會 skip）---"
  docker exec "$PG_CONTAINER" psql -U "$PG_USER" -d "$ODOO_DB" -t -c \
    "select name || ' = ' || state from ir_module_module
      where name in ('sale','account','stock','purchase') order by name;" \
    2>/dev/null || echo "  （$ODOO_DB 還沒建立）"
  echo
  echo "要安裝選用套件請執行："
  echo "  docker exec -u 0 $ODOO_CONTAINER pip install --break-system-packages python-docx docxtpl odfpy"
  echo "要讓原生報表整合測試真的跑（tests/test_qweb_converter_native.py）："
  echo "  docker exec $ODOO_CONTAINER odoo -d $ODOO_DB $PG_ARGS --addons-path=$ADDONS_PATH \\"
  echo "    -i sale,account,stock,purchase $COMMON"
  ;;

install)
  check_env
  echo "=== 乾淨安裝 $MODULE 到 $ODOO_DB 並跑測試 ==="
  run_backend -i
  ;;

test)
  check_env
  echo "=== 重跑 $MODULE 測試（-u ${ODOO_DB}）==="
  run_backend -u
  ;;

tour)
  check_web_env
  echo "=== 在 ${WEB_CONTAINER}（${TOUR_DB}）跑瀏覽器 tour ==="
  run_tour
  ;;

all)
  check_env
  check_web_env
  echo "=== 後端（${ODOO_DB}）==="
  run_backend -u || die "後端測試失敗，不往下跑 tour"
  echo
  echo "=== 瀏覽器 tour（${WEB_CONTAINER} / ${TOUR_DB}）==="
  run_tour
  ;;

reset)
  check_env
  echo "=== 砍掉 $ODOO_DB ==="
  # memory：psql 不給 -d 會連不存在的 odoo 庫，錯誤還會被 /dev/null 吃掉
  docker exec "$PG_CONTAINER" psql -U "$PG_USER" -d postgres \
    -c "DROP DATABASE IF EXISTS $ODOO_DB;"
  docker exec "$PG_CONTAINER" psql -U "$PG_USER" -d postgres -lqt \
    | cut -d'|' -f1 | grep -qw "$ODOO_DB" \
    && die "$ODOO_DB 仍存在" || echo "✓ $ODOO_DB 已移除"
  ;;

*)
  echo "用法：bash $0 {prepare|install|test|tour|all|reset}"
  exit 1
  ;;
esac
