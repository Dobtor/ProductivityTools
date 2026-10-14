# -*- coding: utf-8 -*-
"""主體方案產出的交換：步驟區塊（鏡像已上線內容）、方案可用模組清單（計畫 20.2）。"""
import hashlib
import json

from odoo import api, fields, models

from ..lib import protocol


class KnowledgeStepBlockFederated(models.Model):
    _name = 'corpaas.knowledge.step_block'
    _inherit = ['corpaas.knowledge.step_block', 'corpaas.knowledge.federated.mixin']
    #: 內容＝上線版：從屬鏡像只帶已發佈內容；草稿與修訂不出主控台
    _kb_content_fields = ('published_name', 'published_html', 'fingerprint')
    _kb_default_visibility = 'private'

    feature_key = fields.Char(related='feature_id.feature_key', string='功能點鍵')


class SolutionPackageExchange(models.Model):
    _inherit = 'infrastructure.solution.package'

    knowledge_upstream_modules = fields.Text(
        string='主體方案可用模組', readonly=True, copy=False,
        help='從屬：對應主體方案的可用模組（主體發佈）；判斷能力可用／加購／缺少時併入本地的')
    knowledge_upstream_sellable = fields.Text(
        string='主體可單獨販售模組', readonly=True, copy=False,
        help='從屬：主體登記為可單獨販售的模組；判斷「加購可得」用')
    knowledge_exchange_hash = fields.Char(readonly=True, copy=False,
                                          help='主體：上次發佈的可用模組清單雜湊（變了才再發佈）')
    knowledge_upstream_items = fields.Text(
        readonly=True, copy=False,
        help='從屬：主體方案的能力與情境全域識別（訂閱：鏡像到了就掛到本地方案）')

    def _knowledge_available_modules(self):
        have = super()._knowledge_available_modules()
        if self.knowledge_upstream_modules:
            try:
                have |= set(json.loads(self.knowledge_upstream_modules))
            except ValueError:
                pass
        return have

    def _knowledge_module_brief(self, limit=40):
        """從屬方案沒有自己的程式盤點時：用主體方案的模組清單＋已鏡像的模組摘要（建議書開發建議用）。"""
        res = super()._knowledge_module_brief(limit=limit)
        if res or not self.knowledge_upstream_modules:
            return res
        try:
            mods = set(json.loads(self.knowledge_upstream_modules))
        except ValueError:
            return res
        Summary = self.env['corpaas.knowledge.module_summary'].sudo()
        out, seen = [], set()
        for rec in Summary.search([('module', 'in', list(mods)), ('source', '=', 'ai')], order='id desc'):
            if rec.module not in seen:
                seen.add(rec.module)
                out.append(rec.brief())
        return out[:limit]

    def _knowledge_button_targets(self):
        """從屬方案沒有自己的功能點盤點時：用主體鏡像過來的程式結論的主體（model.method）。"""
        res = super()._knowledge_button_targets()
        if res or not self.knowledge_upstream_key:
            return res
        out = set()
        for f in self.env['corpaas.knowledge.code_fact'].sudo().search(
                [('kb_sync_state', '=', 'mirror'), ('state', '=', 'current')]):
            model, _sep, method = f.subject.rpartition('.')
            if model and method:
                out.add((model, method))
        return sorted(out)

    def _kb_upstream_sellable(self):
        self.ensure_one()
        try:
            return set(json.loads(self.knowledge_upstream_sellable or '[]'))
        except ValueError:
            return set()

    # ------------------------------------------------------------------
    def _kb_package_payload(self):
        """主體：這個方案的可用模組清單（模組名稱是公開的技術名，不含客戶資料）。"""
        self.ensure_one()
        available = sorted(self._knowledge_available_modules())
        sellable = []
        RepoModule = self.env.get('infrastructure.repository.module')
        if RepoModule is not None and 'is_sellable' in RepoModule._fields:
            sellable = sorted(set(RepoModule.sudo().search([('is_sellable', '=', True)]).mapped('technical_name'))
                              - {False})
        def uids(recs):
            return sorted(r.kb_uid for r in recs if r.kb_visibility == 'public' and r.kb_sync_state != 'mirror'
                          and r._kb_exchange_ready())
        return {'kind': protocol.PACKAGE_KIND, 'global_key': self.knowledge_global_key,
                'default_code': self.product_tmpl_id.default_code or '',
                'modules': available, 'sellable': sellable,
                'capabilities': uids(self.knowledge_capability_ids),
                'scenarios': uids(self.knowledge_scenario_ids)}

    @api.model
    def _kb_publish_packages(self):
        """主體：可用模組清單有變的方案寫進發佈清單。"""
        Feed = self.env['corpaas.knowledge.exchange.feed'].sudo()
        n = 0
        # ★ 專案方案（客戶專屬）不進發佈清單
        for pkg in self.sudo().search([('knowledge_enabled', '=', True), ('knowledge_kind', '!=', 'project')]):
            payload = pkg._kb_package_payload()
            digest = hashlib.sha1(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:20]
            if digest != pkg.knowledge_exchange_hash:
                pkg.knowledge_exchange_hash = digest
                Feed.create({'kind': protocol.PACKAGE_KIND, 'res_model': pkg._name, 'res_id': pkg.id,
                             'kb_uid': pkg.knowledge_global_key, 'content_hash': digest})
                n += 1
        return n

    @api.model
    def _kb_apply_package(self, payload):
        """從屬：寫到「對應主體方案」是這個方案的本地方案上，並訂閱（掛上主體方案的能力與情境鏡像）。

        ★ 依建議書自動訂閱（已決事項 6）：建議書用到的本地方案還沒填對應時，商品代碼相同就自動對上。
        """
        key = payload.get('global_key')
        if not key:
            return 0
        Pkg = self.sudo()
        code = payload.get('default_code')
        Proposal = self.env.get('corpaas.knowledge.proposal')
        if code and Proposal is not None:
            used = Proposal.sudo().search([('package_id', '!=', False)]).mapped('package_id')
            used.filtered(lambda p: not p.knowledge_upstream_key and p.product_tmpl_id.default_code == code) \
                .write({'knowledge_upstream_key': key})
        pkgs = Pkg.search([('knowledge_upstream_key', '=', key)])
        pkgs.write({'knowledge_upstream_modules': json.dumps(payload.get('modules') or []),
                    'knowledge_upstream_sellable': json.dumps(payload.get('sellable') or []),
                    'knowledge_upstream_items': json.dumps({'capabilities': payload.get('capabilities') or [],
                                                            'scenarios': payload.get('scenarios') or []})})
        pkgs._kb_attach_upstream()
        return len(pkgs)

    def _kb_attach_upstream(self):
        """訂閱：主體方案的能力、情境鏡像已經到了的，掛到本地方案（關聯可寫；鏡像晚到下次拉取再掛）。"""
        Cap = self.env['corpaas.knowledge.capability'].sudo()
        Sc = self.env['corpaas.knowledge.scenario'].sudo()
        n = 0
        for pkg in self.sudo().filtered('knowledge_upstream_items'):
            try:
                items = json.loads(pkg.knowledge_upstream_items)
            except ValueError:
                continue
            caps = Cap.search([('kb_uid', 'in', items.get('capabilities') or [])]) - pkg.knowledge_capability_ids
            scs = Sc.search([('kb_uid', 'in', items.get('scenarios') or [])]) - pkg.knowledge_scenario_ids
            if caps or scs:
                pkg.write({'knowledge_capability_ids': [(4, c.id) for c in caps],
                           'knowledge_scenario_ids': [(4, c.id) for c in scs]})
                n += len(caps) + len(scs)
        return n


