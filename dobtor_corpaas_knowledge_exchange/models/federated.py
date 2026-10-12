# -*- coding: utf-8 -*-
"""可交換紀錄的匯出、鏡像 upsert、發佈清單（計畫 8.1～8.3、20.2「鏡像穩定 id、只 upsert」）。

★ 鏡像一律 upsert、不刪了重建：從屬的計畫、建議書以 FK 引用能力與情境（restrict／cascade），
  刪了重建會連帶刪掉或擋住。找既有紀錄依交換鍵（事實類自然鍵、範本類 kb_uid）。
★ 寫入鏡像一律帶 EXCHANGE_SYNC（內容唯讀規則的例外）；RPC 偽造不了。
"""
import json
import logging
import re

from odoo import api, models

from odoo.addons.dobtor_corpaas_knowledge.models.federation import EXCHANGE_SYNC

from ..lib import protocol

_logger = logging.getLogger(__name__)


def _sync(records):
    return records.with_context(knowledge_exchange_sync=EXCHANGE_SYNC)


class KnowledgeFederatedExchange(models.AbstractModel):
    _inherit = 'corpaas.knowledge.federated.mixin'

    # ------------------------------------------------------------------
    # 匯出
    # ------------------------------------------------------------------
    def _kb_kind(self):
        return protocol.MODEL_KIND.get(self._name)

    def _kb_exchange_ready(self):
        """這筆有沒有值得交換的內容（只有結構、還沒 AI 讀過的不送也不發佈）。"""
        self.ensure_one()
        kind = self._kb_kind()
        if kind == 'code_def':
            return bool(self.summary_json)
        if kind == 'code_fact':
            return bool(self.fact_json) and self.state == 'current'
        if kind == 'module_summary':
            return self.source == 'ai' and bool(self.summary_json)
        if kind == 'step_block':
            return bool(self.published_rev_no) and self.published_html not in (False, None) \
                and self.state != 'retired'
        if 'published_rev_no' in self._fields:
            # 有送審流程的範本：目前內容就是核准上線那一版才發（草稿、待審不出主控台）
            if self.published_rev_no and self.state == 'published':
                return True
            # ★ 新架構以「說明書製作計畫」為唯一核准點：能力、情境由已核准的計畫建出，
            #   不再走自己的送審（實機 2026-10-12：主體 19 個能力沒有一個是「已上線」狀態）
            return self._kb_approved_by_plan()
        return bool(kind)

    def _kb_approved_by_plan(self):
        self.ensure_one()
        from odoo.addons.dobtor_corpaas_knowledge.models.plan import LIVE_STATES
        return bool(self.env['corpaas.knowledge.plan.item'].sudo().search_count([
            ('res_model', '=', self._name), ('res_id', '=', self.id),
            ('plan_id.state', 'in', LIVE_STATES + ('superseded',))]))

    def _kb_export(self):
        """可攜的交換內容（不帶本地 id）。"""
        self.ensure_one()
        kind = self._kb_kind()
        spec = protocol.KINDS[kind]
        out = {'kind': kind, 'kb_uid': self.kb_uid, 'kb_origin': self.kb_origin,
               'kb_content_hash': self.kb_content_hash, 'content': self._kb_content_payload()}
        for f in spec['key'] + spec['extra']:
            if f in self._fields and f not in out:
                v = self[f]
                out[f] = v if v is not False else None
        if kind == 'code_fact':
            out['defs'] = [d._kb_export() for d in self.def_ids]
        return out

    # ------------------------------------------------------------------
    # 找既有紀錄、鏡像 upsert
    # ------------------------------------------------------------------
    @api.model
    def _kb_find(self, payload):
        kind = self._kb_kind()
        spec = protocol.KINDS[kind]
        Model = self.sudo().with_context(active_test=False)
        if payload.get('kb_uid') and not spec.get('adopt_local', True):
            rec = Model.search([('kb_uid', '=', payload['kb_uid'])], limit=1)
            if rec:
                return rec
        if spec['key'] != ('kb_uid',) and all(payload.get(f) for f in spec['key']):
            dom = [(f, '=', payload.get(f)) for f in spec['key']]
            if not spec.get('adopt_local', True) and self.env['corpaas.knowledge.exchange']._mode() == 'replica':
                dom.append(('kb_sync_state', '=', 'mirror'))
            rec = Model.search(dom, limit=1)
            if rec:
                return rec
        return Model.search([('kb_uid', '=', payload.get('kb_uid'))], limit=1) if payload.get('kb_uid') \
            else Model.browse()

    @api.model
    def _kb_free_code(self, code, origin, exclude=None):
        """範本代碼在兩個主控台各自編號（cap_<id>），撞到本地的就加來源後綴。"""
        if not code or 'code' not in self._fields:
            return code
        dom = [('code', '=', code)] + ([('id', '!=', exclude.id)] if exclude else [])
        Model = self.sudo().with_context(active_test=False)
        if not Model.search_count(dom):
            return code
        base = '%s_%s' % (code, re.sub(r'\W', '', origin or 'x'))
        cand, n = base, 2
        while Model.search_count([('code', '=', cand)] + dom[1:]):
            cand, n = '%s%s' % (base, n), n + 1
        return cand

    @api.model
    def _kb_vals_from(self, payload, state='mirror', trust='master', origin=None):
        kind = self._kb_kind()
        spec = protocol.KINDS[kind]
        vals = {}
        for f, v in (payload.get('content') or {}).items():
            field = self._fields.get(f)
            if field and field.type not in ('many2one', 'many2many', 'one2many'):
                vals[f] = v if v is not None else False
        for f in spec['key'] + spec['extra']:
            if f in self._fields and f in payload and f != 'kb_uid':
                vals[f] = payload[f] if payload[f] is not None else False
        if 'feature_key' in vals:
            feature = self.env['corpaas.knowledge.feature'].sudo().search(
                [('feature_key', '=', vals.pop('feature_key'))], limit=1)
            if not feature:
                raise ValueError('本地沒有功能點 %s（方案還沒盤點到）' % payload.get('feature_key'))
            vals['feature_id'] = feature.id
        if kind == 'step_block' and state == 'mirror':
            # 鏡像在從屬建成已上線狀態：前台與文章只用上線版
            vals.update({'name': vals.get('published_name') or payload.get('anchor') or '?',
                         'html': vals.get('published_html') or '', 'state': 'published',
                         'published_rev_no': 1})
        elif state == 'mirror' and protocol.KINDS[kind]['category'] == 'template' \
                and 'published_rev_no' in self._fields:
            # 範本鏡像＝主體已核准的正式版：在從屬直接是上線狀態（不走從屬的送審）
            vals.update({'state': 'published', 'published_rev_no': 1})
        if kind == 'code_fact':
            Def = self.env['corpaas.knowledge.code_def']
            vals['def_ids'] = [(6, 0, [Def._kb_upsert(d, state=state, trust=trust, origin=origin).id
                                       for d in payload.get('defs') or []])]
        return vals

    @api.model
    def _kb_upsert(self, payload, state='mirror', trust='master', origin=None, visibility='public'):
        """依交換鍵 upsert；回傳紀錄。內容雜湊相同就不動（冪等）。

        state／trust：從屬寫鏡像＝('mirror', 'master')；主體入庫＝('local', 'replica')。
        """
        rec = self._kb_find(payload)
        if rec and rec.kb_content_hash == payload.get('kb_content_hash') \
                and rec.kb_sync_state == state and (rec.kb_uid == payload.get('kb_uid') or not payload.get('kb_uid')):
            return rec
        vals = self._kb_vals_from(payload, state=state, trust=trust, origin=origin)
        meta = {'kb_sync_state': state, 'kb_trust': trust, 'kb_visibility': visibility,
                'kb_origin': origin or payload.get('kb_origin')}
        uid = payload.get('kb_uid')
        if uid and (not rec or rec.kb_uid != uid):
            # 全域識別要跟主體一致；同一個 uid 在本地被別筆占著（理論上不會）就保留本地的
            clash = self.sudo().with_context(active_test=False).search(
                [('kb_uid', '=', uid)] + ([('id', '!=', rec.id)] if rec else []), limit=1)
            if not clash:
                meta['kb_uid'] = uid
        if 'code' in vals:
            if rec:
                # ★ 既有紀錄不改代碼：情境、資料包的代碼是示範資料 xmlid 的命名空間
                vals.pop('code')
            else:
                vals['code'] = self._kb_free_code(vals['code'], meta['kb_origin'])
        if rec:
            _sync(rec).write(dict(vals, **meta))
        else:
            rec = _sync(self.sudo()).create([dict(vals, **meta)])
        if payload.get('kb_content_hash') and rec.kb_content_hash != payload['kb_content_hash']:
            _logger.warning('[exchange] %s %s 內容雜湊與來源不符（%s ≠ %s）：兩邊版本可能不同',
                            self._name, rec.id, rec.kb_content_hash, payload['kb_content_hash'])
        # ☠️ 回傳呼叫端的環境：帶著同步旗標的紀錄之後怎麼寫都不會被擋，唯讀規則就破了
        return self.browse(rec.id)

    # ------------------------------------------------------------------
    # 發佈清單（主體）
    # ------------------------------------------------------------------
    def _kb_refresh_hash(self):
        before = {r.id: r.kb_content_hash for r in self}
        res = super()._kb_refresh_hash()
        if self and self.env['corpaas.knowledge.exchange']._mode() == 'master':
            changed = self.filtered(lambda r: r.kb_content_hash != before.get(r.id))
            changed._kb_publish()
        return res

    @api.model
    def _kb_publish_unsent(self, limit=2000):
        """主體：可交換、但這一版內容還沒寫進發佈清單的（例如計畫核准後才建出的能力）補發。"""
        Feed = self.env['corpaas.knowledge.exchange.feed'].sudo()
        recs = self.sudo().search([('kb_sync_state', '!=', 'mirror'), ('kb_visibility', '=', 'public')],
                                  limit=limit)
        sent = {(r.res_id, r.content_hash) for r in Feed.search([('res_model', '=', self._name)])}
        todo = recs.filtered(lambda r: (r.id, r.kb_content_hash) not in sent and r._kb_exchange_ready())
        return todo._kb_publish()

    def _kb_publish(self):
        """寫進發佈清單：公開、非鏡像、有內容的才發。"""
        Feed = self.env['corpaas.knowledge.exchange.feed'].sudo()
        rows = [{'kind': r._kb_kind(), 'res_model': r._name, 'res_id': r.id, 'kb_uid': r.kb_uid,
                 'content_hash': r.kb_content_hash}
                for r in self if r._kb_kind() and r.kb_visibility == 'public'
                and r.kb_sync_state != 'mirror' and r._kb_exchange_ready()]
        if rows:
            Feed.create(rows)
        return len(rows)


