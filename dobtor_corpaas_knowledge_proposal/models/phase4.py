# -*- coding: utf-8 -*-
"""知識主從第四期（建議書這側）：轉為標準模組、P4 客戶既有實例分析。"""
import json

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from odoo.addons.dobtor_corpaas_knowledge.services import remote

PUBLIC_VENDERS = ('odoo', 'dobtor', 'oca')
P4_STALE_DAYS = 30


class KnowledgeDevItemStandard(models.Model):
    """轉為標準模組（計畫 8.6）：開發模組登記到 repo 清單後標記，它的程式知識改判公開、下次送件上傳主體。"""
    _inherit = 'corpaas.knowledge.dev_item'

    standard_module = fields.Boolean(string='已轉為標準模組', readonly=True, copy=False, tracking=True)
    standard_at = fields.Datetime(string='轉為標準模組時間', readonly=True, copy=False)

    def action_make_standard(self):
        for rec in self:
            if rec.state != 'done' or not rec.module_name:
                raise UserError(_('只有已完成、有模組名稱的開發項目可以轉為標準模組。'))
            Repo = self.env.get('infrastructure.repository.module')
            registered = Repo is not None and Repo.sudo().search_count([
                ('technical_name', '=', rec.module_name), ('module_vender', 'in', PUBLIC_VENDERS)])
            if not registered:
                raise UserError(_('模組 %s 還沒登記在模組清單（來源要是 Dobtor／OCA／Odoo）：'
                                  '先登記，公開判定才會把它當公開模組。') % rec.module_name)
            rec.write({'standard_module': True, 'standard_at': fields.Datetime.now()})
            n = rec._republish_code_knowledge()
            rec.message_post(body=_('已轉為標準模組；%s 筆程式知識改為公開，下次送件上傳主體。') % n)
        return True

    def _republish_code_knowledge(self):
        """這個模組的程式知識重新判定公開；之前被退回的改回本地，下次送件會再送。"""
        self.ensure_one()
        Vis = self.env.get('corpaas.knowledge.exchange.visibility')
        if Vis is None:
            return 0
        n = 0
        mod = self.module_name
        for model, dom in (('corpaas.knowledge.code_def', [('module', '=', mod)]),
                           ('corpaas.knowledge.module_summary', [('module', '=', mod)]),
                           ('corpaas.knowledge.code_fact', [('def_ids.module', '=', mod)])):
            recs = self.env[model].sudo().search(dom + [('kb_sync_state', '!=', 'mirror')])
            recs.filtered(lambda r: r.kb_sync_state == 'rejected').write({'kb_sync_state': 'local'})
            n += len(Vis._classify(recs))
        return n


class KnowledgeProposalP4(models.Model):
    """P4：客戶既有實例分析（疊加或換層級時）——唯讀讀出客戶庫已安裝的模組與主要資料量，和方案比對。"""
    _inherit = 'corpaas.knowledge.proposal'

    customer_database_id = fields.Many2one(
        'infrastructure.database', string='客戶既有實例', tracking=True,
        help='客戶已經在用的資料庫（疊加或換層級）；分析只讀，不寫入任何東西')
    customer_analysis_json = fields.Text(readonly=True, copy=False)
    customer_analysis_at = fields.Datetime(string='既有實例分析時間', readonly=True, copy=False)
    customer_analysis_text = fields.Text(string='既有實例分析', compute='_compute_customer_analysis_text')

    @api.depends('customer_analysis_json')
    def _compute_customer_analysis_text(self):
        for rec in self:
            try:
                data = json.loads(rec.customer_analysis_json or '{}')
            except ValueError:
                data = {}
            if not data:
                rec.customer_analysis_text = False
                continue
            lines = [_('客戶庫已安裝 %s 個模組。') % len(data.get('installed') or [])]
            if data.get('extra'):
                lines.append(_('客戶有、方案沒有（要評估加購或開發）：%s') % '、'.join(data['extra'][:40]))
            if data.get('lacking'):
                lines.append(_('方案有、客戶還沒裝（升級後會多出的功能）：%s') % '、'.join(data['lacking'][:40]))
            used = [('%s：%s 筆' % (m, c)) for m, c in sorted((data.get('counts') or {}).items(),
                                                             key=lambda x: -x[1]) if c][:15]
            if used:
                lines.append(_('主要資料量：%s') % '；'.join(used))
            rec.customer_analysis_text = '\n'.join(lines)

    def action_analyze_customer_instance(self):
        for rec in self:
            db = rec.customer_database_id
            if not db or not db.instance_id:
                raise UserError(_('請先選客戶既有實例。'))
            models_ = sorted({f.model for c in rec._capabilities() for f in c.feature_ids if f.model})[:200]
            script = (
                "import json\n"
                "names = %r\n"
                "mods = env['ir.module.module'].sudo().search_read([('state', '=', 'installed')], ['name'])\n"
                "counts = {}\n"
                "for m in names:\n"
                "    if m in env:\n"
                "        try:\n"
                "            counts[m] = env[m].sudo().with_context(active_test=False).search_count([])\n"
                "        except Exception:\n"
                "            counts[m] = None\n"
                "print('__CORPAAS_SHELL__:' + json.dumps({'installed': sorted(r['name'] for r in mods), "
                "'counts': counts}))\n"
            ) % (models_,)
            res = remote.shell_json(self.env, db.instance_id, db.name, script, isolated=True) or {}
            installed = set(res.get('installed') or [])
            pkg_mods = rec.package_id._knowledge_available_modules() if rec.package_id else set()
            data = dict(res, extra=sorted(installed - pkg_mods), lacking=sorted(pkg_mods - installed))
            rec.write({'customer_analysis_json': json.dumps(data, ensure_ascii=False),
                       'customer_analysis_at': fields.Datetime.now()})
        return True


class KnowledgePlanP4(models.Model):
    _inherit = 'corpaas.knowledge.plan'

    def _knowledge_plan_checks(self, moment):
        out = super()._knowledge_plan_checks(moment)
        if moment != 't1' or self.source_type != 'proposal':
            return out
        prop = self.proposal_id
        for r in out:
            if r.get('code') != 'P4':
                continue
            if not prop or not prop.customer_database_id:
                r.update(state='pass', reason=_('新客戶，沒有既有實例'))
            elif not prop.customer_analysis_at:
                r.update(state='block', reason=_('還沒分析客戶既有實例（建議書「既有實例」頁按「分析」）'))
            elif prop.customer_analysis_at < fields.Datetime.subtract(fields.Datetime.now(), days=P4_STALE_DAYS):
                r.update(state='warn', reason=_('既有實例分析超過 %s 天，建議重做') % P4_STALE_DAYS)
            else:
                r.update(state='pass', reason=(prop.customer_analysis_text or '')[:500])
        return out
