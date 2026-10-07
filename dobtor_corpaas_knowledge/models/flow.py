# -*- coding: utf-8 -*-
"""任務流程（K13）：以模型的狀態列為骨架，把畫面、按鈕、精靈、報表串成一個業務任務。

★ 流程是推導出來的資料（flow_script，不經 AI、不執行按鈕），每次知識更新重算。
  名稱與摘要另由 AI 起草、走核准（K25）；未核准前用「模型名稱＋狀態欄位」顯示。
★ 和功能點一樣是全域的：同一個模型被多個方案共用時是同一個流程，package_ids 記
  它出現在哪些方案。
"""
import json

from odoo import api, fields, models

EVIDENCE_HELP = '靜態：原始碼分析；租戶：租戶庫實際發生的狀態變更；截圖：說明庫操作時觀察到'
#: 單據的上下游先後：按鈕打開「比自己上游」的單據是查看關聯（採購單上的「銷售訂單」智慧按鈕），
#: 不是交接。不在清單裡的模型不判斷（照舊算交接）。
HANDOFF_ORDER = ['crm.lead', 'sale.order', 'purchase.requisition', 'purchase.order',
                 'mrp.production', 'stock.picking', 'stock.move', 'stock.move.line',
                 'account.move', 'account.payment']


class KnowledgeFlow(models.Model):
    _name = 'corpaas.knowledge.flow'
    _description = '任務流程'
    _order = 'usage_score desc, model'

    name = fields.Char(compute='_compute_name', store=True, string='名稱')
    ai_name = fields.Char(string='業務名稱', help='AI 起草、核准後生效')
    summary = fields.Text(string='摘要')
    model = fields.Char(required=True, index=True, readonly=True)
    model_name = fields.Char(readonly=True)
    state_field = fields.Char(required=True, readonly=True)
    field_type = fields.Selection([('selection', '選項'), ('many2one', '階段')], readonly=True)
    package_ids = fields.Many2many(
        'infrastructure.solution.package', 'corpaas_knowledge_flow_package_rel',
        'flow_id', 'package_id', string='存在於方案', readonly=True)
    feature_ids = fields.Many2many(
        'corpaas.knowledge.feature', 'corpaas_knowledge_flow_feature_rel',
        'flow_id', 'feature_id', string='功能點', readonly=True,
        help='入口畫面、狀態按鈕、按鈕打開的精靈、報表')
    step_ids = fields.One2many('corpaas.knowledge.flow.step', 'flow_id', string='步驟')
    transition_ids = fields.One2many('corpaas.knowledge.flow.transition', 'flow_id',
                                     string='轉換')
    capability_id = fields.Many2one('corpaas.knowledge.capability', string='所屬能力',
                                    ondelete='set null')
    usage_score = fields.Float(string='租戶使用量', readonly=True,
                               help='各方案中最大的一個（彙總顯示）；各方案的值在 usage_json')
    usage_json = fields.Text(readonly=True, help='{方案 id: 使用量}（方案屬性層）')
    structure_hash = fields.Char(readonly=True,
                                 help='步驟＋轉換的雜湊：結構變了才請 AI 重新命名')
    named_hash = fields.Char(readonly=True, help='AI 命名時的結構雜湊')
    last_seen = fields.Datetime(readonly=True)

    _sql_constraints = [
        ('flow_unique', 'unique(model, state_field)', '同一模型同一狀態欄位只有一個流程'),
    ]

    @api.depends('ai_name', 'model_name', 'model')
    def _compute_name(self):
        for rec in self:
            rec.name = rec.ai_name or rec.model_name or rec.model

    def _package_usage(self, package):
        self.ensure_one()
        return json.loads(self.usage_json or '{}').get(str(package.id), 0)

    def _set_package_usage(self, package, value):
        for rec in self:
            data = json.loads(rec.usage_json or '{}')
            data[str(package.id)] = value
            rec.write({'usage_json': json.dumps(data), 'usage_score': max(data.values() or [0])})

    def action_approve_proposals(self):
        """批次層：一次核准這個流程的流程提案，以及流程上功能點的待審歸類提案。"""
        Sel = self.env['corpaas.knowledge.selection']
        props = Sel.search([('state', '=', 'proposed'), '|',
                            ('flow_id', 'in', self.ids),
                            ('feature_id', 'in', self.mapped('feature_ids').ids)])
        return props.action_approve()

    def step_label(self, value):
        self.ensure_one()
        step = self.step_ids.filtered(lambda s: s.value == value)[:1]
        return step.label if step else (value or '')

    @api.model
    def _knowledge_record_observations(self, model, transitions):
        """截圖時觀察到的狀態轉換（runner 回報 {button, from, to}）→ 流程證據。

        狀態列的 data-value 是選項技術值；階段型流程的值可能是名稱，照原樣比對。
        """
        Trans = self.env['corpaas.knowledge.flow.transition'].sudo()
        for flow in self.search([('model', '=', model)]):
            for ob in transitions or []:
                fr, to, btn = str(ob.get('from') or ''), str(ob.get('to') or ''), \
                    str(ob.get('button') or '')
                if not to or fr == to:
                    continue
                hit = flow.transition_ids.filtered(
                    lambda t: (t.to_value or '') == to and (t.from_value or '') in (fr, '')
                    and (t.button_name or '') in (btn, ''))
                if hit:
                    hit.write({'ev_shot': True})
                else:
                    Trans.create({'flow_id': flow.id, 'from_value': fr, 'to_value': to,
                                  'button_name': btn, 'ev_shot': True})
        return True

    def as_outline(self):
        """給出口與 AI 用的精簡結構。"""
        self.ensure_one()
        return {
            'name': self.name, 'model': self.model,
            'steps': [{'value': s.value, 'label': s.label, 'on_statusbar': s.on_statusbar}
                      for s in self.step_ids.sorted('sequence')],
            'transitions': [{
                'from': self.step_label(t.from_value) if t.from_value else '（任何狀態）',
                'to': self.step_label(t.to_value) if t.to_value else '',
                'button': t.button_label or t.button_name,
                'opens': t.opens_model or '', 'count': t.usage_count,
            } for t in self.transition_ids],
        }


