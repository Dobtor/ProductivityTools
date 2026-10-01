# -*- coding: utf-8 -*-
"""向 CorPaaS 主控台查「這個畫面／這個問題」的說明連結。

契約（主控台端見 dobtor_corpaas_knowledge/controllers/help_api.py）：
  POST {console}/corpaas/knowledge/v1/help        params: database, query?, action_xmlid?,
                                                          model?, view_type?, limit?, groups?
       → {ok, package, results: [{feature_key, title, url, kind, scenario, anchor,
                                  fingerprint: {model, views, menu_path, view_mode,
                                               elements, lang, version,
                                               scope_hashes, scope_hash}}]}
  POST {console}/corpaas/knowledge/v1/divergence  params: database, feature_key,
                                                          expected, actual

★ 由本站伺服器轉查，不讓瀏覽器直接打主控台：出網路徑集中一處（客戶防火牆只放行
  伺服器），而且 D5 的指紋要用伺服器上的 get_views 算。
★ 查不到就回空清單，絕不讓說明拖垮助理面板——它只是附帶的東西。

簽章（IMPLEMENTATION_SPEC「修正第二輪」1）：兩支 POST 都帶
  X-KB-Database: <庫名>、X-KB-Timestamp: <unix 秒>、
  X-KB-Signature: hex(hmac_sha256(key, b"<ts>." + 原始 request body bytes))
  金鑰由主控台以 shell 寫進 ICP `dobtor_ai_help.console_key`。
"""
import hashlib
import hmac
import json
import logging
import re
import threading
import time
import urllib.parse

import requests

from odoo import api, models

from ..lib import fingerprint_lib
from .res_config_settings import DEFAULT_CONSOLE_URL, DEFAULT_PUBLIC_DOMAINS

_logger = logging.getLogger(__name__)

TIMEOUT = 8
DIVERGENCE_TIMEOUT = 5
MAX_QUERY = 500
MAX_RESULTS = 10
#: groups 參數最多送幾個 xmlid（主控台只拿來做交集，太多沒有意義也拖慢請求）。
MAX_GROUPS = 200

_XMLID = re.compile(r'^[A-Za-z0-9_]+\.[A-Za-z0-9_.\-]+$')
_MODEL = re.compile(r'^[a-z0-9_]+(\.[a-z0-9_]+)+$')
_VIEW_TYPES = ('list', 'form', 'kanban', 'calendar', 'pivot', 'graph', 'activity',
               'map', 'gantt', 'hierarchy', 'search')
#: 主控台算指紋時用的 view 型別（feature.views_for_fingerprint 只收這三種）。
_FP_VIEW_TYPES = ('list', 'form', 'kanban')

#: D5 回報去重：(database, feature_key, actual) → 上次回報時間。
#: ★ 同一個畫面每個人每次打開都會算出同一個「不一致」，全部回報的話主控台的
#:   事件表會被同一件事洗版，而它的限流也會把真正新的回報擋掉。
_REPORTED = {}
_REPORTED_LOCK = threading.Lock()
REPORT_EVERY = 6 * 3600


def _sign(key, ts, body):
    """hex(hmac_sha256(key, b"<ts>." + body))。body 必須是實際送出的 bytes。"""
    return hmac.new(key.encode('utf-8'), ('%s.' % ts).encode('ascii') + body,
                    hashlib.sha256).hexdigest()


