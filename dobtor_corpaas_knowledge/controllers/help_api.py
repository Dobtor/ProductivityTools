# -*- coding: utf-8 -*-
"""租戶端（dobtor_ai_bridge_help）查說明連結的 API。

★ 公開端點：說明頁本來就是公開的（已定案），查詢結果只有公開連結與功能名稱，
  沒有任何客戶資料。仍然限流，避免被當成爬蟲入口。
★ 連結一律由系統產生、結構化回傳；模型不寫連結（面板的防外洩設計不變）。

POST /corpaas/knowledge/v1/help  (type=json)
  params: database, query?, action_xmlid?, model?, view_type?, limit?
  → {ok, package, results: [{feature_key, title, url, kind, scenario, anchor,
                             fingerprint:{elements, scope_hash}}]}
"""
import json
import logging
import threading
import time

from odoo import fields, http
from odoo.http import request


_logger = logging.getLogger(__name__)

_RATE = {}
_RATE_LOCK = threading.Lock()
RATE_PER_MINUTE = 120


def _rate_ok(key):
    """以「資料庫＋來源 IP」為單位限流。

    ☠️ 只看 IP 等於全主機共用一個額度：同一台主機上的所有租戶從同一個出口 IP 來。
    """
    now = time.time()
    with _RATE_LOCK:
        hits = [t for t in _RATE.get(key, []) if now - t < 60]
        if len(hits) >= RATE_PER_MINUTE:
            _RATE[key] = hits
            return False
        hits.append(now)
        _RATE[key] = hits
        if len(_RATE) > 20000:
            _RATE.clear()
    return True


def _as_int(value, default, low, high):
    try:
        return max(low, min(int(value), high))
    except (TypeError, ValueError):
        return default


class KnowledgeHelpApi(http.Controller):

    @http.route('/corpaas/knowledge/v1/help', type='json', auth='public',
                csrf=False, methods=['POST'])
    def help(self, database=None, query=None, action_xmlid=None, model=None,
             view_type=None, limit=5, groups=None, **kw):
        ip = request.httprequest.remote_addr or '?'
        if not database or not isinstance(database, str) or len(database) > 120:
            return {'ok': False, 'error': 'invalid_database'}
        if not _rate_ok('%s|%s' % (database, ip)):
            return {'ok': False, 'error': 'rate_limited'}
        env = request.env(su=True)
        err = self._verify(env, database)
        if err:
            return {'ok': False, 'error': err}
        package = env['corpaas.knowledge.help']._package_for_database(database)
        if not package:
            # ★ 不分辨「庫不存在」與「沒有說明」：前者是列舉客戶資料庫的探測訊號。
            return {'ok': True, 'package': False, 'results': []}
        limit = _as_int(limit, 5, 1, 10)
        user_groups = [g for g in (groups or []) if isinstance(g, str)][:200] \
            if isinstance(groups, list) else None
        matches = env['corpaas.knowledge.help']._match(
            package, query=query, action_xmlid=action_xmlid, model=model,
            view_type=view_type, limit=limit, groups=user_groups)
        results = env['corpaas.knowledge.hooks']._knowledge_help_links(
            package, matches, query, {'database': database, 'limit': limit,
                                      'groups': user_groups})
        env['corpaas.knowledge.help.log'].create({
            'package_id': package.id, 'database': database[:120],
            'query': (query or '')[:500], 'action_xmlid': (action_xmlid or '')[:200],
            'model': (model or '')[:120], 'hits': len(results),
            'top_score': matches[0][1] if matches else 0.0,
        })
        return {'ok': True, 'package': package.display_name,
                'results': self._trim(results, limit)}

    @staticmethod
    def _verify(env, database):
        """租戶簽章（見 models/help_key.py）。回 None＝通過。"""
        return env['infrastructure.database']._knowledge_verify_help_request(
            database, request.httprequest.headers, request.httprequest.get_data())

    @staticmethod
    def _trim(results, limit):
        """截到 limit 筆，但保留一個位置給加購連結（出口掛勾的順序是先說明後加購，
        直接切前 limit 筆會把加購全部切掉）。"""
        manuals = [r for r in results if r.get('kind') != 'upsell']
        upsells = [r for r in results if r.get('kind') == 'upsell']
        # 只有一個名額時留給說明（加購是附帶的）；否則說明與加購至少各一。
        keep_up = min(len(upsells), (1 if limit > 1 else 0) if manuals else limit)
        return manuals[:limit - keep_up] + upsells[:max(keep_up, limit - len(manuals))]

    @http.route('/corpaas/knowledge/v1/divergence', type='json', auth='public',
                csrf=False, methods=['POST'])
    def divergence(self, database=None, feature_key=None, expected=None, actual=None,
                   **kw):
        """D5：租戶端算出的指紋與文章不一致時回報。只記事件，不回資料。"""
        ip = request.httprequest.remote_addr or '?'
        if not database or not feature_key or not isinstance(database, str) \
                or not _rate_ok('div|%s|%s' % (database, ip)):
            return {'ok': False}
        env = request.env(su=True)
        if self._verify(env, database):
            return {'ok': False}
        package = env['corpaas.knowledge.help']._package_for_database(database)
        feature = env['corpaas.knowledge.feature'].search(
            [('feature_key', '=', feature_key)], limit=1)
        # ★ 只收「這個庫的方案確實有這個功能」的回報；同一庫同一功能一天只記一次，
        #   偽造的回報灌不出「N 個租戶分歧」。
        if package and feature and feature.is_present_in(package):
            Event = env['corpaas.knowledge.event']
            since = fields.Datetime.subtract(fields.Datetime.now(), days=1)
            dup = Event.search_count([('type', '=', 'divergence'), ('package_id', '=', package.id),
                                      ('feature_id', '=', feature.id), ('create_date', '>=', since),
                                      ('note', '=', database[:120])])
            if not dup:
                Event.create({
                    'type': 'divergence', 'package_id': package.id, 'feature_id': feature.id,
                    'note': database[:120],
                    'payload': json.dumps({'database': database[:120],
                                           'expected': (expected or '')[:64],
                                           'actual': (actual or '')[:64]}),
                })
        return {'ok': True}
