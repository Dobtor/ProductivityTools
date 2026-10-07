# -*- coding: utf-8 -*-
"""建議書 → 客戶流程藍圖（dobtor_bpmn）：把方案的能力主線複製給客戶，顧問改成客戶流程做 fit-gap。

★ 藍圖是人的工作底稿：用途「藍圖」、掛客戶，不記系統產生的雜湊（系統永遠不覆蓋它）。
  只複製建議書對應到的能力；沒有對應就用方案全部能力。
"""
from odoo import _, fields, models
from odoo.exceptions import UserError


class BpmnDiagramProposal(models.Model):
    _inherit = 'bpmn.diagram'

    knowledge_proposal_id = fields.Many2one('corpaas.knowledge.proposal', string='來源建議書',
                                            ondelete='set null', index=True, copy=False)


class ProposalBlueprint(models.Model):
    _inherit = 'corpaas.knowledge.proposal'

    blueprint_ids = fields.One2many('bpmn.diagram', 'knowledge_proposal_id', string='客戶藍圖')
    blueprint_count = fields.Integer(compute='_compute_blueprint_count')

    def _compute_blueprint_count(self):
        for rec in self:
            rec.blueprint_count = len(rec.blueprint_ids)

    def _blueprint_capabilities(self):
        self.ensure_one()
        caps = self.env['corpaas.knowledge.mapping'].sudo().search(
            [('proposal_id', '=', self.id), ('capability_id', '!=', False)]).mapped('capability_id')
        return caps or self.package_id.knowledge_capability_ids

    def action_create_blueprints(self):
        """每個對應到的能力複製一張主線圖成客戶藍圖（已有的不重複建）。"""
        self.ensure_one()
        Diagram = self.env['bpmn.diagram'].sudo()
        made = Diagram
        for cap in self._blueprint_capabilities():
            if self.blueprint_ids.filtered(lambda d: d.knowledge_capability_id == cap):
                continue
            src = Diagram.search([('knowledge_capability_id', '=', cap.id),
                                  ('knowledge_package_id', '=', self.package_id.id),
                                  ('knowledge_scope', '=', 'capability')],
                                 order='version desc, id desc', limit=1)
            if not src:
                continue
            made |= src.copy({
                'name': _('%(p)s｜%(c)s（客戶藍圖）', p=self.name, c=cap.name),
                'purpose': 'blueprint', 'partner_id': self.partner_id.id,
                'project_ref': self.name, 'code': 'kb_bp_%s_%s' % (self.id, cap.id),
                'knowledge_proposal_id': self.id, 'knowledge_capability_id': cap.id,
                'knowledge_package_id': self.package_id.id, 'knowledge_scope': False,
                'knowledge_struct_hash': False, 'knowledge_xml_hash': False,
                'xml': src.xml, 'svg': src.svg})
        if not made and not self.blueprint_ids:
            raise UserError(_('方案還沒有能力主線圖：先跑一次知識更新產生流程圖。'))
        return self.action_open_blueprints()

    def action_open_blueprints(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': _('客戶藍圖'),
                'res_model': 'bpmn.diagram', 'view_mode': 'kanban,list,form',
                'domain': [('knowledge_proposal_id', '=', self.id)]}
