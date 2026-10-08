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

    # 從報表（或 qweb 範本）那邊帶進來的候選限縮。
    # 從 view 反查報表時可能比到好幾張，那時不替使用者挑，只把下拉縮小。
    candidate_report_ids = fields.Many2many(
        'ir.actions.report', string='候選報表',
        compute='_compute_candidate_report_ids',
        help='從 QWeb 範本進來時的候選清單；留空＝不限縮。',
    )
    multi_warning = fields.Integer(
        string='選了幾張', compute='_compute_candidate_report_ids')

    @api.depends_context('doc_candidate_report_ids', 'doc_convert_multi_warning')
    def _compute_candidate_report_ids(self):
        ids = self.env.context.get('doc_candidate_report_ids') or []
        count = self.env.context.get('doc_convert_multi_warning') or 0
        for rec in self:
            rec.candidate_report_ids = [(6, 0, list(ids))]
            rec.multi_warning = count

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
    sample_res_id = fields.Integer(
        string='試算用記錄 ID', default=0,
        help='留 0＝自動挑一筆最新的。轉換後會用這筆記錄把每個變數試算一遍，'
             '算不出來的會標成待確認。',
    )
    attach_layout = fields.Boolean(
        string='自動掛上外框範本', default=True,
        help='原生報表的頁首頁尾（公司 logo、公司資訊、頁碼）對所有報表都一樣，'
             '所以交給共用的外框範本，不複製進每一張範本。',
    )
    layout_id = fields.Many2one(
        'doc.template', string='使用的外框', readonly=True,
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

        sample = self._pick_sample()
        result = self.env['doc.qweb.converter'].convert_report(
            self.report_id, page_format=self.page_format,
            validate_with=sample,
        )
        if not result.get('content_json'):
            raise UserError(
                '轉換失敗：\n%s' % '\n'.join(result.get('notes') or ['未知原因'])
            )

        layout = self.env['doc.template']
        if self.attach_layout and result.get('needs_layout'):
            # 同一張外框給所有轉換出來的範本共用——每張各建一份的話，
            # 公司資訊又散回 N 份，外框存在的意義就沒了
            layout = self.env['doc.template'].find_or_create_layout()

        template = self.env['doc.template'].create({
            'name': self.template_name or self.report_id.name,
            'role': 'content',
            'layout_id': layout.id or False,
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
        ]
        if sample:
            lines.append(
                '以「%s」試算：%d 個變數算得出來、%d 個算不出來'
                % (sample.display_name, stats.get('validated', 0),
                   stats.get('validate_failed', 0))
            )
        else:
            lines.append(
                '沒有樣本記錄可試算（該模型還沒有資料）——'
                '所有自動改寫的表達式都未經驗證。'
            )
        if layout:
            lines.append(
                '頁首頁尾交給外框範本「%s」（公司 logo／公司資訊／頁碼）。'
                '紙張與邊距也由外框決定。' % layout.name
            )
        elif result.get('needs_layout'):
            lines.append(
                '原生報表有外框（external_layout），但沒有掛外框範本'
                '——頁首頁尾目前是空的，公司 logo 與頁碼不會印出來。'
            )
        lines.append('')
        # 待辦分三段：平鋪幾十條的實務結果是使用者整段跳過。
        # 「要改的」擺最前面，「只是告知的」擺最後。
        by_level = result.get('notes_by_level') or {}
        sections = (
            ('blocker', '── 必須處理（內容或版面會與原生不同）──'),
            ('check', '── 請確認（已自動改寫）──'),
            ('info', '── 告知（不需動作）──'),
        )
        if result.get('notes'):
            shown = 0
            for key, title in sections:
                items = by_level.get(key) or []
                if not items:
                    continue
                lines.append(title)
                lines += ['%d. %s' % (i, n) for i, n in enumerate(items, 1)]
                lines.append('')
                shown += len(items)
            if shown < len(result['notes']):
                # 分級表沒涵蓋到的（舊版結果）還是要印出來，不可以吞掉
                rest = [n for n in result['notes']
                        if all(n not in (by_level.get(k) or [])
                               for k, _t in sections)]
                lines.append('── 其他 ──')
                lines += ['%d. %s' % (i, n) for i, n in enumerate(rest, 1)]
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
            'layout_id': layout.id or False,
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

    def _pick_sample(self):
        """挑一筆樣本記錄給試算用。取不到回空 recordset（略過試算）。

        指定 ID 時以它為準；沒指定就挑最新的一筆。刻意不挑「第一筆」——
        最新的那筆比較可能有完整資料（有明細、有付款條件），空殼記錄
        試算起來什麼都是空的，驗不出東西。
        """
        self.ensure_one()
        model = self.report_id.model
        if not model or model not in self.env:
            return self.env['doc.template'].browse()
        Model = self.env[model]
        if self.sample_res_id:
            rec = Model.browse(self.sample_res_id).exists()
            if rec:
                return rec
        try:
            return Model.search([], order='id desc', limit=1)
        except Exception:
            return Model.browse()

    def action_open_template(self):
        self.ensure_one()
        if not self.template_id:
            raise UserError('還沒有產生範本。')
        return self.template_id.action_open_editor()
