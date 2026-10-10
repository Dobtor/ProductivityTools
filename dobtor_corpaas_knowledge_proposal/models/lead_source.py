# -*- coding: utf-8 -*-
"""商機的「會議與筆記」：選哪些會議記錄／筆記，作為建議書的參考資料來源。

★ 用連結表而不是單純 M2M：同一份筆記在這個商機的角色不同（客戶提供／內部討論／補充），
  內部討論預設不進報價基礎（可能含底價、成本），要不要引用、AI 可不可讀，都是逐筆的決定。
★ 不放寬 `note.note` 的讀取規則（使用者只能看自己的筆記）：連結時把標題與日期存在連結列，
  商機負責人即使看不到筆記本文，也看得到「有這份來源」。能不能點開仍由筆記自己的規則決定。
★ 內容指紋：筆記之後被改過，報價基礎那一列會標示「內容已更新」，提醒新版要重看。
"""
import hashlib

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import html2plaintext

ROLES = [('customer', '客戶提供'), ('internal', '內部討論'), ('supplement', '補充')]


class KnowledgeLeadSource(models.Model):
    _name = 'corpaas.knowledge.lead_source'
    _description = '商機的會議／筆記來源'
    _order = 'lead_id, sequence, id'

    lead_id = fields.Many2one('crm.lead', required=True, ondelete='cascade', index=True)
    sequence = fields.Integer(default=10)
    note_id = fields.Many2one('note.note', string='會議／筆記', required=True,
                              ondelete='cascade', index=True)
    note_title = fields.Char(string='標題', readonly=True)
    note_date = fields.Date(string='日期', readonly=True)
    role = fields.Selection(ROLES, string='角色', default='customer', required=True)
    include_in_basis = fields.Boolean(
        string='列入報價基礎', default=True,
        help='勾選的來源會在建議書的「報價基礎」留一列（只放標題與日期，不放內容）。')
    ai_readable = fields.Boolean(
        string='AI 可讀', default=True,
        help='勾選的來源，AI 萃取痛點時才會讀內容；「內部討論」預設不勾。'
             '★ AI 讀取不受筆記「只能看自己的」規則限制：只要有人連結並勾選，就等於授權 AI 讀。')
    remark = fields.Char(string='備註')

    _sql_constraints = [
        ('lead_note_uniq', 'unique(lead_id, note_id)', '這份筆記已經連到這個商機了。')]

    @api.model
    def _note_fingerprint(self, note):
        """筆記內容的雜湊。★ 用 sudo 只為了算雜湊，內容不外流。"""
        text = html2plaintext(note.sudo().memo or '') if note else ''
        return hashlib.sha1(' '.join(text.split()).encode('utf-8')).hexdigest()[:16]

    @api.model
    def _note_date(self, note):
        note = note.sudo()
        events = note.calendar_event_ids.filtered('start').sorted('start')
        stamp = events[:1].start or note.create_date
        return fields.Date.to_date(stamp) if stamp else False

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            note = self.env['note.note'].browse(vals.get('note_id'))
            if note:
                vals.setdefault('note_title', note.sudo().name)
                vals.setdefault('note_date', self._note_date(note))
                internal = vals.get('role', 'customer') == 'internal'
                vals.setdefault('include_in_basis', not internal)
                vals.setdefault('ai_readable', not internal)
        return super().create(vals_list)

    @api.onchange('role')
    def _onchange_role(self):
        self.include_in_basis = self.ai_readable = self.role != 'internal'

    MAX_NOTE_CHARS = 6000
    MAX_TOTAL_CHARS = 20000

    def _ai_texts(self):
        """AI 可讀的來源內容：[(標題, 純文字)]，單篇與總量都截斷，免得燒預算。"""
        out, total = [], 0
        for src in self.filtered('ai_readable'):
            text = ' '.join(html2plaintext(src.note_id.sudo().memo or '').split())
            text = text[:self.MAX_NOTE_CHARS]
            if not text or total + len(text) > self.MAX_TOTAL_CHARS:
                continue
            total += len(text)
            out.append((src.note_title or src.note_id.sudo().name, text))
        return out

    def _refresh_titles(self):
        """筆記改名後同步標題；回傳 {舊標題: 新標題}（報價基礎列沿用舊標題的才跟著改）。"""
        changed = {}
        for src in self:
            new = src.note_id.sudo().name
            if new and new != src.note_title:
                changed[(src.note_id.id, src.note_title)] = new
                src.note_title = new
        return changed

    def action_open_note(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'res_model': 'note.note',
                'res_id': self.note_id.id, 'view_mode': 'form', 'target': 'current'}


class CrmLeadSource(models.Model):
    _inherit = 'crm.lead'

    knowledge_source_ids = fields.One2many('corpaas.knowledge.lead_source', 'lead_id',
                                           string='會議與筆記')

    def action_pick_knowledge_sources(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': _('選擇會議與筆記'),
                'res_model': 'corpaas.knowledge.lead_source.wizard', 'view_mode': 'form',
                'target': 'new', 'context': {'default_lead_id': self.id}}

    def _knowledge_candidate_notes(self):
        """商機可能相關的筆記：行事曆事件掛在這個商機上的會議記錄。"""
        self.ensure_one()
        events = self.env['calendar.event'].search([('opportunity_id', '=', self.id)])
        return self.env['note.note'].search([('calendar_event_ids', 'in', events.ids)]) \
            if events else self.env['note.note']


class LeadSourceWizard(models.TransientModel):
    _name = 'corpaas.knowledge.lead_source.wizard'
    _description = '選擇會議與筆記'

    lead_id = fields.Many2one('crm.lead', required=True)
    note_ids = fields.Many2many('note.note', string='會議／筆記')
    role = fields.Selection(ROLES, string='角色', default='customer', required=True)

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        lead = self.env['crm.lead'].browse(res.get('lead_id') or
                                           self.env.context.get('default_lead_id'))
        if lead and 'note_ids' in fields_list:
            linked = lead.knowledge_source_ids.note_id
            res['note_ids'] = [(6, 0, (lead._knowledge_candidate_notes() - linked).ids)]
        return res

    def action_confirm(self):
        self.ensure_one()
        if not self.note_ids:
            raise UserError(_('請至少選一份會議記錄或筆記。'))
        linked = self.lead_id.knowledge_source_ids.note_id
        self.env['corpaas.knowledge.lead_source'].create([
            {'lead_id': self.lead_id.id, 'note_id': n.id, 'role': self.role}
            for n in self.note_ids - linked])
        return {'type': 'ir.actions.act_window_close'}