def _post_json(url, params, timeout, database=None, key=None):
    """JSON-RPC POST；回 result dict，失敗拋例外。

    ☠️ `trust_env = False`：requests 預設會吃 .netrc、REQUESTS_CA_BUNDLE 等環境
       設定，容器裡帶了什麼都會悄悄影響這條連線。只保留 proxy（客戶常靠它出網），
       而且照 no_proxy 判斷。
    ☠️ 自己 json.dumps 成 bytes、用 `data=` 送：用 `json=` 的話是 requests 自己序列化，
       簽的 bytes 與送出的 bytes 不保證一致（空白、ensure_ascii），主控台驗不過。
    ☠️ 金鑰絕不進 log／例外訊息：這裡只把它拿去算 HMAC。
    """
    body = json.dumps({'jsonrpc': '2.0', 'method': 'call', 'params': params, 'id': 1},
                      separators=(',', ':')).encode('utf-8')
    headers = {'User-Agent': 'Dobtor-AI-Help/1.0', 'Content-Type': 'application/json'}
    if database:
        headers['X-KB-Database'] = database
    if key:
        ts = str(int(time.time()))
        headers['X-KB-Timestamp'] = ts
        headers['X-KB-Signature'] = _sign(key, ts, body)
    # ★ 沒金鑰照樣送（不簽）：主控台若要求簽章會回 error='unsigned'，
    #   設定頁會提示「尚未收到主控台下發的金鑰」。
    with requests.Session() as session:
        session.trust_env = False
        resp = session.post(
            url, data=body, timeout=timeout,
            proxies=requests.utils.get_environ_proxies(url), headers=headers)
        resp.raise_for_status()
        result = resp.json()
    if result.get('error'):
        err = result['error'] or {}
        raise ValueError(((err.get('data') or {}).get('message')
                          or err.get('message') or 'error')[:300])
    return result.get('result') or {}


def _host(value):
    value = (value or '').strip().lower()
    if not value:
        return ''
    if '//' not in value:
        value = '//' + value
    return (urllib.parse.urlsplit(value).hostname or '').lower()


