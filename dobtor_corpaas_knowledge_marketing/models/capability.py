# -*- coding: utf-8 -*-
from odoo import _, fields, models
from odoo.exceptions import UserError


class KnowledgeCapability(models.Model):
    _inherit = 'corpaas.knowledge.capability'

    pitch_ids = fields.One2many('corpaas.knowledge.pitch', 'capability_id', string='能力卡片')
    pitch_count = fields.Integer(compute='_compute_pitch_count')

    def _compute_pitch_count(self):
        for rec in self:
            rec.pitch_count = len(rec.pitch_ids)

    def _marketing_scenario_for(self, package):
        """能力的適用情境中，優先挑方案也引用的那一個。"""
        self.ensure_one()
        both = self.scenario_ids & package.knowledge_scenario_ids
        return (both or self.scenario_ids)[:1]

    def action_ai_draft_pitch(self):
        """「AI 起草行銷文案」：能力所屬的每個方案各一張卡片（已有就改寫同一張），排入佇列起草。

        ★ AI 不在 HTTP 請求裡跑（`corpaas.knowledge.ai.enqueue`）；卡片先建好，
          起草完成後會自動送審，結果寫在卡片的紀錄裡。
        """
        Pitch = self.env['corpaas.knowledge.pitch']
        Ai = self.env['corpaas.knowledge.ai']
        pitches = Pitch
        for cap in self:
            packages = cap.package_ids.filtered('product_tmpl_id')
            if not packages:
                raise UserError(_('能力「%s」還沒有掛到任何方案，無法決定要寫在哪個商品頁。')
                                % cap.name)
            for pkg in packages:
                pitch = Pitch.search([('capability_id', '=', cap.id),
                                      ('product_tmpl_id', '=', pkg.product_tmpl_id.id),
                                      '|', ('package_id', '=', pkg.id),
                                      ('package_id', '=', False),
                                      ('state', '!=', 'retired')], limit=1)
                if not pitch:
                    pitch = Pitch.create({
                        'capability_id': cap.id, 'product_tmpl_id': pkg.product_tmpl_id.id,
                        'package_id': pkg.id,
                        'scenario_id': cap._marketing_scenario_for(pkg).id,
                        'headline': cap.name, 'sequence': cap.sequence,
                    })
                Ai.enqueue(pitch, '_ai_draft_run', pkg, note=_('AI 起草行銷文案'))
                pitches |= pitch
        return {
            'type': 'ir.actions.client', 'tag': 'display_notification',
            'params': {'type': 'info', 'sticky': False, 'title': _('已排入 AI 工作'),
                       'message': _('%s 張能力卡片排入 AI 起草，完成後會自動送審。') % len(pitches),
                       'next': self.action_open_pitches(pitches)},
        }

    def action_open_pitches(self, pitches=None):
        pitches = pitches if pitches is not None else self.mapped('pitch_ids')
        action = {
            'type': 'ir.actions.act_window', 'name': _('能力卡片'),
            'res_model': 'corpaas.knowledge.pitch', 'view_mode': 'list,form',
            'domain': [('id', 'in', pitches.ids)],
            'context': {'default_capability_id': self[:1].id},
        }
        if len(pitches) == 1:
            action.update(view_mode='form', res_id=pitches.id)
        return action
