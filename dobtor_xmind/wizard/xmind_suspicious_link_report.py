# -*- coding: utf-8 -*-
from odoo import models, fields, api


class XMindSuspiciousLinkReport(models.TransientModel):
    """「可疑關聯檢查」：唯讀列出看起來連錯的心智圖↔專案（永不自動修正）。"""
    _name = 'xmind.suspicious.link.report'
    _description = 'Suspicious Mind Map Project Links'

    line_ids = fields.One2many('xmind.suspicious.link.line', 'report_id', string='Findings',
                               readonly=True)
    line_count = fields.Integer(compute='_compute_line_count', string='Findings Count')

    @api.depends('line_ids')
    def _compute_line_count(self):
        for rec in self:
            rec.line_count = len(rec.line_ids)

    @api.model
    def action_generate(self):
        rows = self.env['xmind.workbook'].get_suspicious_links_report()
        report = self.create({'line_ids': [(0, 0, {
            'workbook_id': row['workbook_id'],
            'project_name': row['project_name'],
            'reason': row['reason'],
        }) for row in rows]})
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._('Suspicious Project Links'),
            'res_model': self._name,
            'res_id': report.id,
            'view_mode': 'form',
            'target': 'current',
        }


class XMindSuspiciousLinkLine(models.TransientModel):
    _name = 'xmind.suspicious.link.line'
    _description = 'Suspicious Mind Map Project Link'

    report_id = fields.Many2one('xmind.suspicious.link.report', ondelete='cascade', required=True)
    workbook_id = fields.Many2one('xmind.workbook', string='Mind Map', readonly=True)
    project_name = fields.Char('Project', readonly=True)
    reason = fields.Char('Reason', readonly=True)

    def action_open_workbook(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'xmind.workbook',
            'res_id': self.workbook_id.id,
            'view_mode': 'form',
            'target': 'current',
        }