class AiHelpLinks(models.AbstractModel):
    _name = 'ai.help.links'
    _description = '此畫面說明'

    @api.model
    def _help_config(self):
        get = self.env['ir.config_parameter'].sudo().get_param
        console = (get('dobtor_ai_help.console_url') or DEFAULT_CONSOLE_URL).strip().rstrip('/')
        domains = get('dobtor_ai_help.public_domains') or DEFAULT_PUBLIC_DOMAINS
        hosts = {_host(console)}
        hosts.update(_host(d) for d in re.split(r'[,\s]+', domains))
        hosts.discard('')
        return {
            'console_url': console,
            'database': (get('dobtor_ai_help.database') or '').strip() or self.env.cr.dbname,
            'hosts': sorted(hosts),
            # ☠️ 金鑰只給 _post_json 算簽章；不要把整個 cfg 印進 log。
            'key': (get('dobtor_ai_help.console_key') or '').strip(),
        }

    @api.model
    def _user_groups(self):
        """目前使用者的群組 xmlid（排序、去掉沒有 xmlid 的），最多 MAX_GROUPS 個。

        ★ 主控台用它過濾功能點（group_xmlids 無交集不回）並排序說明文章。
          xmlid 而非 id：各庫 id 不同。get_external_id 內部已 sudo 讀 ir.model.data。
        """
        xmlids = self.env.user.groups_id.get_external_id()
        return sorted(x for x in xmlids.values() if x)[:MAX_GROUPS]

    # ------------------------------------------------------------------
    @api.model
    def _action_xmlid(self, action):
        """面板送來的 action（數字 id 或 xmlid）→ xmlid。認不出就回空字串。

        ★ 主控台只認 xmlid：數字 id 每一庫都不同，黃金庫的 42 不是這裡的 42。
        """
        if not action or isinstance(action, bool):
            return ''
        if isinstance(action, str) and not action.isdigit():
            return action if _XMLID.match(action) else ''
        try:
            action_id = int(action)
        except (TypeError, ValueError):
            return ''
        # sudo：xmlid 不是機密，而使用者讀不到的動作本來就不會出現在他的畫面上。
        rec = self.env['ir.actions.actions'].sudo().browse(action_id).exists()
        if not rec:
            return ''
        # ☠️ 要用具體模型（ir.actions.act_window…）查：xmlid 是登記在具體模型上的，
        #    拿 ir.actions.actions 去查永遠查不到。
        data = self.env['ir.model.data'].sudo().search(
            [('model', '=', rec.type), ('res_id', '=', rec.id)], limit=1)
        return '%s.%s' % (data.module, data.name) if data else ''

    @api.model
    def _safe_url(self, url, hosts):
        """只放行 https 且網域在白名單上的連結。

        ★ 連結是主控台給的，不是 AI 寫的；但這裡仍然要擋：面板會把它做成可點的
          連結，任何一條 `javascript:` 或外站網址都會變成釣魚入口。
        """
        if not isinstance(url, str):
            return ''
        try:
            parts = urllib.parse.urlsplit(url.strip())
        except ValueError:
            return ''
        if parts.scheme != 'https' or parts.username or parts.password:
            return ''
        if (parts.hostname or '').lower() not in hosts:
            return ''
        return urllib.parse.urlunsplit(parts)

    # ------------------------------------------------------------------
    # D5：租戶端的腳本範圍指紋
    # ------------------------------------------------------------------
    @api.model
    def _fp_views(self, fp):
        """[(view_id|False, view_type)]；照主控台 `views_for_fingerprint` 的規則。"""
        views = fp.get('views')
        if not views:
            modes = [m for m in (fp.get('view_mode') or 'list,form').split(',')
                     if m in _FP_VIEW_TYPES]
            views = [[False, m] for m in modes] or [[False, 'form']]
        out = []
        for pair in views:
            if not isinstance(pair, (list, tuple)) or len(pair) != 2:
                return []
            vx, vt = pair
            if vt not in _VIEW_TYPES:
                return []
            vid = False
            if vx:
                # ★ 本庫沒有這個視圖就退回預設視圖：算出來的雜湊自然不同，
                #   而那正是「你的畫面與說明不同」。
                view = self.env.ref(vx, raise_if_not_found=False) \
                    if isinstance(vx, str) and _XMLID.match(vx) else None
                vid = view.id if view is not None and view._name == 'ir.ui.view' else False
            out.append((vid, vt))
        return out

    @api.model
    def _tenant_scope_hash(self, fp, model):
        """以目前使用者算腳本範圍指紋；算不了回 None（不當成不一致）。"""
        model = fp.get('model') or model
        if not isinstance(model, str) or model not in self.env:
            return None
        views = self._fp_views(fp)
        if not views:
            return None
        # ★ 語言要與主控台拍攝時一致（`string` 屬性在指紋裡）；context 只留 lang：
        #   `*_view_ref` 之類的鍵會換掉視圖，讓比對失去意義。
        lang = fp.get('lang') or 'zh_TW'
        # ☠️ Odoo 18 的 env.lang 遇到沒啟用的語言會直接 UserError。而且就算不炸，
        #    本庫沒裝那個語言時 `string` 全是原文，每一條都會「不一致」——那是語言
        #    不同，不是畫面不同，回報上去只會把主控台的事件表洗掉。所以不比。
        if not isinstance(lang, str) or not self.env['res.lang']._get_code(lang):
            return None
        try:
            data = self.env[model].with_context({'lang': lang}).get_views(views)
        except Exception as exc:  # noqa: BLE001 - 讀不到畫面就不比
            _logger.info('此畫面說明：%s 無法取得視圖（%s）', model, exc)
            return None
        archs = {vt: v['arch'] for vt, v in (data.get('views') or {}).items()}
        sh, _found = fingerprint_lib.scope_hash(
            archs, fp.get('elements') or [], fp.get('menu_path') or '',
            fp.get('view_mode') or '')
        return sh

    @api.model
    def _diverged(self, item, model):
        """回 (diverged, actual, expected)。沒有指紋或算不了一律 (False, None, None)。

        ★ 主控台依角色各算一份（`scope_hashes`）：租戶使用者的群組不一定剛好等於
          某個情境角色，落在任何一份就不算分歧——只比一份會讓群組較多的人一律被誤報。
        """
        fp = item.get('fingerprint')
        if not isinstance(fp, dict) or not fp.get('elements'):
            return False, None, None
        hashes = [h for h in (fp.get('scope_hashes') or []) if isinstance(h, str) and h]
        if not hashes and isinstance(fp.get('scope_hash'), str) and fp['scope_hash']:
            hashes = [fp['scope_hash']]
        if not hashes:
            return False, None, None
        version = fp.get('version')
        if version and version != fingerprint_lib.FINGERPRINT_VERSION:
            return False, None, None
        actual = self._tenant_scope_hash(fp, model)
        if actual is None:
            return False, None, None
        return actual not in hashes, actual, hashes[0]

    @api.model
    def _report_divergence(self, feature_key, expected, actual):
        """非同步回報主控台；不等、不管成敗。"""
        cfg = self._help_config()
        key = (cfg['database'], feature_key, actual)
        now = time.time()
        with _REPORTED_LOCK:
            if now - _REPORTED.get(key, 0) < REPORT_EVERY:
                return False
            _REPORTED[key] = now
            if len(_REPORTED) > 2000:
                _REPORTED.clear()
        url = cfg['console_url'] + '/corpaas/knowledge/v1/divergence'
        params = {'database': cfg['database'], 'feature_key': feature_key,
                  'expected': expected, 'actual': actual}

        # ★ 執行緒裡不碰 self.env：請求結束 cursor 就關了。
        database, secret = cfg['database'], cfg['key']

        def _send():
            try:
                _post_json(url, params, DIVERGENCE_TIMEOUT, database=database, key=secret)
            except Exception as exc:  # noqa: BLE001
                _logger.info('此畫面說明：回報畫面差異失敗（%s）', exc)

        threading.Thread(target=_send, name='ai-help-divergence', daemon=True).start()
        return True

    # ------------------------------------------------------------------
    @api.model
    def fetch_links(self, query=None, action=None, model=None, view_type=None, limit=5):
        """回 {ok, results, hosts[, package, error]}。永遠不拋例外。"""
        cfg = self._help_config()
        out = {'ok': True, 'results': [], 'hosts': cfg['hosts']}
        try:
            limit = max(1, min(int(limit or 5), MAX_RESULTS))
        except (TypeError, ValueError):
            limit = 5
        model = model if isinstance(model, str) and _MODEL.match(model) else ''
        params = {
            'database': cfg['database'],
            'query': query.strip()[:MAX_QUERY] if isinstance(query, str) else '',
            'action_xmlid': self._action_xmlid(action),
            'model': model,
            'view_type': view_type if view_type in _VIEW_TYPES else '',
            'limit': limit,
            'groups': self._user_groups(),
        }
        if not (params['query'] or params['action_xmlid'] or params['model']):
            return out
        try:
            res = _post_json(cfg['console_url'] + '/corpaas/knowledge/v1/help',
                             params, TIMEOUT, database=cfg['database'], key=cfg['key'])
        except Exception as exc:  # noqa: BLE001 - 主控台不通就沒有說明，面板照常
            _logger.warning('此畫面說明：查詢主控台失敗（%s）', exc)
            return dict(out, ok=False, error='unreachable')
        if not res.get('ok'):
            if res.get('error') in ('unsigned', 'bad_signature'):
                _logger.warning('此畫面說明：主控台拒絕簽章（%s；本庫%s金鑰）',
                                res.get('error'), '有' if cfg['key'] else '沒有')
            return dict(out, ok=False, error=str(res.get('error') or 'refused')[:60])
        results = []
        for item in (res.get('results') or [])[:limit]:
            if not isinstance(item, dict):
                continue
            url = self._safe_url(item.get('url'), cfg['hosts'])
            if not url:
                continue
            scenario = item.get('scenario')
            if isinstance(scenario, dict):
                scenario = scenario.get('name')
            row = {
                'feature_key': str(item.get('feature_key') or ''),
                'title': str(item.get('title') or url)[:200],
                'url': url,
                'kind': 'upsell' if item.get('kind') == 'upsell' else 'manual',
                'scenario': str(scenario)[:120] if scenario else '',
                'diverged': False,
            }
            # ★ 自然語言查到的功能點可能在別的畫面：那時「目前畫面的模型」不是它的
            #   模型，拿來算只會得到假的不一致。只有「此畫面說明」才能借用。
            diverged, actual, expected = self._diverged(
                item, '' if params['query'] else model)
            if diverged:
                row['diverged'] = True
                if row['feature_key']:
                    self._report_divergence(row['feature_key'], expected, actual)
            results.append(row)
        return dict(out, package=str(res.get('package') or ''), results=results)
