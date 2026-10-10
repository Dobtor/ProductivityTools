# 部署腳本共用設定：讀 ~/.config/corpaas-kb/settings.env（環境變數同名者優先），缺值就停。
# 格式：KEY=值（一行一個；可加引號；$HOME 會展開；不執行任何指令）。rpc.py 用同樣的規則讀。
SETTINGS=${CORPAAS_KB_SETTINGS:-$HOME/.config/corpaas-kb/settings.env}
if [ -f "$SETTINGS" ]; then
  while IFS='=' read -r k v || [ -n "$k" ]; do
    k=${k#export }; k=${k//[[:space:]]/}
    [[ $k =~ ^[A-Z_][A-Z0-9_]*$ ]] || continue
    v=${v#"${v%%[![:space:]]*}"}; v=${v%"${v##*[![:space:]]}"}
    v=${v%\"}; v=${v#\"}; v=${v%\'}; v=${v#\'}
    v=${v//\$HOME/$HOME}
    if [ -z "${!k}" ]; then export "$k=$v"; fi
  done < "$SETTINGS"
fi
for k in DEPLOY_KEY DEPLOY_HOST DEPLOY_ENV_DIR DEPLOY_CONTAINER DEPLOY_DB; do
  [ -n "${!k}" ] || { echo "缺少設定 $k：請照 tools/knowledge/settings.example.env 建立 $SETTINGS" >&2; exit 1; }
  [[ ${!k} =~ ^[A-Za-z0-9_./@:~-]+$ ]] || { echo "設定 $k 含不允許的字元：${!k}" >&2; exit 1; }
done
KEY=$DEPLOY_KEY; HOST=$DEPLOY_HOST
