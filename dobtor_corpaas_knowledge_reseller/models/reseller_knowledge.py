# -*- coding: utf-8 -*-
"""方案知識的經銷商範圍、說明書匯出、webhook 與 AI 費用計費。"""
import logging
import re

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

PARAM_AI_MARKUP = 'corpaas.reseller.knowledge_ai_markup'
_IMG_RE = re.compile(r'/web/image/(\d+)[^"\'\s)]*')


class SolutionPackageKnowledgeReseller(models.Model):
    _inherit = 'infrastructure.solution.package'

    knowledge_reseller_assigned_id = fields.Many2one(
        'res.partner', string='指定經銷商', index=True, copy=False,
        help='由經銷商 API 建立的專案知識直接記下經銷商（不靠客戶歸屬推算）。')
    knowledge_reseller_id = fields.Many2one(
        'res.partner', string='知識歸屬經銷商', compute='_compute_knowledge_reseller_id',
        store=True, index=True,
        help='經銷商上架的方案，或經銷商代管客戶的專案知識：經銷商可在白標後台管理、'
             'AI 費用記到他的批發月結單。')

    @api.depends('knowledge_reseller_assigned_id', 'publisher_id', 'knowledge_kind', 'knowledge_project_partner_id',
                 'knowledge_project_partner_id.corpaas_reseller_id',
                 'knowledge_project_instance_id.reseller_id')
    def _compute_knowledge_reseller_id(self):
        for pkg in self:
            reseller = pkg.knowledge_reseller_assigned_id or pkg.publisher_id
            if not reseller and pkg.knowledge_kind == 'project':
                cp = pkg.knowledge_project_partner_id.commercial_partner_id
                reseller = (cp if cp.is_reseller else cp.corpaas_reseller_id) \
                    or pkg.knowledge_project_instance_id.reseller_id
            pkg.knowledge_reseller_id = reseller

    # ------------------------------------------------------------------
    # 經銷商建立專案知識
    # ------------------------------------------------------------------
    @api.model
    def _reseller_create_project(self, reseller, database, consent_note):
        """以這座服務的資料庫為基準建立專案知識（只唯讀盤點；說明庫是清除客戶資料後的複本）。"""
        db = database.sudo()
        if db.state != 'active':
            raise UserError(_('Service is not active.'))
        inst = db.instance_id
        if self.sudo().search_count([('knowledge_kind', '=', 'project'),
                                     ('knowledge_project_instance_id', '=', inst.id)]):
            raise UserError(_('This instance already has project knowledge.'))
        note = (consent_note or '').strip()
        if not note:
            raise UserError(_('consent_note is required: the customer must agree to AI '
                              'reading the source code.'))
        wiz = self.env['corpaas.knowledge.project.wizard'].sudo().create({
            'instance_id': inst.id, 'database_id': db.id,
            'partner_id': db.partner_id.commercial_partner_id.id,
            'consent': True,
            'consent_note': _('經銷商 %(r)s 聲明：%(n)s', r=reseller.display_name, n=note[:200]),
        })
        action = wiz.action_confirm()
        pkg = self.sudo().browse(action['res_id'])
        pkg.knowledge_reseller_assigned_id = reseller.id
        pkg._reseller_ensure_plan()
        return pkg

    def _reseller_ensure_plan(self):
        """沒有說明書製作計畫就開初版並建底稿（盤點 → 就緒檢查 → AI 擬計畫 → 待核准）。

        平台上這一步原本是人在方案表單按的；經銷商那邊沒有這顆按鈕，不自動開的話
        專案知識只會停在「盤點完成」，永遠等不到計畫。回傳是否新開。"""
        self.ensure_one()
        Plan = self.env['corpaas.knowledge.plan'].sudo()
        if Plan.search_count([('package_id', '=', self.id), ('source_type', '=', 'product'),
                              ('state', '!=', 'superseded')]):
            return False
        plan = Plan.create({'package_id': self.id, 'source_type': 'product', 'version': 1})
        plan.action_build_ledger()
        return True

    # ------------------------------------------------------------------
    # 說明書匯出（給白標後台匯入自己的網站）
    # ------------------------------------------------------------------
    def _reseller_manual_export(self):
        """已上線的說明書：課程 → 章節 → 文章（html），圖片改成 corpaas-image:<id>。

        回傳 (payload, 圖片 id 集合)。只送已發佈、未撤下的內容。
        """
        self.ensure_one()
        Placement = self.env['corpaas.knowledge.placement'].sudo()
        pls = Placement.search([('package_id', '=', self.id), ('manual_retired', '=', False),
                                ('slide_id', '!=', False)])
        images = set()
        channels = []
        for ch in pls.mapped('channel_id').sorted('id'):
            slides = []
            for s in ch.slide_ids.filtered('is_published').sorted(lambda x: (x.sequence, x.id)):
                html = s.html_content or ''

                def repl(m):
                    images.add(int(m.group(1)))
                    return 'corpaas-image:%s' % m.group(1)
                slides.append({
                    'id': s.id, 'name': s.name, 'sequence': s.sequence,
                    'is_category': bool(s.is_category),
                    'html': _IMG_RE.sub(repl, html) if html else '',
                    'updated_at': str(s.write_date),
                })
            channels.append({'id': ch.id, 'name': ch.name,
                             'description': ch.description or '', 'slides': slides})
        return {'package_id': self.id, 'name': self.display_name, 'channels': channels}, images


