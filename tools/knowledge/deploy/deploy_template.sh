set -e
B=/opt/odoo/env00000036/Prod_admin; S=$B/sources/Dobtor; BK=__BACKUP__
C=odoo-corpaas-prod_admin
# ★ 先等佇列（所有通道：知識、上架、開通…）沒有「處理中」的工作再動手——部署重啟會中斷它們。
#   最多等 WAIT_MIN 分鐘（預設 60）；還在忙就放棄部署，除非 FORCE=1。
WAIT_MIN=${WAIT_MIN:-60}
busy() {
  docker exec $C python3 -c "
import configparser,psycopg2
c=configparser.ConfigParser();c.read('/etc/odoo/odoo.conf');o=c['options']
cn=psycopg2.connect(host=o.get('db_host'),port=o.get('db_port') or 5432,user=o.get('db_user'),password=o.get('db_password'),dbname='CorPAAS_admin')
cur=cn.cursor();cur.execute(\"select count(*), string_agg(channel || ':' || operate, ',') from corpaas_queue where state='processing'\")
n,ops=cur.fetchone();print(n, ops or '')"
}
i=0
while :; do
  read n ops <<< "$(busy)"
  [ "$n" = "0" ] && { echo "queue idle"; break; }
  if [ $i -ge $((WAIT_MIN*2)) ]; then
    if [ "${FORCE:-0}" = "1" ]; then echo "still busy ($ops) — FORCE=1, deploying anyway"; break; fi
    echo "ABORT: queue still busy after ${WAIT_MIN} min ($ops). Re-run later, or FORCE=1."; exit 3
  fi
  [ $((i % 10)) -eq 0 ] && echo "waiting: $n queue job(s) running ($ops)…"
  i=$((i+1)); sleep 30
done
mkdir -p $BK/pt
cd $S/ProductivityTools && tar czf $BK/before-pt.tgz dobtor_corpaas_knowledge dobtor_corpaas_knowledge_manual dobtor_corpaas_knowledge_proposal
tar -xzf $BK/pt.tgz -C $BK/pt
for m in dobtor_corpaas_knowledge dobtor_corpaas_knowledge_manual dobtor_corpaas_knowledge_proposal; do rm -rf $S/ProductivityTools/$m; cp -a $BK/pt/$m $S/ProductivityTools/; chmod -R a+rX $S/ProductivityTools/$m; done
grep -h "'version'" $S/ProductivityTools/dobtor_corpaas_knowledge/__manifest__.py $S/ProductivityTools/dobtor_corpaas_knowledge_manual/__manifest__.py
set +e
OK=
for i in 1 2 3 4 5 6; do
  L=upgrade-__TAG__-$i.log
  docker exec $C odoo -c /etc/odoo/odoo.conf -d CorPAAS_admin -u dobtor_corpaas_knowledge,dobtor_corpaas_knowledge_manual,dobtor_corpaas_knowledge_proposal --stop-after-init --no-http --workers=0 --max-cron-threads=0 --logfile=/var/lib/odoo/$L >/dev/null 2>&1
  H=$B/data_dir/$L
  if grep -q "Failed to load registry\|ParseError" $H; then
    echo "try $i failed: $(grep -o '此計劃任務目前正在執行\|ParseError: while parsing [^,]*\|Error: .*' $H | head -3 | tr '\n' ' ')"
    grep -q "此計劃任務目前正在執行\|could not obtain lock" $H || break
    sleep 20
  else
    echo "try $i OK"; grep -E " ERROR |CRITICAL" $H | head -8; docker restart $C >/dev/null; sleep 25
    docker ps --filter name=$C --format "{{.Status}}"; OK=1; break
  fi
done
if [ -z "$OK" ]; then
  # 升級沒成功：把舊程式碼放回去，免得下次容器重啟載入跟資料庫不相容的新程式
  echo "upgrade failed: restoring previous code from $BK/before-pt.tgz"
  for m in dobtor_corpaas_knowledge dobtor_corpaas_knowledge_manual dobtor_corpaas_knowledge_proposal; do rm -rf $S/ProductivityTools/$m; done
  tar -xzf $BK/before-pt.tgz -C $S/ProductivityTools
  exit 1
fi
