#!/usr/bin/env bash
# run_tour_tests.sh — 跑瀏覽器 tour（前端驗證）
#
# 為什麼要獨立一支：缺 chromium 或 websocket-client 時，Odoo 會把 tour
# 「跳過」而不是失敗——整份測試仍然全綠，但前端一步都沒跑。所以這支先自檢
# 環境、再把「真的跑完」與「被跳過」在摘要裡分開講。
#
# 執行方式（容器內；chromium 需要 root，見下）：
#   docker exec -u 0 <容器> bash /mnt/pt/dobtor_doc_editor/tests/scripts/run_tour_tests.sh
#
# 環境需求（Apple Silicon 上每一項都踩過）：
#   - websocket-client：pip install --break-system-packages websocket-client
#   - 可用的 chromium：arm64 沒有 Linux Chrome，而 Ubuntu 24.04 的
#     `apt install chromium` 只給一個 snap stub（跑起來會說 requires the
#     chromium snap）。可行解是 Playwright 的 chromium：
#       pip install playwright
#       PLAYWRIGHT_BROWSERS_PATH=/opt/pw python3 -m playwright install --with-deps chromium
#       ln -sf /opt/pw/chromium-*/chrome-linux-arm64/chrome /usr/bin/chromium
#   - 以 root 跑：用容器的 odoo 使用者跑時 chromium 會 SIGTRAP。
#   - HTTP_PORT 要避開容器裡已經在跑的 server。

set -uo pipefail

MODULE=dobtor_doc_editor
TAGS="${TAGS:-/$MODULE:TestDocEditorPanelsTour,/$MODULE:TestBrowserAvailable}"
ODOO_DB="${ODOO_DB:-odoo18_dev}"
HTTP_PORT="${HTTP_PORT:-8071}"
LOG="${LOG:-/tmp/${MODULE}_tour.log}"
# 預設讀 odoo.conf；外部 rig 可用 ODOO_ARGS 自帶 --db_host / --addons-path
ODOO_ARGS="${ODOO_ARGS:--c ${ODOO_CONF:-/etc/odoo/odoo.conf}}"

die() { echo "✗ $*" >&2; exit 1; }

echo "─── $MODULE 瀏覽器 tour ───"
echo "  DB:         $ODOO_DB"
echo "  HTTP port:  $HTTP_PORT"
echo "  Tags:       $TAGS"
echo "───────────────────────────"

# ── 環境自檢：這兩項缺任何一個，tour 都只會被跳過，看起來還是綠的
BROWSER=""
for name in google-chrome chromium chromium-browser chrome chrome-browser; do
  if command -v "$name" >/dev/null 2>&1; then BROWSER="$name"; break; fi
done
[ -n "$BROWSER" ] || die "找不到瀏覽器（google-chrome / chromium / ...）——tour 會被跳過"
python3 -c 'import websocket' 2>/dev/null \
  || die "沒有 websocket-client（pip install --break-system-packages websocket-client）"
[ "$(id -u)" = "0" ] || echo "⚠ 不是以 root 跑：chromium 可能 SIGTRAP（見檔頭說明）"
echo "✓ 瀏覽器 = $BROWSER、websocket-client 都在"
echo

# shellcheck disable=SC2086
odoo $ODOO_ARGS -d "$ODOO_DB" \
  -u "$MODULE" --test-enable --test-tags "$TAGS" \
  --without-demo= --workers=0 --max-cron-threads=0 \
  --http-port="$HTTP_PORT" --stop-after-init \
  --log-level=test 2>&1 | tee "$LOG"

echo
echo "─── 結果 ───"
grep -aE "odoo\.tests\.result:.*tests when loading database" "$LOG" | tail -1
grep -aoE '\[[0-9]+/[0-9]+\] Tour [a-z_]+' "$LOG" | tail -1

# 比對要錨在「真的 log 行」上：Odoo 的 traceback 裡也印得出
# success_signal="tour succeeded" 這串字，不錨的話失敗的執行也會被判成成功
# （實測過，而且它騙過了我自己）
OK=$(grep -acE '^[0-9]{4}-[0-9]{2}-[0-9]{2}.*tour succeeded' "$LOG")
SKIPPED=$(grep -ac 'skipped\|未執行（前端未驗證）' "$LOG")
FAILED=$(grep -acE 'odoo\.tests\.result:.*[1-9][0-9]* (failed|error)' "$LOG")

echo
if [ "$FAILED" -gt 0 ]; then
  grep -aoE '(FAIL|ERROR): [A-Za-z0-9_.]+' "$LOG" | sort | uniq -c | sort -rn
  echo "✗ 測試失敗——詳見 $LOG"
  exit 1
elif [ "$OK" -gt 0 ]; then
  echo "✓ tour 真的跑完了（tour succeeded × $OK）"
  exit 0
elif [ "$SKIPPED" -gt 0 ]; then
  # 這條是整支腳本存在的理由：skip 不能當成通過。
  echo "✗ tour 被跳過——前端未驗證，不要當成通過"
  grep -a 'skipped' "$LOG" | tail -5
  exit 2
else
  echo "✗ log 裡既沒有 'tour succeeded' 也沒有 skip 訊息——tour 應該是沒跑到"
  exit 1
fi
