"""方案知識營運工具共用的 JSON-RPC 連線（admin.corpaas.com）。

★ 密碼不寫在檔案裡：從 macOS 鑰匙圈讀（服務名 corpaas-knowledge-rpc），或環境變數 CORPAAS_RPC_PASSWORD。
  第一次使用請自己存入鑰匙圈（會提示輸入密碼，不會出現在指令列記錄）：
      security add-generic-password -s corpaas-knowledge-rpc -a admin -w
☠️ 2026-10-09：原本放在 /tmp 的 ro.py／rw.py 被 macOS 定期清理刪掉，而且密碼以明文存檔。
"""
import json
import os
import subprocess
import urllib.request

URL = os.environ.get('CORPAAS_RPC_URL', 'https://admin.corpaas.com/jsonrpc')
DB = os.environ.get('CORPAAS_RPC_DB', 'CorPAAS_admin')
LOGIN = os.environ.get('CORPAAS_RPC_LOGIN', 'admin')
KEYCHAIN_SERVICE = 'corpaas-knowledge-rpc'
READ_METHODS = {'search_read', 'search_count', 'read_group', 'fields_get', 'read', 'search'}


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
    return res['result']


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


def rw(model, method, *args, **kw):
    """會寫入正式機的呼叫：只在明確要改資料時用。"""
    return _call('object', 'execute_kw', DB, _uid(), _SESSION['pw'], model, method, list(args), kw)
