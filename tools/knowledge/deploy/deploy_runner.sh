#!/bin/bash
# 只換截圖程式（shot_runner/run.py）：不升級模組、不重啟容器、不必等佇列（拍到一半的那張用舊版，下一張起用新版）。
# 來源一律是 git HEAD（先 commit 再部署），換之前先備份正式機上的舊檔。
# 用法：tools/knowledge/deploy/deploy_runner.sh
set -e
HERE=$(cd "$(dirname "$0")" && pwd); REPO=$(cd "$HERE/../../.." && pwd)
. "$HERE/env.sh"
DST=$DEPLOY_ENV_DIR/sources/Dobtor/ProductivityTools/dobtor_corpaas_knowledge/shot_runner/run.py
TMP=$(mktemp)
(cd "$REPO" && git show HEAD:dobtor_corpaas_knowledge/shot_runner/run.py) > "$TMP"
python3 -c "import ast,sys; ast.parse(open('$TMP').read())"
STAMP=$(date +%Y%m%d-%H%M%S)
ssh -i "$KEY" "$HOST" "cp -p $DST $DST.bak-$STAMP"
scp -q -i "$KEY" "$TMP" "$HOST:$DST.new"
ssh -i "$KEY" "$HOST" "chmod a+r $DST.new && mv $DST.new $DST && md5sum $DST"
echo "截圖程式已換成 $(cd "$REPO" && git rev-parse --short HEAD) 的版本（舊檔備份 run.py.bak-$STAMP）"
rm -f "$TMP"
