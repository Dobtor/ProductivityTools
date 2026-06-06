# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class NoteSummaryTemplate(models.Model):
    """會議摘要 Prompt 範本

    將原本硬編於 Python 的 SUMMARY_PROMPT_PRESETS 改為資料化，
    讓管理員可客製/新增 prompt 而不需改 code。
    """
    _name = 'note.summary.template'
    _description = 'Meeting Summary Prompt Template'
    _order = 'sequence, id'

    name = fields.Char(
        string='Name',
        required=True,
        translate=True,
    )
    code = fields.Char(
        string='Code',
        required=True,
        help='Unique identifier; used to look up template from legacy selection field.',
    )
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    description = fields.Char(
        string='Description',
        translate=True,
    )
    prompt = fields.Text(
        string='Prompt',
        required=True,
        translate=True,
        help='Use {transcript} placeholder — it will be replaced with the meeting transcript text.',
    )
    is_system = fields.Boolean(
        string='System Template',
        default=False,
        help='System templates are seeded by module; users should duplicate before editing.',
    )

    _sql_constraints = [
        ('code_uniq', 'UNIQUE(code)', 'Template code must be unique.'),
    ]

    @api.constrains('prompt')
    def _check_prompt_placeholder(self):
        for rec in self:
            if rec.prompt and '{transcript}' not in rec.prompt:
                raise ValidationError(_(
                    'Prompt must contain "{transcript}" placeholder.',
                ))

    def copy(self, default=None):
        default = dict(default or {})
        default.setdefault('name', _('%s (Copy)', self.name))
        default.setdefault('code', f'{self.code}_copy')
        default.setdefault('is_system', False)
        return super().copy(default)
