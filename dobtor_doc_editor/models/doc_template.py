import html as html_mod

from odoo import models, fields, api
from odoo.exceptions import UserError


class DocTemplate(models.Model):
    _name = 'doc.template'
    _description = '文件範本'
    _inherit = ['doc.render.mixin']
    _order = 'name asc'

    name = fields.Char(string='範本名稱', required=True)
    content_html = fields.Html(
        string='範本內容',
        sanitize=False,
        sanitize_attributes=False,
    )
    model_id = fields.Many2one(
        'ir.model',
        string='適用模型',
        ondelete='set null',
        help='此範本適用的 Odoo 模型，留空表示通用範本',
    )
    category = fields.Selection([
        ('general', '一般'),
        ('contract', '合約'),
        ('report', '報告'),
        ('letter', '信函'),
        ('other', '其他'),
    ], string='分類', default='general')
    description = fields.Text(string='說明')
    active = fields.Boolean(string='啟用', default=True)
    page_format = fields.Selection([
        ('A4', 'A4'),
        ('A3', 'A3'),
        ('A5', 'A5'),
        ('letter', 'Letter'),
        ('legal', 'Legal'),
    ], string='預設頁面格式', default='A4')
    field_aliases = fields.Json(
        string='欄位別名對映',
        default=dict,
        help=(
            '範本級全域 alias 對映。所有使用此範本的 doc.document 預覽渲染時都會繼承。'
            'Key 支援兩種形式：'
            '1) 中文 token（如「工程名稱」），文件內寫 《工程名稱》 會被替換。'
            '2) 純變數名（如「project_name」），文件內寫 {{ project_name }} 會被替換。'
        ),
    )

    # Phase 8 Template UI Builder（ADR-022）
    signer_ids = fields.One2many(
        'doc.template.signer',
        'template_id',
        string='簽約人角色',
    )
    field_ids = fields.One2many(
        'doc.template.field',
        'template_id',
        string='範本欄位',
    )
    signer_count = fields.Integer(string='簽約人數', compute='_compute_phase8_counts')
    field_count = fields.Integer(string='欄位數', compute='_compute_phase8_counts')

    def _compute_phase8_counts(self):
        for rec in self:
            rec.signer_count = len(rec.signer_ids)
            rec.field_count = len(rec.field_ids)

    # ─── L2-v2 範本級 alias 管理（form view 用）──────────────────────
    alias_count = fields.Integer(
        string='對映數',
        compute='_compute_alias_count',
        help='範本目前定義的中文/變數名 alias 對映總數',
    )
    field_aliases_display = fields.Html(
        string='對映預覽',
        compute='_compute_field_aliases_display',
        sanitize=False,
        sanitize_attributes=False,
        store=False,
    )

    @api.depends('field_aliases')
    def _compute_alias_count(self):
        for rec in self:
            rec.alias_count = len(rec.field_aliases or {})

    @api.depends('field_aliases')
    def _compute_field_aliases_display(self):
        for rec in self:
            aliases = rec.field_aliases or {}
            if not aliases:
                rec.field_aliases_display = (
                    '<div style="padding:16px;background:#fef9c3;border:1px solid #fde047;'
                    'border-radius:6px;color:#713f12;text-align:center">'
                    '<i class="fa fa-info-circle me-2"/>'
                    '尚未建立任何對映。按下方「從關聯模型自動生成」開始'
                    '</div>'
                )
                continue
            # 分組：中文 token vs 變數名
            import re as _re
            token_rows, var_rows = [], []
            for key in sorted(aliases.keys(), key=lambda k: (not _re.match(r'^[A-Za-z_]\w*$', k), k)):
                val = aliases[key]
                row = (
                    '<tr>'
                    f'<td style="padding:4px 8px;border-bottom:1px solid #f1f5f9">'
                    f'<code style="background:#e3f2fd;color:#1565c0;padding:1px 6px;border-radius:3px">'
                    f'{html_mod.escape(key)}</code></td>'
                    f'<td style="padding:4px 8px;border-bottom:1px solid #f1f5f9;color:#475569">→</td>'
                    f'<td style="padding:4px 8px;border-bottom:1px solid #f1f5f9;font-family:monospace;font-size:12px">'
                    f'{html_mod.escape(val)}</td>'
                    '</tr>'
                )
                if _re.match(r'^[A-Za-z_]\w*$', key):
                    var_rows.append(row)
                else:
                    token_rows.append(row)

            def _section(title, rows):
                if not rows:
                    return ''
                return (
                    f'<h6 style="margin:12px 0 6px;color:#475569">{title}（{len(rows)}）</h6>'
                    '<table style="width:100%;border-collapse:collapse;font-size:13px">'
                    + ''.join(rows) +
                    '</table>'
                )

            rec.field_aliases_display = (
                f'<div style="padding:8px">'
                f'{_section("中文 Token（《xxx》 形式）", token_rows)}'
                f'{_section("變數名（{{ xxx }} 形式）", var_rows)}'
                '</div>'
            )

    def action_auto_init_aliases(self):
        """從 self.model_id 自動補上欄位對映（保留既有）。"""
        self.ensure_one()
        if not self.model_id:
            raise UserError('請先設定「適用模型」後再使用此功能。')
        result = self.init_aliases_from_model_for(self.model_id.model, overwrite=False)
        if not result.get('success'):
            raise UserError(result.get('error') or '自動生成失敗')
        added = len(result.get('added') or [])
        skipped = len(result.get('skipped') or [])
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': '自動生成完成',
                'message': f'已新增 {added} 個對映、跳過 {skipped} 個既有對映。',
                'type': 'success',
                'sticky': False,
            },
        }

    def action_clear_aliases(self):
        """清空所有對映（需確認）。"""
        self.ensure_one()
        self.field_aliases = {}
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': '已清空',
                'message': '所有對映已移除。',
                'type': 'warning',
                'sticky': False,
            },
        }

    # ─── Selection 欄位速查 ────────────────────────────────────────────
    selection_fields_display = fields.Html(
        string='Selection 欄位速查',
        compute='_compute_selection_fields_display',
        sanitize=False,
        sanitize_attributes=False,
        store=False,
    )

    @api.depends('model_id')
    def _compute_selection_fields_display(self):
        for rec in self:
            if not rec.model_id:
                rec.selection_fields_display = (
                    '<div style="padding:16px;background:#f8fafc;border:1px dashed #cbd5e1;'
                    'border-radius:6px;color:#64748b;text-align:center">'
                    '請先設定「適用模型」以列出 Selection 欄位。</div>'
                )
                continue
            model_name = rec.model_id.model
            if model_name not in rec.env:
                rec.selection_fields_display = (
                    f'<div style="color:#dc2626">模型「{html_mod.escape(model_name)}」未載入</div>'
                )
                continue
            try:
                Model = rec.env[model_name]
                rows = []
                # ir.model.fields 比 _fields 慢但能拿到 field_description（中文 label）
                selection_recs = rec.env['ir.model.fields'].sudo().search([
                    ('model', '=', model_name),
                    ('ttype', '=', 'selection'),
                ], order='field_description asc')
                for f in selection_recs:
                    label = html_mod.escape(f.field_description or '')
                    name = html_mod.escape(f.name)
                    # 拿可能值（透過 model field 取 _description_selection）
                    options_html = ''
                    try:
                        field = Model._fields.get(f.name)
                        if field:
                            choices = field._description_selection(rec.env)
                            opts = []
                            for val, lab in choices:
                                opts.append(
                                    f'<span style="background:#fef3c7;color:#78350f;'
                                    f'padding:1px 6px;border-radius:3px;margin-right:4px;'
                                    f'font-size:11px;display:inline-block;margin-bottom:2px">'
                                    f'{html_mod.escape(str(val))} = {html_mod.escape(str(lab))}'
                                    '</span>'
                                )
                            options_html = ''.join(opts) or '<em style="color:#94a3b8">（無選項）</em>'
                    except Exception as exc:
                        options_html = f'<em style="color:#dc2626">無法取得選項：{html_mod.escape(str(exc))}</em>'

                    rows.append(
                        '<tr>'
                        f'<td style="padding:6px 8px;border-bottom:1px solid #f1f5f9;'
                        f'vertical-align:top;white-space:nowrap">'
                        f'<strong>{label}</strong><br/>'
                        f'<code style="font-size:11px;color:#64748b">{name}</code>'
                        '</td>'
                        f'<td style="padding:6px 8px;border-bottom:1px solid #f1f5f9">'
                        f'{options_html}'
                        '</td>'
                        '</tr>'
                    )
                if not rows:
                    rec.selection_fields_display = (
                        f'<div style="padding:16px;background:#f8fafc;border:1px dashed #cbd5e1;'
                        f'border-radius:6px;color:#64748b">'
                        f'模型「{html_mod.escape(model_name)}」沒有 Selection 欄位。</div>'
                    )
                else:
                    rec.selection_fields_display = (
                        f'<div style="margin-bottom:8px;font-size:12px;color:#64748b">'
                        f'模型 <code>{html_mod.escape(model_name)}</code> 共 {len(rows)} 個 Selection 欄位。'
                        f'渲染時可用 <code>selection_label(\'欄位名\')</code> 取得中文 label。</div>'
                        '<table style="width:100%;border-collapse:collapse;font-size:13px">'
                        '<thead><tr style="background:#f1f5f9">'
                        '<th style="padding:6px 8px;text-align:left;width:25%">欄位</th>'
                        '<th style="padding:6px 8px;text-align:left">可能值</th>'
                        '</tr></thead>'
                        '<tbody>'
                        + ''.join(rows) +
                        '</tbody></table>'
                    )
            except Exception as exc:
                rec.selection_fields_display = (
                    f'<div style="color:#dc2626;padding:12px">'
                    f'掃描失敗：{html_mod.escape(str(exc))}</div>'
                )
