#!/bin/bash
# pt-verify deploy-plan 的遠端部署腳本範本（由 deploy.sh 上傳到 $BK 後在正式機主機執行）。
# 整併自 ProductivityTools/tools/knowledge/deploy/deploy_template.sh 與 2026-11-02 的控制台部署腳本：
#   漂移比對 → 暫停排程 → 等佇列 → 備份 → 換碼 → -u（鎖類錯誤重試）→ 失敗還原 → 重啟 → 恢復排程。
# 一般化：「正式機原碼子目錄 → 模組清單」多組；任何一組的模組清單可為空（全新模組不比漂移、不備份）。
# ☠️ 不要手改下面的設定區塊：由 pt-verify deploy-plan 產生。
set -e
# @@CONFIG@@
BK=${BK:?BK 未設定（由 deploy.sh 帶入）}
WAIT_MIN=${WAIT_MIN:-60}
N=${#GROUP_DIRS[@]}
[ "$N" -gt 0 ] || { echo "ABORT: 沒有任何部署分組"; exit 2; }
[ -n "$UPG$INS" ] || { echo "ABORT: 沒有要升級／安裝的模組"; exit 2; }

# 1. 漂移檢查：正式機現在的檔案要和部署前快照一模一樣（LC_ALL=C 排序後比）
DRIFT=0
for i in $(seq 0 $((N-1))); do
  g=${GROUP_DIRS[$i]}; ex=${GROUP_EXIST[$i]}
  [ -d "$S/$g" ] || { echo "ABORT: $S/$g 不存在"; exit 2; }
  if [ -z "$ex" ]; then echo "drift: $g 只有新模組，略過比對"; continue; fi
  # ★ 模組清單非空才 find（空清單時 find 會掃整個目錄、xargs 會讀 stdin）
  (cd "$S/$g" && find $ex -type f -not -path '*/__pycache__/*' -not -name '*.pyc' -print0 \
     | LC_ALL=C sort -z | xargs -0 -r md5sum) > "$BK/now_$i.md5"
  LC_ALL=C sort "$BK/now_$i.md5" -o "$BK/now_$i.md5"
  LC_ALL=C sort "$BK/expect_$i.md5" -o "$BK/expect_$i.md5"
  if ! diff -q "$BK/expect_$i.md5" "$BK/now_$i.md5" >/dev/null; then
    echo "ABORT: $g 正式機程式和部署前快照不一致（有人改過）："; diff "$BK/expect_$i.md5" "$BK/now_$i.md5" | head; DRIFT=1
  fi
done
[ "$DRIFT" = 0 ] || exit 2
echo "drift check OK"

pg() {
  docker exec -e Q="$1" -e PTV_DB="$DB" -e PTV_CONF="$ODOO_CONF" "$C" python3 -c "
import configparser,os,psycopg2
c=configparser.ConfigParser();c.read(os.environ['PTV_CONF']);o=c['options']
h=o.get('db_host');h=None if h in (None,'','False') else h
cn=psycopg2.connect(host=h,port=o.get('db_port') or 5432,user=o.get('db_user'),password=o.get('db_password'),dbname=os.environ['PTV_DB'])
cn.autocommit=True;cur=cn.cursor();cur.execute(os.environ['Q'])
print(','.join(str(r[0]) for r in cur.fetchall()) if cur.description else '')"
}

# 2. 暫停排程（只動原本啟用的；結束一定恢復）
PAUSED=
if [ -n "$PAUSE_XIDS" ]; then
  PAUSED=$(pg "update ir_cron c set active=false from ir_model_data d where d.model='ir.cron' and d.res_id=c.id and d.module||'.'||d.name in ($PAUSE_XIDS) and c.active returning c.id")
fi
echo "paused crons: ${PAUSED:-（無）}"
resume() { if [ -n "$PAUSED" ]; then pg "update ir_cron set active=true where id in ($PAUSED) returning id" >/dev/null && echo "resumed crons: $PAUSED"; PAUSED=; fi; }
trap resume EXIT

# 3. 等佇列閒置（目標有設定 QUEUE_BUSY_SQL 才等）
if [ -n "$QUEUE_BUSY_SQL" ]; then
  i=0
  while :; do
    n=$(pg "$QUEUE_BUSY_SQL")
    [ "$n" = "0" ] && { echo "queue idle"; break; }
    if [ $i -ge $((WAIT_MIN*2)) ]; then
      [ "${FORCE:-0}" = "1" ] && { echo "still busy — FORCE=1"; break; }
      echo "ABORT: queue still busy after ${WAIT_MIN} min"; exit 3
    fi
    [ $((i % 10)) -eq 0 ] && echo "waiting: $n queue job(s) running…"
    i=$((i+1)); sleep 30
  done
fi
if [ -n "$KILL_PATTERN" ]; then
  KILLED=$(docker exec "$C" sh -c "pkill -f '$KILL_PATTERN' && echo yes || true")
  [ -n "$KILLED" ] && { echo "stopped running job subprocess(es)"; sleep 5; }
fi
# 3b. 停掉的作業留下的資料庫連線（交易開著、閒置）會握著鎖，升級的 ALTER TABLE 等到逾時。
#   ☠️ 實機（2026-11-04 admin.corpaas.com 兩次）：6 次升級都 lock timeout，自動還原。
#   等最多 2 分鐘讓它們自己結束；還在就結束掉（網頁請求不會開著交易閒置 60 秒以上）。
STALE="from pg_stat_activity where datname=current_database() and pid<>pg_backend_pid() and state like 'idle in transaction%' and now()-state_change > interval '60 seconds'"
n=$(pg "select count(*) $STALE")
for i in $(seq 1 12); do
  [ "$n" = "0" ] && break
  sleep 10; n=$(pg "select count(*) $STALE")
done
if [ "$n" != "0" ]; then
  pg "select pg_terminate_backend(pid) $STALE" >/dev/null
  echo "terminated $n stale idle-in-transaction session(s)"
fi

# 4. 備份＋換程式
for i in $(seq 0 $((N-1))); do
  g=${GROUP_DIRS[$i]}; ex=${GROUP_EXIST[$i]}
  [ -n "$ex" ] && (cd "$S/$g" && tar czf "$BK/before_$i.tgz" $ex)
  mkdir -p "$BK/new_$i" && tar -xzf "$BK/bundle_$i.tgz" -C "$BK/new_$i"
done
restore() {
  echo "restoring previous code"
  for i in $(seq 0 $((N-1))); do
    g=${GROUP_DIRS[$i]}; ex=${GROUP_EXIST[$i]}
    for m in ${GROUP_MODS[$i]}; do rm -rf "$S/$g/$m"; done
    [ -n "$ex" ] && tar -xzf "$BK/before_$i.tgz" -C "$S/$g"
  done
}
for i in $(seq 0 $((N-1))); do
  g=${GROUP_DIRS[$i]}
  for m in ${GROUP_MODS[$i]}; do
    rm -rf "$S/$g/$m"; cp -a "$BK/new_$i/$m" "$S/$g/"; chmod -R a+rX "$S/$g/$m"
    printf '%s: ' "$m"; grep -h "'version'" "$S/$g/$m/__manifest__.py" | head -1
  done
done

# 5. 升級（鎖類錯誤重試；每次新的 log 檔）
set +e
OK=
ARGS=()
[ -n "$UPG" ] && ARGS+=(-u "$UPG")
[ -n "$INS" ] && ARGS+=(-i "$INS")
for i in 1 2 3 4 5 6; do
  L=upgrade-$LABEL-$i-$(date +%Y%m%d%H%M%S).log
  docker exec "$C" odoo -c "$ODOO_CONF" -d "$DB" "${ARGS[@]}" --stop-after-init --no-http --workers=0 \
    --max-cron-threads=0 --logfile="$CONTAINER_LOG_DIR/$L" >/dev/null 2>&1
  RC=$?; H=$BK/$L
  docker exec "$C" cat "$CONTAINER_LOG_DIR/$L" > "$H" 2>/dev/null
  if [ $RC -ne 0 ] || [ ! -s "$H" ] || grep -q "Failed to load registry\|ParseError" "$H"; then
    echo "try $i failed (exit $RC): $(grep -o 'ParseError: while parsing [^,]*\|[A-Za-z]*Error: .*' "$H" 2>/dev/null | head -3 | tr '\n' ' ')"
    grep -q "could not obtain lock\|deadlock detected\|lock timeout\|LockNotAvailable\|could not serialize\|此計劃任務目前正在執行" "$H" 2>/dev/null || break
    sleep 20
  else
    echo "try $i OK"; grep -E "Running migration" "$H" | head -8; grep -E " ERROR |CRITICAL" "$H" | head -8
    OK=1; break
  fi
done
if [ -z "$OK" ]; then restore; docker restart "$C" >/dev/null; echo "UPGRADE FAILED — 舊程式已還原、容器已重啟；log: $H"; exit 1; fi
docker restart "$C" >/dev/null; sleep "${RESTART_WAIT:-25}"
docker ps --filter "name=$C" --format "{{.Status}}"
echo "DEPLOY DONE; backup in $BK"
