# -*- coding: utf-8 -*-
from odoo import api, fields, models

KNOWLEDGE_STEPS = [
    {'code': 'kb_check', 'name': '確認說明主機上的母體與黃金庫', 'est': 3},
    {'code': 'kb_golden_sync', 'name': '黃金庫對齊母體程式碼', 'est': 60},
    {'code': 'kb_inventory', 'name': '盤點功能點（唯讀）', 'est': 40},
    {'code': 'kb_fingerprint', 'name': '計算畫面指紋並比對', 'est': 90},
    {'code': 'kb_ai_catalog', 'name': 'AI 歸類新功能與同義詞', 'est': 120},
    {'code': 'kb_sandbox', 'name': '重建說明庫（清除＋示範資料）', 'est': 180},
    {'code': 'kb_shoot', 'name': '無頭瀏覽器截圖', 'est': 300},
    {'code': 'kb_outlets', 'name': '更新說明、行銷與建議書素材', 'est': 120},
    {'code': 'kb_cleanup', 'name': '收尾', 'est': 2},
]


class CorpaasQueue(models.Model):
    _inherit = 'corpaas.queue'

    operate = fields.Selection(
        selection_add=[('knowledge_refresh', 'Knowledge Refresh (docs/marketing)'),
                       ('knowledge_ai_job', 'Knowledge AI Job'),
                       ('knowledge_sandbox', 'Knowledge Sandbox Rebuild/Drop')],
        ondelete={'knowledge_refresh': 'cascade', 'knowledge_ai_job': 'cascade',
                  'knowledge_sandbox': 'cascade'})

    @api.model
    def _get_queue_steps(self):
        steps = super()._get_queue_steps()
        steps[('solution.package', 'knowledge_refresh')] = KNOWLEDGE_STEPS
        steps[('solution.package', 'knowledge_ai_job')] = [
            {'code': 'kb_ai_job', 'name': 'AI 工作', 'est': 120}]
        steps[('solution.package', 'knowledge_sandbox')] = [
            {'code': 'kb_sandbox_op', 'name': '重建／刪除說明庫', 'est': 300}]
        return steps
