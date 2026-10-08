"""把「轉成列印範本」這件事放到使用者已經在看的地方。

轉換器與精靈（doc.qweb.import.wizard）早就做完整件事：轉換 → 建範本
（可選外框與綁定）→ 開編輯器。問題是**只能從選單進去**，而那張表單的第一個
欄位是「報表」——一個有幾百筆的下拉。使用者是在看某一張報表時想到要轉它的，
不是在選單裡想到的。

所以這裡加三個入口，都只是「帶著 report_id 開同一個精靈」：

  1. ir.actions.report 表單的統計按鈕（已接管幾筆綁定 / 轉成列印範本）
  2. 報表清單與表單的齒輪動作（可以一次選幾張）
  3. qweb 範本（ir.ui.view）表單的按鈕——使用者常常是在看範本原始碼時
     才決定要轉；從 view 反查報表的方式見 _doc_candidate_reports()

刻意**不**做成另一條轉換流程：入口多、流程只有一條。精靈改了這三個入口
自動跟著改。
"""
import logging

from odoo import _, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class IrActionsReportEntry(models.Model):
    _inherit = 'ir.actions.report'

    doc_report_ids = fields.One2many(
        'doc.report', 'report_id',
        string='列印範本綁定',
        help='接管這張報表的範本綁定。有一筆以上時依語言／公司決定用哪一筆。',
    )
    doc_report_count = fields.Integer(
        string='綁定筆數', compute='_compute_doc_report_count')

    def _compute_doc_report_count(self):
        # 用 _read_group 而不是逐筆 len()：報表清單一頁 80 筆，逐筆查會是 80 個
        # 查詢。這個欄位會出現在清單的選用欄位裡。
        data = self.env['doc.report']._read_group(
            [('report_id', 'in', self.ids)],
            groupby=['report_id'], aggregates=['__count'])
        mapped = {report.id: count for report, count in data}
        for rec in self:
            rec.doc_report_count = mapped.get(rec.id, 0)

    def action_convert_to_doc_template(self):
        """開啟轉換精靈，報表欄位已填好。

        多選時只帶第一張並說明：轉換要逐張確認待辦清單，批次轉等於把那份
        清單丟掉——而待辦裡有「這一段沒有轉換」這種非看不可的項目。
        """
        if not self:
            raise UserError(_('請先選一張報表。'))
        report = self[:1]
        if report.report_type not in ('qweb-pdf', 'qweb-html'):
            raise UserError(_(
                '只能轉 qweb-pdf / qweb-html 的報表，這一張是「%s」。'
            ) % report.report_type)
        action = self.env['ir.actions.act_window']._for_xml_id(
            'dobtor_doc_editor.action_doc_qweb_import_wizard')
        action['context'] = dict(
            self.env.context,
            default_report_id=report.id,
            default_template_name='%s（自 QWeb 轉換）' % report.name,
        )
        if len(self) > 1:
            action['context']['doc_convert_multi_warning'] = len(self)
        return action

    def action_view_doc_reports(self):
        """看這張報表的綁定（統計按鈕）。"""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('列印範本綁定'),
            'res_model': 'doc.report',
            'view_mode': 'list,form',
            'domain': [('report_id', '=', self.id)],
            'context': {'default_report_id': self.id},
        }


class IrUiViewEntry(models.Model):
    _inherit = 'ir.ui.view'

    def _doc_candidate_reports(self):
        """用這個 qweb 範本的報表（由近到遠三種比法）。

        Odoo 自己的 associated_view() 是反方向（報表 → 範本），而且用
        `name ilike` naive 比對。這裡要的是 範本 → 報表，依序試：

          1. report_name 完全等於這個 view 的完整 XML ID
             （sale.report_saleorder 這種「入口範本」會中）
          2. 去掉 _document 後綴再比
             （sale.report_saleorder_document 的報表是 sale.report_saleorder）
          3. report_name 的最後一段與 view 名稱有共同前綴
             （繼承來的 xxx_inherit_yyy、或模組自己改名過的）

        找不到就回空，呼叫端負責講清楚為什麼——猜一張錯的報表去轉，
        使用者會以為轉換器壞了。
        """
        self.ensure_one()
        Report = self.env['ir.actions.report']
        base = [('report_type', 'in', ('qweb-pdf', 'qweb-html'))]
        xmlid = self.get_external_id().get(self.id) or ''
        if xmlid:
            found = Report.search(base + [('report_name', '=', xmlid)])
            if found:
                return found
            if xmlid.endswith('_document'):
                found = Report.search(
                    base + [('report_name', '=', xmlid[:-len('_document')])])
                if found:
                    return found
        stem = (self.name or '').split('.')[-1]
        for suffix in ('_document', '_inherit'):
            if stem.endswith(suffix):
                stem = stem[:-len(suffix)]
        if len(stem) < 6:
            # 太短的詞幹會比到一堆無關報表（'report'、'label'…）
            return Report.browse()
        return Report.search(base + [('report_name', 'ilike', stem)])

    def action_convert_to_doc_template(self):
        """從 qweb 範本開轉換精靈。"""
        self.ensure_one()
        if self.type != 'qweb':
            raise UserError(_('只有 QWeb 範本可以轉成列印範本。'))
        reports = self._doc_candidate_reports()
        if not reports:
            raise UserError(_(
                '找不到使用這個範本的報表。\n\n'
                '轉換的對象是「報表」而不是「範本」——報表身上才有模型、'
                '紙張格式與列印按鈕的綁定。\n'
                '請改從 設定 → 技術 → 報表 找到那張報表，'
                '按「轉成列印範本」。'
            ))
        action = self.env['ir.actions.act_window']._for_xml_id(
            'dobtor_doc_editor.action_doc_qweb_import_wizard')
        action['context'] = dict(self.env.context)
        if len(reports) == 1:
            action['context'].update(
                default_report_id=reports.id,
                default_template_name='%s（自 QWeb 轉換）' % reports.name,
            )
        else:
            # 比到好幾張：不要替使用者挑。把候選縮進 domain，讓他自己選。
            action['context']['doc_candidate_report_ids'] = reports.ids
        return action
