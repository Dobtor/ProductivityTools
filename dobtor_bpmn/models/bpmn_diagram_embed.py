# -*- coding: utf-8 -*-
from odoo import models, fields, api


class BpmnDiagramEmbed(models.Model):
    """Tracks which host records embed a given BPMN/DMN diagram in their HTML fields.

    When a user inserts a diagram through the ``/`` power-box of any model's
    rich-text (html) field, the editor registers the association here — the WHOLE
    diagram is linked to the host record (``res_model`` + ``res_id``). The BPMN
    editor's project bar then lists the names of the records embedding it
    ("關聯物件：...").
    """
    _name = 'bpmn.diagram.embed'
    _description = '流程設計圖嵌入關聯'
    _rec_name = 'res_name'

    # One row per (diagram, host record). NULL res_id rows are exempt from the
    # UNIQUE index (Postgres), which never happens here since res_id is required.
    _sql_constraints = [
        ('diagram_res_uniq', 'unique(diagram_id, res_model, res_id)',
         '此流程設計圖已關聯到該記錄。'),
    ]

    diagram_id = fields.Many2one(
        'bpmn.diagram', string='流程設計圖', required=True,
        ondelete='cascade', index=True)
    res_model = fields.Char('宿主模型', required=True, index=True)
    res_id = fields.Integer('宿主記錄 ID', required=True, index=True)
    res_name = fields.Char('宿主記錄', compute='_compute_res_name')

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
            rec.res_name = name or (
                f'{rec.res_model},{rec.res_id}' if rec.res_model else False)
