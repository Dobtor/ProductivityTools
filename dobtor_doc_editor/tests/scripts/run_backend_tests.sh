#!/usr/bin/env bash
# run_backend_tests.sh — 跑 Odoo HttpCase / TransactionCase backend tests
#
# Sprint 72：把分散的 Odoo test 跑命令統一為一個腳本、方便 user 與未來 CI 觸發。
#
# 涵蓋 tag：
#   - zip_guard（Sprint 20 W9-10 + Sprint 71 補測 — DOCX zip bomb 防護）
#
# 執行方式（建議走 Makefile，它會把連線參數帶進來）：
#   make test-backend              # 預設 tag
#   make test-backend TAG=security # 指定 tag
#
# 直接 docker exec 的話要自己帶 ODOO_ARGS——這個 rig 的 Postgres 在**另一個
# 容器**，不帶就會去找容器內的 unix socket 然後 psycopg2.OperationalError：
#   docker exec -e ODOO_DB=docedit \
#     -e ODOO_ARGS="--db_host=qcpg --db_user=odoo --db_password=odoo \
#                   --addons-path=/usr/lib/python3/dist-packages/odoo/addons,/mnt/pt" \
#     qcodoo bash /mnt/pt/dobtor_doc_editor/tests/scripts/run_backend_tests.sh
#
# ⚠️ 打了不存在的 tag，Odoo 會回「0 failed, 0 error of **0 tests**」——看起來
#    是綠的。腳本結尾有擋這件事。

set -euo pipefail

# 預設跑所有 backend test tag、可用 --tag=<name> 縮 scope
TAG="${1:-zip_guard}"
TAG="${TAG#--tag=}"

ODOO_DB="${ODOO_DB:-docedit}"
ODOO_CONF="${ODOO_CONF:-/etc/odoo/odoo.conf}"
HTTP_PORT="${HTTP_PORT:-8169}"
# 預設讀 odoo.conf。資料庫不在本機 socket（例如 pg 在另一個容器）時，
# 用 ODOO_ARGS 自帶 --db_host / --addons-path，不要去改 odoo.conf。
ODOO_ARGS="${ODOO_ARGS:--c ${ODOO_CONF}}"

echo "─── dobtor_doc_editor backend tests ───"
echo "  Tag(s):       ${TAG}"
echo "  Odoo args:    ${ODOO_ARGS}"
echo "  DB:           ${ODOO_DB}"
echo "  HTTP port:    ${HTTP_PORT}（避開 production 8069）"
echo "─────────────────────────────────────────"

# 跑 odoo --test-tags、stop-after-init、不啟動 cron worker
# shellcheck disable=SC2086
odoo ${ODOO_ARGS} -d "${ODOO_DB}" \
  --test-enable \
  --test-tags="${TAG}" \
  --stop-after-init \
  -u dobtor_doc_editor \
  --http-port="${HTTP_PORT}" \
  --max-cron-threads=0 \
  2>&1 | tee /tmp/dobtor_backend_tests.log

# 從 log 抓最終結果
RESULT_LINE=$(grep -aE "odoo\.tests\.result:.*tests when loading database" /tmp/dobtor_backend_tests.log | tail -1)
echo
echo "─── 結果 ───"
echo "${RESULT_LINE}"

# 判定 pass / fail
if echo "${RESULT_LINE}" | grep -qE "^.*: 0 failed, 0 error\(s\) of [0-9]+ tests"; then
  TEST_COUNT=$(echo "${RESULT_LINE}" | grep -oE "of [0-9]+ tests" | grep -oE "[0-9]+")
  if [ "${TEST_COUNT:-0}" = "0" ]; then
    echo "⚠ 0 tests matched tag '${TAG}' — 確認 @tagged() 包含此 tag"
    exit 2
  fi
  echo "✓ All ${TEST_COUNT} tests passed"
  exit 0
else
  echo "✗ tests failed — 詳見 /tmp/dobtor_backend_tests.log"
  exit 1
fi