class KnowledgePlanResellerEvents(models.Model):
    _inherit = 'corpaas.knowledge.plan'

    def write(self, vals):
        before = {p.id: p.state for p in self} if 'state' in vals else {}
        res = super().write(vals)
        if before:
            for plan in self:
                reseller = plan.package_id.knowledge_reseller_id
                if not reseller or before.get(plan.id) == plan.state:
                    continue
                event = {'review': 'knowledge_plan_review',
                         'done': 'knowledge_published'}.get(plan.state)
                if event:
                    try:
                        plan._reseller_emit(event)
                    except Exception:  # noqa: BLE001 - 通知失敗不可中斷知識流程
                        _logger.warning('[knowledge] reseller event %s failed', event, exc_info=True)
        return res

    def _reseller_emit(self, event):
        self.ensure_one()
        pkg = self.package_id
        ref = False
        db = pkg.knowledge_project_database_id
        if db:
            req = self.env['infrastructure.provision.request'].sudo().search(
                [('database_id', '=', db.id), ('external_ref', '!=', False)], limit=1)
            ref = req.external_ref or False
        return self.env['reseller.webhook.event']._emit(
            pkg.knowledge_reseller_id, event, ref,
            {'knowledge_id': pkg.id, 'plan_id': self.id, 'plan_state': self.state})


class StatementLineKnowledge(models.Model):
    _inherit = 'reseller.billing.statement.line'

    line_type = fields.Selection(selection_add=[('knowledge', '方案知識 AI 費用')],
                                 ondelete={'knowledge': 'set default'})


class BillingStatementKnowledge(models.Model):
    _inherit = 'reseller.billing.statement'

    @api.model
    def _generate_for_period(self, period_start, period_end, reseller=None):
        made = super()._generate_for_period(period_start, period_end, reseller=reseller)
        self._apply_knowledge_costs(period_start, period_end, reseller=reseller)
        return made

    @api.model
    def _apply_knowledge_costs(self, period_start, period_end, reseller=None):
        """這一期屬於經銷商的方案知識 AI 費用（實際呼叫，不含快取命中）× 平台加成。"""
        try:
            markup = float(self.env['ir.config_parameter'].sudo().get_param(PARAM_AI_MARKUP) or 1.0)
        except ValueError:
            markup = 1.0
        Call = self.env['corpaas.knowledge.ai.call'].sudo()
        dom = [('create_date', '>=', fields.Datetime.to_datetime(period_start)),
               ('create_date', '<', fields.Datetime.add(fields.Datetime.to_datetime(period_end),
                                                        days=1)),
               ('cached', '=', False), ('package_id.knowledge_reseller_id', '!=', False),
               # 用經銷商自己的 AI Hub 跑的（他自己的 Claude 帳號付費）不再向他收一次
               ('package_id.knowledge_hub_url', 'in', (False, ''))]
        if reseller:
            dom.append(('package_id.knowledge_reseller_id', '=', reseller.id))
        by_reseller = {}
        for call in Call.search(dom):
            rs = call.package_id.knowledge_reseller_id
            by_reseller.setdefault(rs, 0.0)
            by_reseller[rs] += call.cost_usd or 0.0
        usd = self.env.ref('base.USD', raise_if_not_found=False)
        Line = self.env['reseller.billing.statement.line'].sudo()
        made = Line.browse()
        for rs, cost in by_reseller.items():
            if cost <= 0:
                continue
            st = self.sudo().search([('reseller_id', '=', rs.id),
                                     ('period_start', '=', period_start)], limit=1)
            if not st:
                st = self.sudo().create({
                    'reseller_id': rs.id, 'period_start': period_start, 'period_end': period_end,
                    'name': self.env['ir.sequence'].next_by_code(
                        'reseller.billing.statement') or '/'})
            if st.state != 'draft' or st.line_ids.filtered(lambda l: l.line_type == 'knowledge'):
                continue
            amount = cost * markup
            made |= Line.create({
                'statement_id': st.id, 'line_type': 'knowledge',
                'description': _('方案知識 AI 費用（USD %(c).2f × %(m)s）', c=cost, m=markup),
                'source_currency_id': (usd or st.currency_id).id,
                'base_price': amount,
                'amount': st._convert_to_statement(amount, usd or st.currency_id),
            })
        return made