class KnowledgeExchangeVisibility(models.AbstractModel):
    """公開與私有的判定（計畫第 4 節；預設私有）。"""
    _name = 'corpaas.knowledge.exchange.visibility'
    _description = '知識公開判定'

    PUBLIC_VENDERS = ('odoo', 'dobtor', 'oca')

    @api.model
    def _public_modules(self, modules):
        """回傳 modules 裡判為公開的集合。

        公開：Odoo 核心（(core)、映像官方模組）；或登記在模組清單且來源為 odoo／dobtor／oca。
        系統參數 corpaas_knowledge.exchange_private_modules（逗號分隔）強制私有。
        ★ 主體入庫時用主體自己的清單再判一次（雙重把關）。
        """
        modules = {m for m in modules if m}
        if not modules:
            return set()
        icp = self.env['ir.config_parameter'].sudo()
        forced = {m.strip() for m in (icp.get_param('corpaas_knowledge.exchange_private_modules') or '').split(',')
                  if m.strip()}
        public = {m for m in modules if m == '(core)'}
        for tree in self.env['corpaas.knowledge.code_tree'].sudo().search([('core_hashes', '!=', False)]):
            try:
                core = json.loads(tree.core_hashes or '{}')
            except ValueError:
                continue
            public |= modules & set(core)
        RepoModule = self.env.get('infrastructure.repository.module')
        if RepoModule is not None and 'module_vender' in RepoModule._fields:
            rest = modules - public
            if rest:
                for r in RepoModule.sudo().search([('technical_name', 'in', list(rest)),
                                                   ('module_vender', 'in', self.PUBLIC_VENDERS)]):
                    public.add(r.technical_name)
        return public - forced

    @api.model
    def _desired(self, records):
        """{record: 'public'|'private'}，只判程式知識與規則；範本類維持原值（從屬只靠人工上收送出）。"""
        kind = protocol.MODEL_KIND.get(records._name)
        if kind == 'code_def':
            pub = self._public_modules(records.mapped('module'))
            return {r: 'public' if r.module in pub else 'private' for r in records}
        if kind == 'module_summary':
            pub = self._public_modules(records.mapped('module'))
            return {r: 'public' if r.module in pub else 'private' for r in records}
        if kind == 'code_fact':
            pub = self._public_modules(records.mapped('def_ids.module'))
            # ★ 繼承鏈任何一段是私有模組 → 整個結論私有
            return {r: 'public' if r.def_ids and set(r.def_ids.mapped('module')) <= pub else 'private'
                    for r in records}
        if kind == 'rule':
            return {r: 'private' if r.package_id else r.kb_visibility for r in records}
        if kind == 'step_block':
            pub = self._public_modules(records.mapped('feature_id.module'))
            return {r: 'public' if r.feature_id.module in pub else 'private' for r in records}
        return {r: r.kb_visibility for r in records}

    @api.model
    def _classify(self, records):
        """套用判定（鏡像不動）；回傳由私有轉公開的紀錄。"""
        records = records.filtered(lambda r: r.kb_sync_state != 'mirror')
        became = records.browse()
        for rec, vis in self._desired(records).items():
            if rec.kb_visibility != vis:
                _sync(rec).write({'kb_visibility': vis})
                if vis == 'public':
                    became |= rec
        if became and self.env['corpaas.knowledge.exchange']._mode() == 'master':
            became._kb_publish()
        return became

    @api.model
    def _cron_classify(self, batch=5000):
        for kind in ('code_def', 'module_summary', 'code_fact', 'rule', 'step_block'):
            Model = self.env[protocol.KINDS[kind]['model']].sudo()
            self._classify(Model.search([('kb_sync_state', '!=', 'mirror')], limit=batch, order='id desc'))
        return True