class KnowledgeCapabilityExchange(models.Model):
    _inherit = 'corpaas.knowledge.capability'

    def availability_for(self, package):
        """從屬：本地缺的模組若都是主體登記可單獨販售的，算「加購可得」而不是缺少。"""
        state, lacking = super().availability_for(package)
        if state == 'missing' and lacking and lacking <= package._kb_upstream_sellable():
            return 'addon', lacking
        return state, lacking


class _PublishOnApprove(models.AbstractModel):
    """有送審流程的範本：核准上線時寫進發佈清單（內容雜湊沒變也要發——從屬拿的是上線版）。"""
    _name = 'corpaas.knowledge.exchange.publish_on_approve'
    _description = '核准即發佈'

    def _do_publish(self, change, note=None):
        res = super()._do_publish(change, note=note)
        if self.env['corpaas.knowledge.exchange']._mode() == 'master':
            self.env['corpaas.knowledge.exchange.visibility']._classify(self)
            self._kb_publish()
        return res


class KnowledgeCapabilityPublish(models.Model):
    _name = 'corpaas.knowledge.capability'
    _inherit = ['corpaas.knowledge.exchange.publish_on_approve', 'corpaas.knowledge.capability']


class KnowledgeScenarioPublish(models.Model):
    _name = 'corpaas.knowledge.scenario'
    _inherit = ['corpaas.knowledge.exchange.publish_on_approve', 'corpaas.knowledge.scenario']


class KnowledgeSeedPackPublish(models.Model):
    _name = 'corpaas.knowledge.seed_pack'
    _inherit = ['corpaas.knowledge.exchange.publish_on_approve', 'corpaas.knowledge.seed_pack']
