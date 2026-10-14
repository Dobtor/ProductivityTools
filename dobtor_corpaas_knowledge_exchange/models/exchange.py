# -*- coding: utf-8 -*-
"""交換服務：主體端的處理（lookup／ingest／feed／feedback）與從屬端的呼叫（先查主體、送件、拉取）。

開關（系統參數，預設全關，逐項啟用：先 lookup，再 ingest，最後 feed）：
  corpaas_knowledge.exchange_mode            off｜master｜replica
  corpaas_knowledge.exchange_enable_lookup   True／False
  corpaas_knowledge.exchange_enable_ingest   True／False
  corpaas_knowledge.exchange_enable_feed     True／False
關閉＝回到各自獨立運作；鏡像保留（內容唯讀）。

★ HTTP 只在 controllers/exchange.py；這裡的 _serve_* 收已驗證的對端與參數，可直接測。
★ 從屬呼叫主體一律「失敗當作沒有」：主體停機時從屬照常本地算（驗收 V4），送件匣稍後補送。
"""
import json
import logging
from datetime import timedelta

from odoo import api, fields, models

from odoo.addons.dobtor_corpaas_knowledge.models.federation import console_code

from ..lib import protocol

_logger = logging.getLogger(__name__)

BATCH = 100
FEED_PAGE = 200
BACKOFF_MINUTES = (10, 30, 120, 360, 1440)
RECHECK_REVIEW_HOURS = 24