class KnowledgeFlowStep(models.Model):
    _name = 'corpaas.knowledge.flow.step'
    _description = '流程步驟'
    _order = 'flow_id, sequence'

    flow_id = fields.Many2one('corpaas.knowledge.flow', required=True, ondelete='cascade',
                              index=True)
    sequence = fields.Integer()
    value = fields.Char(required=True, help='選項的技術值；階段用名稱')
    label = fields.Char()
    on_statusbar = fields.Boolean(string='顯示在狀態列')


class KnowledgeFlowTransition(models.Model):
    _name = 'corpaas.knowledge.flow.transition'
    _description = '流程轉換'
    _order = 'flow_id, from_value, to_value'

    flow_id = fields.Many2one('corpaas.knowledge.flow', required=True, ondelete='cascade',
                              index=True)
    from_value = fields.Char(string='起點', help='空白＝任何狀態都看得到這顆按鈕')
    to_value = fields.Char(string='終點', help='空白＝不改狀態或推不出來')
    button_name = fields.Char(string='按鈕方法')
    button_label = fields.Char(string='按鈕')
    button_feature_id = fields.Many2one('corpaas.knowledge.feature', string='按鈕功能點',
                                        ondelete='set null')
    conditional = fields.Boolean(string='條件可見',
                                 help='按鈕的顯示條件還牽涉狀態以外的欄位')
    opens_model = fields.Char(string='打開', help='按鈕打開的精靈或畫面模型')
    opens_flow_id = fields.Many2one('corpaas.knowledge.flow', string='交接到',
                                    ondelete='set null')
    ev_static = fields.Boolean(string='靜態', help=EVIDENCE_HELP)
    ev_tenant = fields.Boolean(string='租戶', help=EVIDENCE_HELP)
    ev_shot = fields.Boolean(string='截圖', help=EVIDENCE_HELP)
    usage_count = fields.Integer(string='租戶次數', readonly=True, help='各方案相加')
    usage_json = fields.Text(readonly=True, help='{方案 id: 次數}（方案屬性層）')
    package_ids = fields.Many2many(
        'infrastructure.solution.package', 'corpaas_knowledge_flow_transition_package_rel',
        'transition_id', 'package_id', string='靜態推得出的方案', readonly=True)

    def _package_usage(self, package):
        self.ensure_one()
        return json.loads(self.usage_json or '{}').get(str(package.id), 0)

    def is_handoff(self, target_model=None):
        """這顆按鈕是不是把工作交給下游單據（而不是回頭查看上游的關聯單據）。"""
        self.ensure_one()
        src = self.flow_id.model
        dst = target_model or self.opens_model or (self.opens_flow_id.model if self.opens_flow_id
                                                   else False)
        if not dst or dst == src:
            return False
        if src in HANDOFF_ORDER and dst in HANDOFF_ORDER:
            return HANDOFF_ORDER.index(dst) > HANDOFF_ORDER.index(src)
        return True

    def display_label(self):
        """給讀者看的按鈕名稱：沒有字面名稱（只剩動作編號）時用按鈕功能點的名稱。"""
        self.ensure_one()
        label = (self.button_label or '').strip()
        if label and not label.isdigit():
            return label
        return self.button_feature_id.name or ''

    def _set_package_usage(self, package, value):
        """只改本方案的次數；租戶證據＝任一方案有次數。"""
        for rec in self:
            data = json.loads(rec.usage_json or '{}')
            if value:
                data[str(package.id)] = value
            else:
                data.pop(str(package.id), None)
            total = sum(data.values())
            rec.write({'usage_json': json.dumps(data) if data else False,
                       'usage_count': total, 'ev_tenant': bool(total)})

    _sql_constraints = [
        ('transition_unique',
         'unique(flow_id, from_value, to_value, button_name)', '轉換重複'),
    ]
