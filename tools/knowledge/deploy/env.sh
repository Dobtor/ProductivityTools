# 部署腳本共用設定：讀 ~/.config/corpaas-kb/settings.env（環境變數同名者優先），缺值就停。
SETTINGS=${CORPAAS_KB_SETTINGS:-$HOME/.config/corpaas-kb/settings.env}
if [ -f "$SETTINGS" ]; then
  while IFS='=' read -r k v; do
    case "$k" in ''|\#*) continue ;; esac
    if [ -z "${!k}" ]; then eval "export $k=\"$v\""; fi
  done < "$SETTINGS"
fi
for k in DEPLOY_KEY DEPLOY_HOST DEPLOY_ENV_DIR DEPLOY_CONTAINER DEPLOY_DB; do
  [ -n "${!k}" ] || { echo "缺少設定 $k：請照 tools/knowledge/settings.example.env 建立 $SETTINGS" >&2; exit 1; }
done
KEY=$DEPLOY_KEY; HOST=$DEPLOY_HOST