class KnowledgeExchange(models.AbstractModel):
    _name = 'corpaas.knowledge.exchange'
    _description = '知識交換'

    # ------------------------------------------------------------------
    # 設定
    # ------------------------------------------------------------------
    @api.model
    def _mode(self):
        mode = self.env['ir.config_parameter'].sudo().get_param('corpaas_knowledge.exchange_mode', 'off')
        return mode if mode in ('master', 'replica') else 'off'

    @api.model
    def _enabled(self, feature):
        return self._mode() != 'off' and self.env['ir.config_parameter'].sudo().get_param(
            'corpaas_knowledge.exchange_enable_%s' % feature, 'False') == 'True'

    @api.model
    def _master_peer(self):
        return self.env['corpaas.knowledge.exchange.peer'].sudo().search([('role', '=', 'master')], limit=1)

    @api.model
    def _model(self, kind):
        return self.env[protocol.KINDS[kind]['model']].sudo()

    # ==================================================================
    # 主體端
    # ==================================================================
    @api.model
    def _serve_lookup(self, peer, items):
        """依（類別、交換鍵）批次查；只回公開、有內容的。"""
        out = []
        Vis = self.env['corpaas.knowledge.exchange.visibility']
        for item in (items or [])[:500]:
            kind = item.get('kind') if isinstance(item, dict) else None
            if kind not in protocol.KINDS or protocol.KINDS[kind]['category'] not in ('fact', 'output'):
                continue
            rec = self._model(kind)._kb_find(item.get('key') or {})
            if rec and rec.kb_sync_state != 'mirror':
                Vis._classify(rec)
            found = bool(rec) and rec.kb_visibility == 'public' and rec._kb_exchange_ready()
            out.append({'kind': kind, 'key': item.get('key'), 'found': found,
                        'payload': rec._kb_export() if found else None})
        return out

    @api.model
    def _serve_ingest(self, peer, items):
        """批次送件；逐筆回覆 exists／ingested／review／rejected。同鍵同雜湊冪等。"""
        Log = self.env['corpaas.knowledge.exchange.ingest'].sudo()
        Promo = self.env['corpaas.knowledge.exchange.promotion'].sudo()
        Vis = self.env['corpaas.knowledge.exchange.visibility']
        out = []
        for payload in (items or [])[:BATCH]:
            kind = payload.get('kind') if isinstance(payload, dict) else None
            if kind not in protocol.KINDS:
                out.append({'kind': kind, 'result': protocol.REJECTED, 'reason': 'unknown_kind'})
                continue
            spec = protocol.KINDS[kind]
            key = protocol.key_of(kind, payload)
            res, reason, rec = protocol.REJECTED, '', None
            if spec['category'] == 'output':
                reason = 'master_only'   # 主體方案的產出只從主體流向從屬
            elif spec['category'] == 'fact':
                modules = self._payload_modules(kind, payload)
                if not modules or modules - Vis._public_modules(modules):
                    # ★ 主體用自己的模組清單再判一次：私有的不收（雙重把關）
                    reason = 'private'
                else:
                    Model = self._model(kind)
                    rec = Model._kb_find(payload)
                    if rec and rec._kb_exchange_ready():
                        res = protocol.EXISTS
                    else:
                        rec = Model._kb_upsert(payload, state='local', trust='replica', origin=peer.code)
                        res = protocol.INGESTED
            else:
                res, reason, rec = self._ingest_template(peer, kind, payload, Promo)
            Log.create({'peer_id': peer.id, 'kind': kind, 'key_text': json.dumps(key, ensure_ascii=False)[:500],
                        'kb_uid': payload.get('kb_uid'), 'content_hash': payload.get('kb_content_hash'),
                        'result': res, 'reason': reason,
                        'res_model': rec._name if rec else False, 'res_id': rec.id if rec else 0})
            out.append({'kind': kind, 'key': list(key), 'result': res, 'reason': reason,
                        'kb_uid': rec.kb_uid if rec and 'kb_uid' in rec._fields else payload.get('kb_uid')})
        return out

    @api.model
    def _ingest_template(self, peer, kind, payload, Promo):
        """範本類：建上收提案（待審）；已審過的回覆結果（從屬定期重送以得知審核結果）。"""
        uid = payload.get('kb_uid')
        existing = self._model(kind).search([('kb_uid', '=', uid)], limit=1) if uid else None
        if existing and existing.kb_sync_state != 'mirror':
            return protocol.EXISTS, '', existing
        promo = Promo.search([('peer_id', '=', peer.id), ('kind', '=', kind), ('kb_uid', '=', uid),
                              ('type', '=', 'promotion')], order='id desc', limit=1) if uid else Promo
        if promo and promo.state == 'merged':
            return protocol.REJECTED, 'merged:%s' % promo.merged_into_uid, None
        if promo and promo.state == 'rejected':
            return protocol.REJECTED, 'rejected', None
        if not promo or promo.state != 'pending':
            name = (payload.get('content') or {}).get('name') or uid or '?'
            Promo.create({'peer_id': peer.id, 'kind': kind, 'kb_uid': uid, 'name': name,
                          'payload': json.dumps(payload, ensure_ascii=False),
                          'similar_text': Promo._similar(kind, name)})
        return protocol.REVIEW, '', None

    @api.model
    def _payload_modules(self, kind, payload):
        if kind in ('code_def', 'module_summary'):
            return {payload.get('module')} - {None, False, ''}
        if kind == 'code_fact':
            return {d.get('module') for d in payload.get('defs') or []} - {None, False, ''}
        return set()

    @api.model
    def _serve_feed(self, peer, cursor, limit=FEED_PAGE):
        """依游標取變更清單；同一筆只回最新狀態。回傳 {items, cursor, more}。"""
        Feed = self.env['corpaas.knowledge.exchange.feed'].sudo()
        Vis = self.env['corpaas.knowledge.exchange.visibility']
        limit = max(1, min(int(limit or FEED_PAGE), 500))
        rows = Feed.search([('id', '>', int(cursor or 0))], limit=limit)
        items, seen = [], set()
        for row in reversed(rows):
            ident = (row.res_model, row.res_id)
            if ident in seen:
                continue
            seen.add(ident)
            rec = self.env[row.res_model].sudo().browse(row.res_id).exists() if row.res_model in self.env else None
            if row.kind == protocol.PACKAGE_KIND:
                # ★ 專案方案（客戶專屬）不發；舊的發佈紀錄也一併略過
                if rec and getattr(rec, 'knowledge_kind', 'package') != 'project':
                    items.append({'op': 'upsert', 'payload': rec._kb_package_payload()})
                continue
            if rec and row.op == 'upsert' and rec.kb_visibility == 'public' and rec.kb_sync_state != 'mirror' \
                    and not Vis._project_only(rec):
                if rec._kb_exchange_ready():
                    items.append({'op': 'upsert', 'payload': rec._kb_export()})
                # 暫時是草稿／待審：這次不送（核准時會再發佈），也不作廢從屬已有的上一版
                continue
            items.append({'op': 'retract', 'kind': row.kind, 'kb_uid': row.kb_uid})
        items.reverse()
        return {'items': items, 'cursor': rows[-1].id if rows else int(cursor or 0),
                'more': len(rows) == limit}

    @api.model
    def _serve_feedback(self, peer, items):
        """對主體知識的修改意見（不含客戶內容）：進上收提案清單，類型＝修改意見。"""
        Promo = self.env['corpaas.knowledge.exchange.promotion'].sudo()
        out = []
        for item in (items or [])[:50]:
            kind = item.get('kind') if isinstance(item, dict) else None
            text = (item.get('text') or '').strip()[:4000] if kind in protocol.KINDS else ''
            rec = self._model(kind).search([('kb_uid', '=', item.get('kb_uid'))], limit=1) if text else None
            if not rec:
                out.append({'ok': False})
                continue
            Promo.create({'type': 'feedback', 'peer_id': peer.id, 'kind': kind, 'kb_uid': rec.kb_uid,
                          'name': rec.display_name, 'note': text})
            out.append({'ok': True})
        return out

    @api.model
    def _serve_help(self, peer, global_key, query=None, action_xmlid=None, model=None, view_type=None,
                    limit=5, groups=None):
        """主體：從屬的租戶查主體公開方案的說明連結（說明連結分流，計畫 20.3）。

        只回公開說明（連結＋功能名稱），不回任何租戶資料；方案依全域識別認。
        """
        pkg = self.env['infrastructure.solution.package'].sudo().search(
            [('knowledge_global_key', '=', (global_key or '')[:120])], limit=1) if global_key else None
        # ★ 專案方案的說明是客戶專屬，不回給任何從屬
        if not pkg or getattr(pkg, 'knowledge_kind', 'package') == 'project':
            return []
        try:
            limit = max(1, min(int(limit or 5), 10))
        except (TypeError, ValueError):
            limit = 5
        groups = [g for g in groups if isinstance(g, str)][:200] if isinstance(groups, list) else None
        Help = self.env['corpaas.knowledge.help']
        matches = Help._match(pkg, query=query, action_xmlid=action_xmlid, model=model, view_type=view_type,
                              limit=limit, groups=groups)
        results = self.env['corpaas.knowledge.hooks']._knowledge_help_links(
            pkg, matches, query, {'limit': limit, 'groups': groups, 'exchange_peer': peer.code})
        return [r for r in results if r.get('kind') != 'upsell'][:limit]

    @api.model
    def _upstream_help(self, package, query, ctx):
        """從屬：方案對應主體方案時，向主體查說明連結。主體不通就當沒有（本地結果照給）。"""
        if self._mode() != 'replica' or not self._enabled('lookup') or not package.knowledge_upstream_key \
                or ctx.get('exchange_peer'):
            return []
        try:
            res = self._call('help', {'global_key': package.knowledge_upstream_key, 'query': query or '',
                                      'action_xmlid': ctx.get('action_xmlid') or '', 'model': ctx.get('model') or '',
                                      'view_type': ctx.get('view_type') or '', 'limit': ctx.get('limit') or 5,
                                      'groups': ctx.get('groups')}, timeout=4)
        except Exception as e:  # noqa: BLE001
            _logger.info('[exchange] 向主體查說明連結失敗：%s', e)
            return []
        return [r for r in res.get('results') or [] if isinstance(r, dict) and r.get('url')]

    @api.model
    def action_publish_all(self):
        """主體上線交換時：把既有公開知識全部寫進發佈清單（之後的變更自動發佈）。"""
        Vis = self.env['corpaas.knowledge.exchange.visibility']
        n = 0
        for kind in protocol.ORDER:
            recs = self._model(kind).search([('kb_sync_state', '!=', 'mirror')])
            Vis._classify(recs)
            n += recs._kb_publish()
        n += self.env['infrastructure.solution.package']._kb_publish_packages()
        return n

    # ==================================================================
    # 從屬端
    # ==================================================================
    @api.model
    def _call(self, endpoint, params, timeout=20):
        peer = self._master_peer()
        if not (peer and peer.url and peer.key):
            raise ValueError('沒有設定主體（網址與金鑰）')
        try:
            res = protocol.post('%s/corpaas/knowledge/exchange/v1/%s' % (peer.url.rstrip('/'), endpoint),
                                params, peer.key, console_code(self.env), timeout=timeout)
        except Exception as e:
            peer.write({'last_error': str(e)[:200]})
            raise
        peer.write({'last_ok': fields.Datetime.now(), 'last_error': False})
        return res

    @api.model
    def _prefetch(self, modules=(), defs=(), facts=()):
        """先查主體：本地沒有內容的，問主體；主體有的存成鏡像。回傳寫入的鏡像筆數。"""
        if self._mode() != 'replica' or not self._enabled('lookup'):
            return 0
        items = []
        Summary, Def, Fact = self._model('module_summary'), self._model('code_def'), self._model('code_fact')
        for m, h in modules:
            rec = Summary.search([('module', '=', m), ('dir_hash', '=', h)], limit=1)
            if not (rec and rec._kb_exchange_ready()):
                items.append({'kind': 'module_summary', 'key': {'module': m, 'dir_hash': h}})
        for h, method, module in defs:
            rec = Def.search([('def_hash', '=', h), ('method', '=', method), ('module', '=', module)], limit=1)
            if not (rec and rec._kb_exchange_ready()):
                items.append({'kind': 'code_def', 'key': {'def_hash': h, 'method': method, 'module': module}})
        for subject, chain in facts:
            rec = Fact.search([('subject', '=', subject), ('chain_hash', '=', chain)], limit=1)
            if not (rec and rec._kb_exchange_ready()):
                items.append({'kind': 'code_fact', 'key': {'subject': subject, 'chain_hash': chain}})
        n = 0
        for i in range(0, len(items), 200):
            try:
                res = self._call('lookup', {'items': items[i:i + 200]})
            except Exception as e:  # noqa: BLE001 — 主體不通：本地照算
                _logger.info('[exchange] 查主體失敗，本地照算：%s', e)
                return n
            for r in res.get('results') or []:
                if r.get('found') and isinstance(r.get('payload'), dict) and r.get('kind') in protocol.KINDS:
                    self._model(r['kind'])._kb_upsert(r['payload'])
                    n += 1
        return n

    @api.model
    def _lookup_step_blocks(self, pairs):
        """從屬：（功能點鍵, 畫面指紋）相同的主體已上線步驟區塊 → 鏡像；回傳 {(鍵, 指紋): 區塊}。

        客戶專屬說明書（第三期）寫原生功能前先呼叫：指紋相同就引用主體版本，不同才在本地分岔。
        """
        out = {}
        if self._mode() != 'replica' or not self._enabled('lookup') or not pairs:
            return out
        items = [{'kind': 'step_block', 'key': {'feature_key': k, 'fingerprint': fp}} for k, fp in pairs]
        try:
            res = self._call('lookup', {'items': items[:500]})
        except Exception as e:  # noqa: BLE001
            _logger.info('[exchange] 查主體步驟區塊失敗：%s', e)
            return out
        Block = self._model('step_block')
        for r in res.get('results') or []:
            if r.get('found') and isinstance(r.get('payload'), dict):
                try:
                    with self.env.cr.savepoint():
                        blk = Block._kb_upsert(r['payload'])
                except ValueError as e:
                    _logger.info('[exchange] 步驟區塊鏡像略過：%s', e)
                    continue
                key = r.get('key') or {}
                out[(key.get('feature_key'), key.get('fingerprint'))] = blk
        return out

    @api.model
    def _collect(self, limit=500):
        """公開、本地自己算、有內容的程式知識 → 送件匣。範本類不自動送（要人工上收）。"""
        if self._mode() != 'replica':
            return 0
        Vis = self.env['corpaas.knowledge.exchange.visibility']
        Outbox = self.env['corpaas.knowledge.exchange.outbox'].sudo()
        me = console_code(self.env)
        n = 0
        for kind in ('code_def', 'module_summary', 'code_fact'):
            recs = self._model(kind).search([('kb_sync_state', '=', 'local'), ('kb_origin', '=', me)],
                                            limit=limit, order='id')
            recs = recs.filtered(lambda r: r._kb_exchange_ready())
            Vis._classify(recs)
            for rec in recs.filtered(lambda r: r.kb_visibility == 'public'):
                n += self._enqueue(rec, Outbox)
        return n

    @api.model
    def _enqueue(self, rec, Outbox=None):
        Outbox = Outbox or self.env['corpaas.knowledge.exchange.outbox'].sudo()
        if Outbox.search_count([('res_model', '=', rec._name), ('res_id', '=', rec.id),
                                ('content_hash', '=', rec.kb_content_hash)]):
            return 0
        payload = rec._kb_export()
        Outbox.create({'kind': rec._kb_kind(), 'res_model': rec._name, 'res_id': rec.id,
                       'name': rec.display_name, 'kb_uid': rec.kb_uid, 'content_hash': rec.kb_content_hash,
                       'payload': json.dumps(payload, ensure_ascii=False)})
        rec.write({'kb_sync_state': 'pending'})
        return 1

    @api.model
    def _push(self):
        """送件匣 → 主體 ingest；依回覆更新。失敗依退避重試。"""
        if self._mode() != 'replica' or not self._enabled('ingest'):
            return 0
        Outbox = self.env['corpaas.knowledge.exchange.outbox'].sudo()
        now = fields.Datetime.now()
        recheck = now - timedelta(hours=RECHECK_REVIEW_HOURS)
        rows = Outbox.search(['|', '&', ('state', 'in', ('pending', 'error')),
                              '|', ('next_try', '=', False), ('next_try', '<=', now),
                              '&', ('state', '=', 'review'), ('write_date', '<=', recheck)],
                             limit=BATCH, order='id')
        sendable, payloads = Outbox, []
        for row in rows:
            rec = row.record()
            # ★ 送出前再檢查一次：紀錄還在、仍公開
            if not rec or (rec.kb_visibility != 'public' and row.kind in ('code_def', 'module_summary', 'code_fact')):
                row.write({'state': 'rejected', 'reason': '送出前檢查：已不存在或已改為私有'})
                continue
            sendable |= row
            payloads.append(json.loads(row.payload))
        if not sendable:
            return 0
        try:
            res = self._call('ingest', {'items': payloads}, timeout=60)
        except Exception as e:  # noqa: BLE001
            for row in sendable:
                wait = BACKOFF_MINUTES[min(row.attempts, len(BACKOFF_MINUTES) - 1)]
                row.write({'state': 'error', 'attempts': row.attempts + 1, 'reason': str(e)[:200],
                           'next_try': now + timedelta(minutes=wait)})
            return 0
        for row, r in zip(sendable, res.get('results') or []):
            self._apply_reply(row, r)
        return len(sendable)

    @api.model
    def _apply_reply(self, row, reply):
        result = reply.get('result')
        rec = row.record()
        state_map = {protocol.INGESTED: 'ingested', protocol.EXISTS: 'exists', protocol.REVIEW: 'review',
                     protocol.REJECTED: 'rejected'}
        row.write({'state': state_map.get(result, 'error'), 'reason': (reply.get('reason') or '')[:200],
                   'attempts': row.attempts + 1})
        if rec:
            sync = {'ingested': 'sent', 'exists': 'sent', 'review': 'sent', 'rejected': 'rejected'}.get(row.state)
            if sync and rec.kb_sync_state != 'mirror':
                rec.write({'kb_sync_state': sync})

    @api.model
    def _pull(self):
        """依游標拉主體發佈清單，upsert 鏡像。回傳處理筆數。"""
        if self._mode() != 'replica' or not self._enabled('feed'):
            return 0
        peer = self._master_peer()
        n = 0
        for _page in range(20):
            try:
                res = self._call('feed', {'cursor': peer.feed_cursor, 'limit': FEED_PAGE}, timeout=60)
            except Exception as e:  # noqa: BLE001
                _logger.info('[exchange] 拉主體發佈清單失敗：%s', e)
                return n
            for item in res.get('items') or []:
                try:
                    self._apply_feed_item(item)
                    n += 1
                except Exception as e:  # noqa: BLE001 — 一筆壞掉不擋其他；游標照前進，紀錄在 log
                    _logger.warning('[exchange] 發佈清單項目寫入失敗：%s', e)
            peer.sudo().write({'feed_cursor': int(res.get('cursor') or peer.feed_cursor)})
            if not res.get('more'):
                break
        # 方案訂閱：這次才到的能力／情境鏡像掛上去
        self.env['infrastructure.solution.package'].sudo().search(
            [('knowledge_upstream_items', '!=', False)])._kb_attach_upstream()
        return n

    @api.model
    def _apply_feed_item(self, item):
        if item.get('op') == 'upsert':
            payload = item.get('payload') or {}
            if payload.get('kind') == protocol.PACKAGE_KIND:
                self.env['infrastructure.solution.package']._kb_apply_package(payload)
                return
            if payload.get('kind') in protocol.KINDS:
                with self.env.cr.savepoint():
                    self._model(payload['kind'])._kb_upsert(payload)
            return
        kind = item.get('kind')
        if kind in protocol.KINDS and item.get('kb_uid'):
            rec = self._model(kind).search([('kb_uid', '=', item['kb_uid']), ('kb_sync_state', '=', 'mirror')],
                                           limit=1)
            if rec and 'active' in rec._fields:
                rec.write({'active': False})

    @api.model
    def _send_feedback(self, record, text):
        """從屬：對鏡像紀錄送修改意見給主體（不得含客戶內容，由送件人負責）。"""
        res = self._call('feedback', {'items': [{'kind': record._kb_kind(), 'kb_uid': record.kb_uid,
                                                 'text': text}]})
        return bool((res.get('results') or [{}])[0].get('ok'))

    @api.model
    def _submit_promotion(self, records):
        """從屬：把本地範本項目送上收提案（人工決定才送）。"""
        n = 0
        Vis = self.env['corpaas.knowledge.exchange.visibility']
        for rec in records:
            if Vis._project_only(rec):
                continue   # 專案客戶的範本不上收
            if rec.kb_sync_state in ('local', 'rejected') and protocol.KINDS.get(rec._kb_kind() or '', {}).get(
                    'category') == 'template':
                n += self._enqueue(rec)
        return n

    @api.model
    def _cron_exchange(self):
        mode = self._mode()
        if mode == 'off':
            return True
        Vis = self.env['corpaas.knowledge.exchange.visibility']
        if mode == 'master':
            Vis._cron_classify()
            for kind in ('capability', 'scenario', 'seed_pack', 'role', 'rule'):
                self._model(kind)._kb_publish_unsent()
            self.env['infrastructure.solution.package']._kb_publish_packages()
            return True
        self._collect()
        self._push()
        self._pull()
        return True
