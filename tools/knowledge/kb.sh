#!/bin/bash
# 本機跑方案知識測試。用法：
#   tools/knowledge/kb.sh            → 三個知識模組 -u ＋全部測試（資料庫 kb）
#   tools/knowledge/kb.sh -i         → 第一次：-i 安裝
#   DB=xxx MODS=a,b TAGS=/a,/b tools/knowledge/kb.sh
set -e
KB_HOME=${KB_HOME:-$HOME/Library/Caches/corpaas-kb}
ODOO=${ODOO_SRC:-$HOME/Desktop/Claude/odoo-18.0}
GH=${GH_ROOT:-$HOME/Documents/GitHub}
DB=${DB:-kb}
MODS=${MODS:-dobtor_corpaas_knowledge,dobtor_corpaas_knowledge_manual,dobtor_corpaas_knowledge_proposal}
TAGS=${TAGS:-/dobtor_corpaas_knowledge,/dobtor_corpaas_knowledge_manual,/dobtor_corpaas_knowledge_proposal}
MODE=${1:--u}
[ -x "$KB_HOME/venv/bin/python" ] || { echo "先跑 tools/knowledge/setup_local.sh"; exit 1; }
# pgserver 程序可能已停：get_server 會沿用或重新啟動
"$KB_HOME/venv/bin/python" -c "import pgserver; s=pgserver.get_server('$KB_HOME/pgdata', cleanup_mode=None); open('$KB_HOME/pg_host','w').write(s.get_uri().split('host=')[1])"
export PATH=$KB_HOME/bin:$PATH
ADDONS=$ODOO/addons,$ODOO/odoo/addons,$KB_HOME/venv/lib/python3.12/site-packages/odoo/addons
for r in PAAS Google-API ProductivityTools AI Sales Uniform-Invoice eCommerce website-user; do ADDONS=$ADDONS,$GH/$r; done
cd "$ODOO"
exec "$KB_HOME/venv/bin/python" odoo-bin -d "$DB" --data-dir="$KB_HOME/data" \
  --db_host="$(cat "$KB_HOME/pg_host")" --db_user=odoo --db_password=odoo --addons-path="$ADDONS" \
  "$MODE" "$MODS" --test-enable --test-tags "$TAGS" --without-demo=all --workers=0 \
  --max-cron-threads=0 --http-port=8091 --stop-after-init --log-level=test
