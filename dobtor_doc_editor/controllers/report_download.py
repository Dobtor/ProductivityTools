"""下載檔名：讓 doc.report.filename_pattern 真的生效。

這個欄位一直是**宣告了、表單上也有、但沒有任何程式讀它**——使用者填了檔名
樣式，下載下來還是原生的名字，而且沒有任何訊息。會這樣是因為 Odoo 只在一個
地方決定下載檔名（web/controllers/report.py 的 report_download），它讀的是
報表自己的 print_report_name，沒有留 hook。

為什麼不改 print_report_name：那是**原生報表身上的欄位**。寫進去會讓這張報表
在我們的綁定停用之後也變了名字，違反「原生報表不動、停用就回到原生」。

所以在這裡接：先讓 super() 把回應做好（PDF 內容、錯誤處理、attachment 重用
全部不碰），只在「這張報表有綁定、而且綁定填了 filename_pattern」時改寫
Content-Disposition。算不出來就不改，保留 super() 給的名字——為了一個檔名
讓整個下載失敗是最糟的結果。
"""
import json
import logging

from odoo import http
from odoo.addons.web.controllers.report import ReportController
from odoo.http import content_disposition, request

_logger = logging.getLogger(__name__)

class DocReportDownload(ReportController):

    @http.route()
    def report_download(self, data, context=None, token=None):
        response = super().report_download(data, context=context, token=token)
        try:
            self._doc_rename_download(response, data, context)
        except Exception as e:
            # 改名失敗 → 用原生的名字。使用者要的是那份 PDF。
            _logger.warning('[doc.report] 下載改名失敗，沿用原生檔名：%s', e)
        return response

    def _doc_rename_download(self, response, data, context):
        requestcontent = json.loads(data)
        url, type_ = requestcontent[0], requestcontent[1]
        if type_ not in ('qweb-pdf', 'qweb-text'):
            return
        pattern = '/report/pdf/' if type_ == 'qweb-pdf' else '/report/text/'
        if pattern not in url:
            return
        reportname = url.split(pattern)[1].split('?')[0]
        docids = None
        if '/' in reportname:
            reportname, docids = reportname.split('/', 1)
        if not docids:
            # 沒有記錄就沒有 {{ object }} 可用，樣式必然算不出來
            return

        report = request.env['ir.actions.report']._get_report_from_name(reportname)
        if not report:
            return
        doc_report = request.env['doc.report']._resolve_for_report(report)
        pattern_str = (doc_report.filename_pattern or '').strip() \
            if doc_report else ''
        if not pattern_str:
            return

        ids = [int(x) for x in docids.split(',') if x.strip().isdigit()]
        if len(ids) != 1:
            # 多筆合併成一份：單一記錄的檔名樣式套不上去，交回原生
            return
        record = request.env[report.model].browse(ids)
        if not record.exists():
            return

        name = request.env['doc.render.mixin']._render_filename(
            pattern_str, record)
        if not name:
            return
        extension = 'pdf' if type_ == 'qweb-pdf' else 'txt'
        # 覆寫而不是再 add 一個：header 允許重複，而瀏覽器取的是第一個，
        # super() 已經加過一個了。
        response.headers.pop('Content-Disposition', None)
        response.headers.add(
            'Content-Disposition', content_disposition('%s.%s' % (name, extension)))
