#!/usr/bin/env bash
# run_upgrade_check.sh — 既有資料庫升得上來嗎（完工判準 upgrade-path）。
#
# ☠️ 為什麼需要這一支：到 2026-10-09 之前，**所有**驗證都是「乾淨安裝」或
#    「同版 -u」。那兩種都跑不到 migration。而本模組的
#    `security/doc_security.xml` 與出貨範本資料檔都是 `<data noupdate="1">`
#    ——那個旗標的意思就是「改 XML 對既有資料庫無效」，所以修正只能靠
#    migration 送達。沒有這支腳本的話，「新安裝拿得到修正、既有資料庫拿不到」
#    這種最糟的半修好狀態不會有任何東西發現。
#
# 做法（不依賴 git 歷史，所以不會被工作樹狀態影響）：
#   1. 乾淨裝一次現行程式碼 → 得到「升級後」的終點狀態
#   2. **把 DB 推回升級前的樣子**：latest_version 退回舊版，
#      並把兩支 migration 各自修過的資料改回舊值
#   3. 跑 -u → migration 應該要執行
#   4. 斷言：兩支 migration 的 log 都出現，而且資料真的被修好
#
# 退出碼：0 通過 / 1 升級路徑壞了 / 2 環境不具備
set -u
# ☠️ 全形標點緊跟在 $VAR 後面時，bash 會把它當成變數名的一部分
#    （實測：`BEFORE_JSON�: unbound variable`）。中文訊息裡一律用 ${VAR}。

cd "$(dirname "$0")/../.."
ODOO_CONTAINER="${ODOO_CONTAINER:-qcodoo}"
PG_CONTAINER="${PG_CONTAINER:-qcpg}"
DB="${UPGRADE_DB:-upgradecheck}"
ADDONS_PATH="${ADDONS_PATH:-/usr/lib/python3/dist-packages/odoo/addons,/mnt/dm,/mnt/ds,/mnt/pt,/mnt/fw}"
PG_ARGS="--db_host=${PG_HOST:-$PG_CONTAINER} --db_user=odoo --db_password=odoo"
COMMON="--without-demo= --workers=0 --max-cron-threads=0 --http-port=8095 --stop-after-init"

# 比兩支 migration 都舊的版本，這樣兩支都會被觸發
OLD_VERSION="18.0.9.0.0"
SHIPPED_TEMPLATES="doc_template_blank template_meeting_record template_self_inspection template_defect_improvement template_payment_estimate template_review_control"

for c in "$ODOO_CONTAINER" "$PG_CONTAINER"; do
    docker ps --format '{{.Names}}' 2>/dev/null | grep -qx "$c" || {
        echo "✗ 環境不具備：容器 $c 沒在跑（退出碼 2，不是通過）"; exit 2; }
done

psql() { docker exec "$PG_CONTAINER" psql -U odoo -d "$DB" -t -A -c "$1"; }

echo "=== 1. 乾淨安裝現行程式碼到 $DB ==="
docker exec "$PG_CONTAINER" psql -U odoo -d postgres \
    -c "DROP DATABASE IF EXISTS $DB;" >/dev/null 2>&1
docker exec "$ODOO_CONTAINER" odoo -d "$DB" $PG_ARGS \
    --addons-path="$ADDONS_PATH" -i dobtor_doc_editor \
    $COMMON --log-level=warn >/tmp/upgrade_install.log 2>&1
STATE=$(psql "select state from ir_module_module where name='dobtor_doc_editor';")
[ "$STATE" = "installed" ] || { echo "✗ 乾淨安裝就失敗了（state=${STATE}），見 /tmp/upgrade_install.log"; exit 1; }
echo "  ✓ installed"

echo "=== 2. 把 DB 推回升級前的狀態 ==="
psql "update ir_module_module set latest_version='$OLD_VERSION' where name='dobtor_doc_editor';" >/dev/null
# 18.0.15.2.0 修的：manager rule 的公司範圍
psql "update ir_rule r set domain_force='[(1, ''='', 1)]'
        from ir_model_data d
       where d.res_id=r.id and d.model='ir.rule'
         and d.module='dobtor_doc_editor'
         and d.name='rule_doc_document_manager_all';" >/dev/null
# 18.0.10.1.0 補的：出貨範本的 content_json
for x in $SHIPPED_TEMPLATES; do
    psql "update doc_template t set content_json=null
            from ir_model_data d
           where d.res_id=t.id and d.model='doc.template'
             and d.module='dobtor_doc_editor' and d.name='$x';" >/dev/null
done
BEFORE_RULE=$(psql "select domain_force from ir_rule r join ir_model_data d on d.res_id=r.id and d.model='ir.rule' where d.name='rule_doc_document_manager_all';")
BEFORE_JSON=$(psql "select count(*) from doc_template t join ir_model_data d on d.res_id=t.id and d.model='doc.template' where d.module='dobtor_doc_editor' and content_json is not null;")
echo "  rule domain  = $BEFORE_RULE"
echo "  有 content_json 的出貨範本 = ${BEFORE_JSON}（推回後應該是 0）"
[ "$BEFORE_JSON" = "0" ] || { echo "✗ 推回失敗：還有 $BEFORE_JSON 張有 content_json，這一輪驗不到 migration"; exit 1; }

echo "=== 3. 升級（migration 應該要執行）==="
docker exec "$ODOO_CONTAINER" odoo -d "$DB" $PG_ARGS \
    --addons-path="$ADDONS_PATH" -u dobtor_doc_editor \
    $COMMON --log-level=info >/tmp/upgrade_run.log 2>&1

echo "=== 4. 斷言 ==="
fail=0
for v in 18.0.10.1.0 18.0.15.2.0; do
    if grep -aq "Running upgrade \[$v>\]" /tmp/upgrade_run.log; then
        echo "  ✓ migration $v 執行了"
    else
        echo "  ✗ migration $v **沒有執行**（既有資料庫拿不到那個修正）"; fail=1
    fi
done
AFTER_RULE=$(psql "select domain_force from ir_rule r join ir_model_data d on d.res_id=r.id and d.model='ir.rule' where d.name='rule_doc_document_manager_all';")
case "$AFTER_RULE" in
    *company_ids*) echo "  ✓ manager rule 已收斂到公司範圍" ;;
    *) echo "  ✗ manager rule 還是 $AFTER_RULE —— 跨公司讀取的洞沒被補上"; fail=1 ;;
esac
AFTER_JSON=$(psql "select count(*) from doc_template t join ir_model_data d on d.res_id=t.id and d.model='doc.template' where d.module='dobtor_doc_editor' and content_json is not null;")
if [ "$AFTER_JSON" -ge 1 ]; then
    echo "  ✓ 出貨範本補回 content_json：$AFTER_JSON 張"
else
    echo "  ✗ 出貨範本的 content_json 沒有補回來"; fail=1
fi
FINAL_STATE=$(psql "select state from ir_module_module where name='dobtor_doc_editor';")
[ "$FINAL_STATE" = "installed" ] && echo "  ✓ 升級後 state=installed" \
    || { echo "  ✗ 升級後 state=$FINAL_STATE"; fail=1; }

echo
if [ "$fail" = "0" ]; then
    echo "✓ upgrade-path 通過：既有資料庫升得上來，而且 migration 真的改到資料。"
    exit 0
fi
echo "✗ upgrade-path 沒過。詳見 /tmp/upgrade_run.log"
exit 1
