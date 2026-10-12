# -*- coding: utf-8 -*-
"""主體的交換端點（計畫第 7 節）。只在 exchange_mode＝master 且該項已啟用時服務。

POST /corpaas/knowledge/exchange/v1/lookup    {items: [{kind, key}]}        → {ok, results}
POST /corpaas/knowledge/exchange/v1/ingest    {items: [payload]}            → {ok, results}
POST /corpaas/knowledge/exchange/v1/feed      {cursor, limit}               → {ok, items, cursor, more}
POST /corpaas/knowledge/exchange/v1/feedback  {items: [{kind, kb_uid, text}]} → {ok, results}
POST /corpaas/knowledge/exchange/v1/help      {global_key, query, action_xmlid, model, view_type, limit, groups} → {ok, results}（說明連結分流）
POST /corpaas/knowledge/exchange/v1/transfer  {transfer: {...同意紀錄}, items} → {ok, ref, count}（移交，含私有）
全部帶 schema_version 與 nonce；標頭 X-KB-Peer／X-KB-Timestamp／X-KB-Signature。
"""
import logging

from odoo import http
from odoo.http import request

from ..lib import protocol

_logger = logging.getLogger(__name__)


class KnowledgeExchangeApi(http.Controller):

    def _auth(self, feature, kw):
        """回 (peer, None) 或 (None, 錯誤代碼)。

        ★ 不分辨「對端不存在」與「簽章錯」：前者是列舉從屬代碼的探測訊號。
        """
        env = request.env(su=True)
        Ex = env['corpaas.knowledge.exchange']
        if Ex._mode() != 'master' or not Ex._enabled(feature):
            return None, 'disabled'
        if kw.get('schema_version') != protocol.SCHEMA_VERSION:
            return None, 'schema_mismatch'
        headers = request.httprequest.headers
        code = (headers.get('X-KB-Peer') or '').strip()[:64]
        peer = env['corpaas.knowledge.exchange.peer'].search(
            [('code', '=', code), ('role', '=', 'replica'), ('active', '=', True)], limit=1) if code else None
        ip = request.httprequest.remote_addr or ''
        if not peer or not peer._ip_allowed(ip):
            return None, 'bad_signature'
        err = protocol.verify(peer.key, headers.get('X-KB-Timestamp'), request.httprequest.get_data(),
                              headers.get('X-KB-Signature') or '')
        if err:
            return None, 'bad_signature'
        nonce = kw.get('nonce')
        if not isinstance(nonce, str) or not nonce or not env['corpaas.knowledge.help.nonce']._knowledge_claim(
                'x|%s|%s' % (peer.code, nonce[:64])):
            return None, 'replayed'
        return peer, None

    @http.route('/corpaas/knowledge/exchange/v1/lookup', type='json', auth='public', csrf=False, methods=['POST'])
    def lookup(self, items=None, **kw):
        peer, err = self._auth('lookup', kw)
        if err:
            return {'ok': False, 'error': err}
        return {'ok': True, 'results': request.env(su=True)['corpaas.knowledge.exchange']._serve_lookup(
            peer, items if isinstance(items, list) else [])}

    @http.route('/corpaas/knowledge/exchange/v1/ingest', type='json', auth='public', csrf=False, methods=['POST'])
    def ingest(self, items=None, **kw):
        peer, err = self._auth('ingest', kw)
        if err:
            return {'ok': False, 'error': err}
        return {'ok': True, 'results': request.env(su=True)['corpaas.knowledge.exchange']._serve_ingest(
            peer, items if isinstance(items, list) else [])}

    @http.route('/corpaas/knowledge/exchange/v1/feed', type='json', auth='public', csrf=False, methods=['POST'])
    def feed(self, cursor=0, limit=200, **kw):
        peer, err = self._auth('feed', kw)
        if err:
            return {'ok': False, 'error': err}
        try:
            cursor = int(cursor or 0)
        except (TypeError, ValueError):
            cursor = 0
        return dict(request.env(su=True)['corpaas.knowledge.exchange']._serve_feed(peer, cursor, limit), ok=True)

    @http.route('/corpaas/knowledge/exchange/v1/feedback', type='json', auth='public', csrf=False, methods=['POST'])
    def feedback(self, items=None, **kw):
        peer, err = self._auth('ingest', kw)
        if err:
            return {'ok': False, 'error': err}
        return {'ok': True, 'results': request.env(su=True)['corpaas.knowledge.exchange']._serve_feedback(
            peer, items if isinstance(items, list) else [])}

    @http.route('/corpaas/knowledge/exchange/v1/transfer', type='json', auth='public', csrf=False, methods=['POST'])
    def transfer(self, transfer=None, items=None, **kw):
        peer, err = self._auth('ingest', kw)
        if err:
            return {'ok': False, 'error': err}
        try:
            rec = request.env(su=True)['corpaas.knowledge.exchange.transfer']._receive(
                peer, transfer, items if isinstance(items, list) else [])
        except Exception as e:  # noqa: BLE001 — 缺同意紀錄等：回錯誤，不寫任何東西
            request.env.cr.rollback()
            return {'ok': False, 'error': str(e)[:200]}
        return {'ok': True, 'ref': 'transfer:%s' % rec.id, 'count': rec.item_count}

    @http.route('/corpaas/knowledge/exchange/v1/help', type='json', auth='public', csrf=False, methods=['POST'])
    def help(self, global_key=None, query=None, action_xmlid=None, model=None, view_type=None, limit=5,
             groups=None, **kw):
        peer, err = self._auth('lookup', kw)
        if err:
            return {'ok': False, 'error': err}
        return {'ok': True, 'results': request.env(su=True)['corpaas.knowledge.exchange']._serve_help(
            peer, global_key, query=query, action_xmlid=action_xmlid, model=model, view_type=view_type,
            limit=limit, groups=groups)}
