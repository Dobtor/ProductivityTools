#!/bin/bash
# 打包三個知識模組（git HEAD）並產生部署腳本；比對正式機與上一包是否一致（有人改過就停）。
# 用法：tools/knowledge/deploy/build_bundle.sh <標籤，例如 n68> [上一包標籤]
set -e
TAG=$1; PREV=$2
HERE=$(cd "$(dirname "$0")" && pwd); REPO=$(cd "$HERE/../../.." && pwd)
OUT=${BUNDLE_ROOT:-$HOME/Library/Caches/corpaas-kb/bundles}/$TAG
# ★ 預設只打包核心＋說明書：建議書模組由它自己的工作階段部署（相依不同，曾讓整包升級失敗）
#   要一起打包：KB_MODS="dobtor_corpaas_knowledge dobtor_corpaas_knowledge_manual dobtor_corpaas_knowledge_proposal"
# 部署集（#19）：KB_SET=core｜proposal｜marketing｜exchange｜all；KB_MODS 直接指定優先
#   ★ 建議書一定連 doc_editor、會議記錄一起上（相依不同曾讓整包升級失敗）
case "${KB_SET:-core}" in
  core)      SET_MODS="dobtor_corpaas_knowledge dobtor_corpaas_knowledge_manual" ;;
  proposal)  SET_MODS="dobtor_corpaas_knowledge dobtor_corpaas_knowledge_manual dobtor_doc_editor dobtor_meeting_minutes dobtor_corpaas_knowledge_proposal" ;;
  marketing) SET_MODS="dobtor_corpaas_knowledge dobtor_corpaas_knowledge_manual dobtor_corpaas_knowledge_marketing" ;;
  exchange)  SET_MODS="dobtor_corpaas_knowledge dobtor_corpaas_knowledge_manual dobtor_corpaas_knowledge_exchange" ;;
  all)       SET_MODS="dobtor_corpaas_knowledge dobtor_corpaas_knowledge_manual dobtor_doc_editor dobtor_meeting_minutes dobtor_corpaas_knowledge_proposal dobtor_corpaas_knowledge_marketing dobtor_corpaas_knowledge_exchange" ;;
  *) echo "未知的 KB_SET：$KB_SET（core｜proposal｜marketing｜exchange｜all）"; exit 2 ;;
esac
MODS=${KB_MODS:-$SET_MODS}
. "$HERE/env.sh"
SRC=$DEPLOY_ENV_DIR/sources/Dobtor/ProductivityTools
rm -rf "$OUT"; mkdir -p "$OUT/new"
(cd "$REPO" && git archive HEAD $MODS | tar -x -C "$OUT/new")
(cd "$OUT/new" && tar czf ../pt.tgz $MODS)
sed -e "s#__BACKUP__#/root/deploy-backup-$(date +%Y%m%d)-$TAG#" -e "s#__TAG__#$TAG#" \
    -e "s#__ENV_DIR__#$DEPLOY_ENV_DIR#" -e "s#__CONTAINER__#$DEPLOY_CONTAINER#" -e "s#__DB__#$DEPLOY_DB#g" \
    -e "s#__MODS__#$MODS#g" -e "s#__MODS_CSV__#$(echo $MODS | tr ' ' ',')#g" \
    "$HERE/deploy_template.sh" > "$OUT/deploy.sh"
if [ -n "$PREV" ]; then
  P=$(dirname "$OUT")/$PREV/new
  # 只比上一包也有的模組（這包新加的模組正式機本來就沒有）
  CMP=$(cd "$P" && for m in $MODS; do [ -d "$m" ] && printf '%s ' "$m"; done)
  (cd "$P" && find $CMP -type f | LC_ALL=C sort | xargs md5 -r) | awk '{print $1" "$2}' > "$OUT/prev.md5"
  ssh -n -i "$KEY" "$HOST" "cd $SRC && find $CMP -type f ! -name '*.pyc' | LC_ALL=C sort | xargs md5sum" \
    | awk '{print $1" "$2}' > "$OUT/server.md5"
  # 截圖程式可能已用 deploy_runner.sh 單獨換過：不算「有人改過」
  grep -v 'shot_runner/run.py' "$OUT/prev.md5" > "$OUT/prev.cmp"; grep -v 'shot_runner/run.py' "$OUT/server.md5" > "$OUT/server.cmp"
  cmp -s "$OUT/prev.cmp" "$OUT/server.cmp" && echo "正式機與 $PREV 一致（截圖程式不比）" || { echo "☠️ 正式機和 $PREV 不一致（有人改過），先查清楚再部署"; diff "$OUT/prev.cmp" "$OUT/server.cmp" | head; exit 2; }
fi
echo "部署指令："
echo "B=/root/deploy-backup-$(date +%Y%m%d)-$TAG; D=$OUT; ssh -i $KEY $HOST \"mkdir -p \$B\" && scp -i $KEY \$D/pt.tgz $HOST:\$B/ && ssh -i $KEY $HOST 'bash -s' < \$D/deploy.sh"
