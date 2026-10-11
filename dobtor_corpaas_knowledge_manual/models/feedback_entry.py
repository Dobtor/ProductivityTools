# -*- coding: utf-8 -*-
"""說明書意見的入口（新架構規格 12.1）：後台文章畫面的「提出意見」、前台課程頁（限租戶管理員）。"""
import json

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class KnowledgeFeedbackWizard(models.TransientModel):
    _name = 'corpaas.knowledge.feedback.wizard'
    _description = '提出說明書意見'

    article_id = fields.Many2one('corpaas.knowledge.article', string='文章', required=True)
    step_block_id = fields.Many2one('corpaas.knowledge.step_block', string='步驟區塊',
                                    domain="[('id', 'in', allowed_block_ids)]")
    allowed_block_ids = fields.Many2many(related='article_id.step_block_ids')
    step_no = fields.Integer(string='第幾步')
    shot_name = fields.Char(string='截圖名稱')
    selected_text = fields.Char(string='選取的文字')
    body = fields.Text(string='意見', required=True)

    def action_submit(self):
        self.ensure_one()
        fb = self.article_id._knowledge_feedback_create(
            self.body, source='content', anchor={
                'step_block_id': self.step_block_id.id or None, 'step_no': self.step_no or None,
                'shot_name': self.shot_name or None, 'selected_text': self.selected_text or None})
        fb.action_analyze()
        return {'type': 'ir.actions.client', 'tag': 'display_notification',
                'params': {'type': 'success', 'title': _('已收到意見'),
                           'message': _('AI 分析後會彙整進下一個說明書計畫版本。'),
                           'next': {'type': 'ir.actions.act_window_close'}}}


class KnowledgeArticleFeedback(models.Model):
    _inherit = 'corpaas.knowledge.article'

    def action_open_feedback(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': _('提出意見'),
                'res_model': 'corpaas.knowledge.feedback.wizard', 'view_mode': 'form', 'target': 'new',
                'context': {'default_article_id': self.id}}

    def _knowledge_feedback_create(self, body, source='content', anchor=None, user=None):
        self.ensure_one()
        pkg = self.scenario_id.package_ids[:1]
        if not pkg:
            raise UserError(_('這篇文章沒有所屬的方案。'))
        return self.env['corpaas.knowledge.feedback'].sudo().create({
            'package_id': pkg.id, 'source': source, 'res_model': self._name, 'res_id': self.id,
            'anchor_json': json.dumps({k: v for k, v in (anchor or {}).items() if v}, ensure_ascii=False),
            'body': (body or '').strip()[:4000], 'user_id': (user or self.env.user).id})


class SlideSlideFeedback(models.Model):
    _inherit = 'slide.slide'

    def _knowledge_feedback_article(self):
        """這張 slide 對應的說明書文章（不是方案知識的 slide 回空）。"""
        self.ensure_one()
        pl = self.env['corpaas.knowledge.placement'].sudo().search([('slide_id', '=', self.id)], limit=1)
        return pl.article_id

    def _knowledge_feedback_allowed(self):
        self.ensure_one()
        user = self.env.user
        return not user._is_public() and user.has_group('dobtor_corpaas_knowledge.group_knowledge_feedback') \
            and bool(self._knowledge_feedback_article())
