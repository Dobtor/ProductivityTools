# -*- coding: utf-8 -*-
"""匯入售前痛點 xlsx（部門表 → corpaas.knowledge.pain）。"""
import base64

from odoo import _, fields, models
from odoo.exceptions import UserError

from ..services import presales_xlsx


class ProposalImport(models.TransientModel):
    _name = 'corpaas.knowledge.proposal.import'
    _description = '匯入售前痛點 xlsx'

    proposal_id = fields.Many2one('corpaas.knowledge.proposal', required=True,
                                  ondelete='cascade')
    file = fields.Binary(string='售前痛點 xlsx', required=True)
    filename = fields.Char()
    replace = fields.Boolean(string='取代先前匯入的痛點',
                             help='勾選：先刪掉這張建議書「匯入」來源的痛點再匯入；手動輸入的不動。')

    def _parse(self):
        self.ensure_one()
        try:
            wb = presales_xlsx.load_workbook_bytes(base64.b64decode(self.file))
        except ImportError:
            raise UserError(_('伺服器沒有安裝 openpyxl。'))
        except Exception as e:  # noqa: BLE001 — 壞檔各種例外都一樣處理
            raise UserError(_('無法讀取 xlsx：%s') % e)
        try:
            return presales_xlsx.parse_workbook(wb)
        finally:
            wb.close()

    def action_import(self):
        self.ensure_one()
        proposal = self.proposal_id
        proposal._ensure_draft()
        rows = self._parse()
        if not rows:
            raise UserError(_('檔案裡沒有找到痛點（每張部門表第 2 列表頭、第 3 列起資料）。'))
        if self.replace:
            proposal.pain_ids.filtered(lambda p: p.source == 'import').unlink()
        start = max(proposal.pain_ids.mapped('sequence') or [0])
        self.env['corpaas.knowledge.pain'].create([{
            'proposal_id': proposal.id,
            'sequence': start + i + 1,
            'department': r['department'],
            'description': r['description'],
            'current_state': r['current_state'] or False,
            'proposed_solution': r['proposed_solution'] or False,
            'color_hint': r['color'] or False,
            'module_hint': r['module_hint'] or False,
            'quote_note': r['quote_note'] or False,
            'source': 'import',
        } for i, r in enumerate(rows)])
        proposal.message_post(body=_('匯入售前痛點 %(n)s 筆（%(f)s）',
                                     n=len(rows), f=self.filename or 'xlsx'))
        return {'type': 'ir.actions.act_window_close'}
