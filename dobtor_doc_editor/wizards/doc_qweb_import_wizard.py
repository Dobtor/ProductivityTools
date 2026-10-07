from odoo import models, fields, api
from odoo.exceptions import UserError


class DocQwebImportWizard(models.TransientModel):
    """從原生 QWeb 報表產生文件範本。

    刻意做成「產生一張草稿 + 一份待辦清單」而不是「一鍵完成」：
    轉換器只轉版面與結構，沒把握的地方一律標成待辦。轉錯的版面使用者看得見，
    轉錯的綁定（印出別的欄位的值）看不見——所以寧可標成待辦。
    """
    _name = 'doc.qweb.import.wizard'
    _description = 'QWeb 報表匯入精靈'

    report_id = fields.Many2one(
        'ir.actions.report', string='原生報表', required=True,
        domain="[('report_type', 'in', ['qweb-pdf', 'qweb-html'])]",
        help='要轉換的 Odoo 原生報表。轉換不會修改原報表。',
    )
    report_model = fields.Char(
        related='report_id.model', string='適用模型', readonly=True,
    )
    template_name = fields.Char(string='新範本名稱')
    page_format = fields.Selection(
        [('A4', 'A4'), ('A4_landscape', 'A4 橫向'), ('Letter', 'Letter')],
        string='紙張', default='A4', required=True,
    )
    create_binding = fields.Boolean(
        string='同時建立報表綁定', default=False,
        help='勾選後會建立 doc.report 綁定，列印該報表時改用新範本。'
             '預設不勾：轉換結果應該先人工檢查過再上線。',
    )
    notes = fields.Text(string='待辦清單', readonly=True)
    template_id = fields.Many2one(
        'doc.template', string='產生的範本', readonly=True,
    )
    state = fields.Selection(
        [('draft', '設定'), ('done', '完成')], default='draft',
    )

    @api.onchange('report_id')
    def _onchange_report_id(self):
        if self.report_id and not self.template_name:
            self.template_name = '%s（自 QWeb 轉換）' % self.report_id.name

    def action_convert(self):
        self.ensure_one()
        if not self.report_id.model:
            raise UserError('這個報表沒有指定模型，無法轉換。')

        result = self.env['doc.qweb.converter'].convert_report(
            self.report_id, page_format=self.page_format,
        )
        if not result.get('content_json'):
            raise UserError(
                '轉換失敗：\n%s' % '\n'.join(result.get('notes') or ['未知原因'])
            )

        template = self.env['doc.template'].create({
            'name': self.template_name or self.report_id.name,
            'role': 'content',
            'page_format': self.page_format,
            'model_id': self.env['ir.model']._get(self.report_id.model).id,
            'content_json': result['content_json'],
            'description': '由原生報表「%s」轉換產生。請依待辦清單逐項確認。'
                           % self.report_id.name,
        })

        stats = result.get('stats') or {}
        lines = [
            '── 轉換統計 ──',
            '變數藥丸 %d 個（其中 %d 個待確認）'
            % (stats.get('pill', 0), stats.get('unbound', 0)),
            '表格 %d、重複列 %d、條件 %d、圖片 %d、稅額彙總 %d'
            % (stats.get('table', 0), stats.get('repeat', 0),
               stats.get('condition', 0), stats.get('image', 0),
               stats.get('taxTotals', 0)),
            '',
        ]
        if result.get('notes'):
            lines.append('── 待辦（請逐項確認）──')
            lines += ['%d. %s' % (i, n)
                      for i, n in enumerate(result['notes'], 1)]
        else:
            lines.append('沒有待辦項目。仍建議印一張比對原生輸出。')

        binding = self.env['doc.report']
        if self.create_binding:
            binding = self.env['doc.report'].create({
                'name': '%s（轉換）' % self.report_id.name,
                'template_id': template.id,
                'report_id': self.report_id.id,
                'active': False,
            })
            lines += [
                '',
                '已建立報表綁定但**停用**中。確認範本沒問題後再啟用，'
                '否則所有使用者立刻會印到未檢查的版本。',
            ]

        self.write({
            'template_id': template.id,
            'notes': '\n'.join(lines),
            'state': 'done',
        })
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_open_template(self):
        self.ensure_one()
        if not self.template_id:
            raise UserError('還沒有產生範本。')
        return self.template_id.action_open_editor()
