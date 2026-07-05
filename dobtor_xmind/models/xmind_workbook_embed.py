# -*- coding: utf-8 -*-
from odoo import models, fields, api


class XMindWorkbookEmbed(models.Model):
    """Tracks which host records embed a given mind map inside their HTML fields.

    When a user inserts a mind map through the ``/`` power-box of any model's
    rich-text (html) field, the editor registers the association here — the WHOLE
    workbook is linked to the host record (``res_model`` + ``res_id``), not to a
    single topic. The mind map editor's project bar then lists the names of the
    records embedding it ("關聯物件：...").
    """
    _name = 'xmind.workbook.embed'
    _description = 'Mind Map Embed Reference'
    _rec_name = 'res_name'

    # One row per (workbook, host record). NULL res_id rows are exempt from the
    # UNIQUE index (Postgres), which never happens here since res_id is required.
    _sql_constraints = [
        ('workbook_res_uniq', 'unique(workbook_id, res_model, res_id)',
         'This mind map is already linked to that record.'),
    ]

    workbook_id = fields.Many2one(
        'xmind.workbook', string='Mind Map', required=True, ondelete='cascade', index=True)
    res_model = fields.Char('Host Model', required=True, index=True)
    res_id = fields.Integer('Host Record ID', required=True, index=True)
    res_name = fields.Char('Host Record', compute='_compute_res_name')

    @api.depends('res_model', 'res_id')
    def _compute_res_name(self):
        """Resolve the live display name of each host record.

        Computed (not stored) so the shown name always reflects the current DB
        state; falls back gracefully when the model/record is gone or unreadable.
        """
        for rec in self:
            name = False
            model = rec.res_model
            if model and rec.res_id and model in self.env:
                try:
                    target = self.env[model].browse(rec.res_id)
                    if target.exists() and target.has_access('read'):
                        name = target.display_name
                except Exception:
                    name = False
            rec.res_name = name or (f'{rec.res_model},{rec.res_id}' if rec.res_model else False)
