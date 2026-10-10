"""方案知識營運工具共用的 JSON-RPC 連線（主控台網址見 settings.env）。

★ 密碼不寫在檔案裡：從 macOS 鑰匙圈讀（服務名 corpaas-knowledge-rpc），或環境變數 CORPAAS_RPC_PASSWORD。
  第一次使用請自己存入鑰匙圈（會提示輸入密碼，不會出現在指令列記錄）：
      security add-generic-password -s corpaas-knowledge-rpc -a admin -w
☠️ 2026-10-09：原本放在 /tmp 的 ro.py／rw.py 被 macOS 定期清理刪掉，而且密碼以明文存檔。
"""
import json
import os
import subprocess
import urllib.request

SETTINGS = os.environ.get('CORPAAS_KB_SETTINGS',
                          os.path.expanduser('~/.config/corpaas-kb/settings.env'))


def _setting(key):
    """正式機設定：環境變數優先，其次 ~/.config/corpaas-kb/settings.env（不進 repo）。"""
    if os.environ.get(key):
        return os.environ[key]
    try:
        for line in open(SETTINGS, encoding='utf-8'):
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            k, _sep, v = line.partition('=')
            if k.replace('export ', '').strip() == key:
                v = v.strip().strip('"').strip("'").replace('$HOME', os.path.expanduser('~'))
                if v:
                    return v
                break   # 空值＝缺值
    except OSError:
        pass
    raise SystemExit('缺少設定 %s：請照 tools/knowledge/settings.example.env 建立 %s' % (key, SETTINGS))


URL = _setting('CORPAAS_RPC_URL')
DB = _setting('CORPAAS_RPC_DB')
LOGIN = _setting('CORPAAS_RPC_LOGIN')
KEYCHAIN_SERVICE = 'corpaas-knowledge-rpc'
READ_METHODS = {'search_read', 'search_count', 'read_group', 'fields_get', 'read', 'search'}
#: rw() 允許的寫入方法（營運工具實際用到的）；其他方法要明確 unsafe=True
WRITE_METHODS = {'action_approve', 'action_knowledge_ai_select', 'action_knowledge_refresh',
                 'knowledge_enqueue_refresh'}


class RpcError(Exception):
    """伺服器回的錯誤：message 是完整的錯誤訊息（不含 traceback）。"""


def _password():
    pw = os.environ.get('CORPAAS_RPC_PASSWORD')
    if pw:
        return pw
    hint = ('請在「終端機」App 執行 `security add-generic-password -s %s -a %s -w` 存入鑰匙圈'
            '（在 Claude Code 用 ! 執行收不到鍵盤輸入，會存成空白），或設定 CORPAAS_RPC_PASSWORD'
            % (KEYCHAIN_SERVICE, LOGIN))
    try:
        pw = subprocess.run(['security', 'find-generic-password', '-s', KEYCHAIN_SERVICE,
                             '-a', LOGIN, '-w'], capture_output=True, text=True,
                            check=True).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        raise SystemExit('找不到密碼：' + hint)
    if not pw:
        raise SystemExit('鑰匙圈裡的密碼是空的：先 `security delete-generic-password -s %s -a %s`，再%s'
                         % (KEYCHAIN_SERVICE, LOGIN, hint[1:]))
    return pw


def _call(service, method, *args):
    body = {'jsonrpc': '2.0', 'method': 'call',
            'params': {'service': service, 'method': method, 'args': list(args)}}
    req = urllib.request.Request(URL, json.dumps(body).encode(),
                                 {'Content-Type': 'application/json', 'User-Agent': 'Mozilla/5.0'})
    res = json.load(urllib.request.urlopen(req, timeout=300))
    if 'error' in res:
        data = res['error'].get('data') or {}
        raise RpcError('%s: %s' % (data.get('name'), data.get('message') or res['error']))
    # ★ Odoo 18 的 JSON-RPC：方法回 None 時回應裡**沒有** result 鍵（不是 result: null）
    return res.get('result')


_SESSION = {}


def _uid():
    if 'uid' not in _SESSION:
        _SESSION['pw'] = _password()
        _SESSION['uid'] = _call('common', 'authenticate', DB, LOGIN, _SESSION['pw'], {})
        if not _SESSION['uid']:
            raise SystemExit('登入失敗：帳號或密碼不對')
    return _SESSION['uid']


def ro(model, method, *args, **kw):
    """唯讀呼叫（只允許讀取方法）。"""
    if method not in READ_METHODS:
        raise ValueError('ro() 只允許讀取方法：%s' % method)
    return _call('object', 'execute_kw', DB, _uid(), _SESSION['pw'], model, method, list(args), kw)


def rw(model, method, *args, unsafe=False, **kw):
    """會寫入正式機的呼叫：只允許 WRITE_METHODS；其他方法（write、unlink…）要明確 unsafe=True。"""
    if method not in WRITE_METHODS and not unsafe:
        raise ValueError('rw() 不允許 %s.%s（要改資料請明確傳 unsafe=True）' % (model, method))
    return _call('object', 'execute_kw', DB, _uid(), _SESSION['pw'], model, method, list(args), kw)
