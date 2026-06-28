#!/usr/bin/env bash
# run_backend_tests.sh — 跑 Odoo HttpCase / TransactionCase backend tests
#
# Sprint 72：把分散的 Odoo test 跑命令統一為一個腳本、方便 user 與未來 CI 觸發。
#
# 涵蓋 tag：
#   - font_serve（Sprint 64b/66/68/69 — /dobtor/fonts/* endpoint）
#   - zip_guard（Sprint 20 W9-10 + Sprint 71 補測 — DOCX zip bomb 防護）
#
# 執行方式：
#   docker exec odoo18 bash /mnt/extra-addons/dobtor_doc_editor/tests/scripts/run_backend_tests.sh
#   docker exec odoo18 bash /mnt/extra-addons/dobtor_doc_editor/tests/scripts/run_backend_tests.sh --tag=font_serve
#
# 環境需求：
#   - Odoo container `odoo18` 已運行（或 ODOO_CONTAINER env 覆寫）
#   - DB `odoo18_dev` 已 install dobtor_doc_editor
#   - port 8169 可用（避開既有 server 的 8069）

set -euo pipefail

# 預設跑所有 backend test tag、可用 --tag=<name> 縮 scope
TAG="${1:-font_serve,zip_guard}"
TAG="${TAG#--tag=}"

ODOO_DB="${ODOO_DB:-odoo18_dev}"
ODOO_CONF="${ODOO_CONF:-/etc/odoo/odoo.conf}"
HTTP_PORT="${HTTP_PORT:-8169}"

echo "─── dobtor_doc_editor backend tests ───"
echo "  Tag(s):       ${TAG}"
echo "  DB:           ${ODOO_DB}"
echo "  HTTP port:    ${HTTP_PORT}（避開 production 8069）"
echo "─────────────────────────────────────────"

# 跑 odoo --test-tags、stop-after-init、不啟動 cron worker
odoo -c "${ODOO_CONF}" -d "${ODOO_DB}" \
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
    echo "::warning::0 tests matched tag '${TAG}' — 確認 @tagged() 包含此 tag"
    exit 2
  fi
  echo "✓ All ${TEST_COUNT} tests passed"
  exit 0
else
  echo "::error::tests failed — 詳見 /tmp/dobtor_backend_tests.log"
  exit 1
fi
