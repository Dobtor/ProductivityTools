#!/bin/bash
# 建本機測試環境（不開 Docker）：Python 3.12 虛擬環境＋內嵌 PostgreSQL（pgserver）。
# ★ 放在 ~/Library/Caches/corpaas-kb，不放 /tmp（macOS 會定期清掉 /tmp 三天沒動的檔案）。
set -e
KB_HOME=${KB_HOME:-$HOME/Library/Caches/corpaas-kb}
ODOO=${ODOO_SRC:-$HOME/Desktop/Claude/odoo-18.0}
mkdir -p "$KB_HOME"
cd "$KB_HOME"
[ -x venv/bin/python ] || uv venv --python 3.12 venv -q
# requirements 去版本號；psycopg2 改 binary，python-ldap／gevent／greenlet 本機用不到
sed -E 's/[<>=;].*//; s/ *$//' "$ODOO/requirements.txt" | grep -v '^#' | grep -v '^$' \
  | grep -vixE 'pypiwin32|psycopg2|python-ldap|gevent|greenlet' | sort -u > req.txt
uv pip install --python venv/bin/python -q -r req.txt psycopg2-binary pgserver websocket-client \
  "Werkzeug==3.0.1" "lxml==5.2.1" paramiko fabric invoke gitpython pygithub pyjwt pyyaml \
  simplejson responses pathspec
uv pip install --python venv/bin/python -q --no-deps "odoo-addon-github-connector>=18.0,<18.1" \
  "odoo-addon-github-connector-odoo>=18.0,<18.1"
venv/bin/python - <<PY
import pgserver
s = pgserver.get_server('$KB_HOME/pgdata', cleanup_mode=None)
try:
    s.psql("CREATE ROLE odoo LOGIN SUPERUSER PASSWORD 'odoo'")
except Exception:
    pass
host = s.get_uri().split('host=')[1]
open('$KB_HOME/pg_host', 'w').write(host)
print('pg socket:', host)
PY
mkdir -p "$KB_HOME/bin" && printf '#!/bin/sh\necho "{}"\n' > "$KB_HOME/bin/cloc" && chmod +x "$KB_HOME/bin/cloc"
echo "完成：$KB_HOME"
