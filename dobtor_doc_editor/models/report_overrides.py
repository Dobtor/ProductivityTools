import io
import logging

from odoo import models
from odoo.tools.pdf import merge_pdf


_logger = logging.getLogger(__name__)


class IrActionsReport(models.Model):
    _inherit = 'ir.actions.report'

    def _build_wkhtmltopdf_args(
        self, paperformat_id, landscape,
        specific_paperformat_args=None, set_viewport_size=False
    ):
        """擴充 specific_paperformat_args 支援 data-report-margin-left/right。

        Odoo 18 原始實作（ir_actions_report.py 第 344、351 行）將 --margin-left/right
        硬寫為 paperformat_id.margin_left/right，忽略 specific_paperformat_args 中的
        data-report-margin-left/right 鍵值。
        本覆寫在 super() 執行後，將 args 清單中對應的值替換為指定值。
        """
        args = super()._build_wkhtmltopdf_args(
            paperformat_id, landscape, specific_paperformat_args, set_viewport_size
        )
        if not specific_paperformat_args:
            return args

        for side in ('left', 'right'):
            key = f'data-report-margin-{side}'
            cli_flag = f'--margin-{side}'
            if key in specific_paperformat_args and cli_flag in args:
                idx = args.index(cli_flag)
                args[idx + 1] = str(specific_paperformat_args[key])

        # footer-spacing：Odoo 只讀 data-report-header-spacing
        # （ir_actions_report.py:339），沒有對應的 footer 版本。頁尾間距沒接上
        # 的話，頁尾一高就壓到本文最後一行——而那只有在內容剛好印滿一頁時
        # 才看得出來，最難追。
        foot_key = 'data-report-footer-spacing'
        if foot_key in specific_paperformat_args:
            value = str(specific_paperformat_args[foot_key])
            if '--footer-spacing' in args:
                args[args.index('--footer-spacing') + 1] = value
            else:
                args.extend(['--footer-spacing', value])
        return args

    # ══════════════════════════════════════════════════════════════════
    # 報表引擎：用 doc.template 取代 QWeb 產生報表內容
    #
    # 攔截點選在 _render_qweb_html 而非 _render_qweb_pdf_prepare_streams，
    # 也不是 selection_add 一個新的 report_type。三個理由：
    #
    #   1. _render_qweb_pdf_prepare_streams（ir_actions_report.py:860）就是從
    #      _render_qweb_html 取得 HTML 的。攔在 HTML 這一層，attachment 重用、
    #      wkhtmltopdf 呼叫、多筆 PDF 切割與合併、paperformat 全部不必碰。
    #   2. 自訂 report_type 會被 web client 擋下——action_service.js:1333 對未知
    #      型別只 console.error。要能用必須同時註冊 JS handler，而且模組一停用
    #      所有報表按鈕就全壞。保持 qweb-pdf 則前端零改動、停用時自動回到原生。
    #   3. _render_qweb_html 同時是 report_type='qweb-html'（瀏覽器預覽）的入口
    #      （ir_actions_report.py:1009），所以預覽也一併接上，不必另外處理。
    #
    # 查不到綁定時一律 super()：定案決策一是「逐一綁定」，與原生 QWeb 共存。
    # ══════════════════════════════════════════════════════════════════

    def _render_qweb_html(self, report_ref, docids, data=None):
        report = self._get_report(report_ref)
        doc_report = self.env['doc.report']._resolve_for_report(report)
        if not doc_report:
            return super()._render_qweb_html(report_ref, docids, data=data)

        if isinstance(docids, int):
            docids = [docids]
        if not docids or not report.model:
            # 沒有記錄可渲染（例如空選取）→ 交回原生，由它處理既有的邊界行為
            return super()._render_qweb_html(report_ref, docids, data=data)

        records = self.env[report.model].browse(docids)
        html, frozen_trees = doc_report._build_report_html(records)

        # 定案決策二：預設不留存。開啟時每筆記錄留一筆 doc.output。
        #
        # 只在「真的在產生 PDF」時留存：_render_qweb_pdf 會先
        # data.setdefault('report_type', 'pdf')（ir_actions_report.py:1019）才一路
        # 呼進這裡，而瀏覽器預覽（report_type='qweb-html'）不會帶這個值。
        # 不分辨的話，使用者「先預覽再列印」同一張單據會留下兩筆紀錄。
        is_pdf_run = (data or {}).get('report_type') == 'pdf'
        if doc_report.persist_output and is_pdf_run:
            Output = self.env['doc.output']
            for record in records:
                try:
                    Output._record_output(
                        doc_report, record, frozen_trees.get(record.id),
                    )
                except Exception as e:
                    # 留存失敗不該讓列印失敗——使用者要的是那張單據
                    _logger.warning(
                        '[doc.report] 留存輸出失敗 %s(%s)：%s',
                        record._name, record.id, e,
                    )
        return html, 'html'

    # ══════════════════════════════════════════════════════════════════
    # 附頁：第二個攔截點，而且只為設了附頁的綁定存在
    #
    # 上面那支刻意攔在 HTML 層，好處是 wkhtmltopdf、attachment、多筆切割
    # 全部不必碰。但「把別的報表或固定 PDF 接在單據後面」在 HTML 層做不到
    # ——HTML 裡沒有 PDF 可接。所以這裡多開一個 PDF 層的攔截點。
    #
    # 選 _render_qweb_pdf_prepare_streams 而不是 _render_qweb_pdf：
    # 前者給的是 {res_id: {'stream': …}}，一筆記錄一份。接的是「這張單據的
    # 附頁」，多筆列印時每張後面都要有自己那一份；在 _render_qweb_pdf 之後
    # 動手只剩一份合併好的 PDF，附頁只能全部堆在最後面。
    #
    # 沒設附頁時這支等於不存在（第一個 if 就 return super 的結果）。
    # ══════════════════════════════════════════════════════════════════

    def _render_qweb_pdf_prepare_streams(self, report_ref, data, res_ids=None):
        report = self._get_report(report_ref)
        doc_report = self.env['doc.report']._resolve_for_report(report)
        # 要不要進這條路：綁定設了附頁，**或**這個模型自己會提供附頁。
        # 後者用 hasattr 問「模型」而不是逐筆問記錄——列印 80 張單據時
        # 光是為了決定要不要進來就呼叫 80 次業務方法太貴。
        hook = self.env['doc.report']._RECORD_HOOKS['pdfs']
        model_supplies = bool(
            report.model and report.model in self.env
            and hasattr(self.env[report.model], hook))
        appends = doc_report and (
            doc_report.append_report_ids or doc_report.append_attachment_ids
            or model_supplies)
        if not appends or self._context.get('doc_report_no_append'):
            return super()._render_qweb_pdf_prepare_streams(
                report_ref, data, res_ids=res_ids)

        # 重用既有附件的那幾筆要跳過：那份 PDF 是上次產的，**已經含附頁**，
        # 再接一次會變兩份。條件與 Odoo 自己判斷重用的條件一致
        #（ir_actions_report.py:817）。
        reused = set()
        if (report.attachment and report.attachment_use and res_ids
                and not self._context.get('report_pdf_no_attachment')):
            for record in self.env[report.model].browse(res_ids):
                if report.retrieve_attachment(record):
                    reused.add(record.id)

        collected = super()._render_qweb_pdf_prepare_streams(
            report_ref, data, res_ids=res_ids)

        for res_id, entry in (collected or {}).items():
            if not res_id or res_id in reused:
                continue
            stream = (entry or {}).get('stream')
            if not stream:
                continue
            record = self.env[report.model].browse(res_id)
            if not record.exists():
                continue
            extra = doc_report._append_streams_for(record)
            if not extra:
                continue
            try:
                own = stream.getvalue()
                parts = ([own] + extra) if doc_report.append_position == 'after' \
                    else (extra + [own])
                entry['stream'] = io.BytesIO(merge_pdf(parts))
            except Exception as e:
                # 合併失敗就給原本那份。使用者要的是單據本身，少了附頁
                # 看得出來；整張產不出來才是災難。
                _logger.warning(
                    '[doc.report] 附頁合併失敗 %s(%s)，只輸出本體：%s',
                    report.model, res_id, e,
                )
        return collected
