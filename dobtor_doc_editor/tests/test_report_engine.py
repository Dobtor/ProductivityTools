"""報表引擎（R1-R3）：doc.report 綁定、HTML 結構契約、doc.output 唯讀。

這批測試的重點是 Odoo 報表管線的**結構契約**——我們產生的 HTML 若不符合
ir_actions_report._prepare_html() 的期待，失敗方式是 IndexError 或 UserError，
而不是「版面有點怪」。所以結構比內容更該被釘住。
"""
import json
from unittest.mock import patch

from odoo.exceptions import AccessError, UserError
from odoo.tests.common import TransactionCase, tagged


def _text(value, **kw):
    return dict({'value': value}, **kw)


def _pill(label_text, **meta):
    payload = {'labelText': label_text}
    payload.update(meta)
    return {
        'type': 'label',
        'value': label_text,
        'label': {'backgroundColor': '#e3f2fd'},
        'extension': {'dobtorField': payload},
    }


@tagged('post_install', '-at_install', 'dobtor_doc_editor')
class TestDocReportBinding(TransactionCase):
    """綁定解析：找不到綁定必須讓原生 QWeb 接手。"""

    def setUp(self):
        super().setUp()
        self.partner_model = self.env['ir.model']._get('res.partner')
        self.template = self.env['doc.template'].create({
            'name': '聯絡人卡片',
            'model_id': self.partner_model.id,
            'content_json': json.dumps({
                'main': [_text('客戶：'), _pill('名稱', source='record', path='name')],
            }),
        })
        # 用一個現成的原生報表當綁定對象（任何 qweb-pdf 報表都可以）
        self.report = self.env['ir.actions.report'].search([
            ('report_type', '=', 'qweb-pdf'), ('model', '=', 'res.partner'),
        ], limit=1)
        if not self.report:
            self.report = self.env['ir.actions.report'].create({
                'name': '測試聯絡人報表',
                'model': 'res.partner',
                'report_type': 'qweb-pdf',
                'report_name': 'base.report_partnercontact',
            })

    def test_no_binding_resolves_empty(self):
        """沒有綁定時回空——呼叫端據此 super()，與原生共存（定案決策一）。"""
        self.assertFalse(
            self.env['doc.report']._resolve_for_report(self.report)
        )

    def test_binding_resolves(self):
        binding = self.env['doc.report'].create({
            'name': '聯絡人卡片綁定',
            'template_id': self.template.id,
            'report_id': self.report.id,
        })
        self.assertEqual(
            self.env['doc.report']._resolve_for_report(self.report), binding,
        )

    def test_explicit_lang_beats_fallback(self):
        """有語言專屬定義時，不該被 lang 留空的後備值搶走。"""
        fallback = self.env['doc.report'].create({
            'name': '後備', 'template_id': self.template.id,
            'report_id': self.report.id, 'sequence': 1,
        })
        specific = self.env['doc.report'].create({
            'name': '繁中專屬', 'template_id': self.template.id,
            'report_id': self.report.id, 'lang': 'zh_TW', 'sequence': 99,
        })
        resolved = self.env['doc.report'].with_context(
            lang='zh_TW'
        )._resolve_for_report(self.report)
        self.assertEqual(
            resolved, specific,
            '明確指定語言者應優先於後備值，即使 sequence 較大',
        )
        other = self.env['doc.report'].with_context(
            lang='en_US'
        )._resolve_for_report(self.report)
        self.assertEqual(other, fallback, '非對應語言應落到後備值')

    def test_model_mismatch_is_blocked(self):
        """範本模型與報表模型不一致時必須擋下。

        不擋的話藥丸的欄位路徑對不上來源記錄，求值全部落空——
        而求值失敗是靜默的（回空字串），使用者只會看到一張空白單據。
        """
        other_template = self.env['doc.template'].create({
            'name': '使用者範本',
            'model_id': self.env['ir.model']._get('res.users').id,
        })
        with self.assertRaises(UserError):
            self.env['doc.report'].create({
                'name': '錯誤綁定',
                'template_id': other_template.id,
                'report_id': self.report.id,
            })

    def test_template_without_model_is_allowed(self):
        """通用範本（未指定模型）可綁任何報表。"""
        generic = self.env['doc.template'].create({'name': '通用範本'})
        binding = self.env['doc.report'].create({
            'name': '通用綁定',
            'template_id': generic.id,
            'report_id': self.report.id,
        })
        self.assertTrue(binding.id)


@tagged('post_install', '-at_install', 'dobtor_doc_editor')
class TestReportHtmlContract(TransactionCase):
    """HTML 結構契約——不符合 _prepare_html() 的期待會以例外收場，不是版面變醜。"""

    def setUp(self):
        super().setUp()
        self.partners = self.env['res.partner'].create([
            {'name': '甲客戶'}, {'name': '乙客戶'},
        ])
        self.template = self.env['doc.template'].create({
            'name': '契約範本',
            'model_id': self.env['ir.model']._get('res.partner').id,
            'margin_top': 120, 'margin_left': 80,
            'content_json': json.dumps({
                'header': [_text('頁首文字')],
                'main': [_text('立約人 '), _pill('客戶', source='record', path='name')],
                'footer': [_text('第 1 頁')],
            }),
        })
        report = self.env['ir.actions.report'].create({
            'name': '契約', 'model': 'res.partner', 'report_type': 'qweb-pdf',
            'report_name': 'dobtor_doc_editor.test_contract',
        })
        self.binding = self.env['doc.report'].create({
            'name': '契約綁定',
            'template_id': self.template.id,
            'report_id': report.id,
        })

    def test_html_has_main_element(self):
        """_prepare_html 是 root.xpath('//main')[0]——沒有 <main> 就 IndexError。"""
        html, _ = self.binding._build_report_html(self.partners)
        self.assertIn('<main>', html)

    def test_one_article_per_record_with_oe_attrs(self):
        """每筆記錄一個 div.article 帶 data-oe-model / data-oe-id。

        Odoo 據此把單一 PDF 切回每筆記錄的 stream；report.attachment 開啟且
        id 對不上時會直接 raise UserError。
        """
        html, _ = self.binding._build_report_html(self.partners)
        self.assertEqual(html.count('class="article"'), 2)
        for partner in self.partners:
            self.assertIn('data-oe-model="res.partner"', html)
            self.assertIn('data-oe-id="%s"' % partner.id, html)

    def test_header_footer_emitted_as_odoo_divs(self):
        """頁首頁尾要用 Odoo 認得的 class，才會被抽出來交給 wkhtmltopdf 每頁重複。"""
        html, _ = self.binding._build_report_html(self.partners)
        self.assertIn('class="header"', html)
        self.assertIn('class="footer"', html)

    def test_margins_passed_as_data_report_attrs(self):
        """範本邊距 → 根 <html> 的 data-report-* → specific_paperformat_args。

        定案：範本的版面設定優先於報表 paperformat，因為
        「編輯器裡看到的就是列印結果」是本模組的賣點。
        """
        html, _ = self.binding._build_report_html(self.partners)
        # 120px ≈ 31.8mm、80px ≈ 21.2mm
        self.assertIn('data-report-margin-top="31.8"', html)
        self.assertIn('data-report-margin-left="21.2"', html)

    def test_pills_are_evaluated_and_flattened(self):
        """列印時求值（與 doc.document 的「建立時凍結」語意不同），且不留網底。"""
        html, trees = self.binding._build_report_html(self.partners)
        self.assertIn('甲客戶', html)
        self.assertIn('乙客戶', html)
        self.assertNotIn('#e3f2fd', html, '藥丸網底不該進正式文件（定案決策四）')
        # 回傳的 tree 是凍結後的，供留存使用（定案決策三）
        tree = trees[self.partners[0].id]
        pills = [
            el for el in self.env['doc.render.mixin']._iter_elements(tree)
            if el.get('type') == 'label'
        ]
        self.assertEqual(pills[0]['value'], '甲客戶')
        self.assertTrue(
            pills[0]['extension']['dobtorField'].get('frozenAt'),
            '凍結後要蓋章，否則匯出時會被重複求值',
        )

    def test_template_without_content_json_still_prints(self):
        """範本還沒用編輯器存過時退回舊 alias 渲染，而不是給一張空白紙。"""
        self.template.write({
            'content_json': False,
            'content_html': '<p>舊範本內容</p>',
        })
        html, trees = self.binding._build_report_html(self.partners)
        self.assertIn('舊範本內容', html)
        self.assertIsNone(trees[self.partners[0].id])


@tagged('post_install', '-at_install', 'dobtor_doc_editor')
class TestDocOutput(TransactionCase):
    """輸出紀錄：唯讀、可追溯、有出路。"""

    def setUp(self):
        super().setUp()
        self.partner = self.env['res.partner'].create({'name': '輸出測試客戶'})
        self.template = self.env['doc.template'].create({
            'name': '輸出測試範本',
            'model_id': self.env['ir.model']._get('res.partner').id,
            'content_json': json.dumps({'main': [_text('內容')]}),
        })
        self.template.action_save_version(label='v1')
        report = self.env['ir.actions.report'].create({
            'name': '輸出測試報表', 'model': 'res.partner',
            'report_type': 'qweb-pdf', 'report_name': 'x.y',
        })
        self.binding = self.env['doc.report'].create({
            'name': '輸出測試綁定',
            'template_id': self.template.id,
            'report_id': report.id,
            'persist_output': True,
        })

    def _make_output(self):
        tree = {'main': [_text('凍結內容')]}
        return self.env['doc.output']._record_output(
            self.binding, self.partner, tree,
        )

    def test_records_source_name_and_version(self):
        """res_name 必須存下來：res_id 無法搜尋顯示名稱，且來源可能被刪除。"""
        out = self._make_output()
        self.assertEqual(out.res_name, '輸出測試客戶')
        self.assertEqual(out.res_model, 'res.partner')
        self.assertEqual(out.template_version, self.template.version_number)
        self.assertTrue(out.rendered_at)
        self.assertEqual(out.rendered_by, self.env.user)

    def test_res_name_survives_source_rename(self):
        """來源改名後，輸出紀錄仍回答「當時印的是哪一張」。"""
        out = self._make_output()
        self.partner.name = '改名後的客戶'
        out.invalidate_recordset()
        self.assertEqual(out.res_name, '輸出測試客戶')

    def test_source_exists_flag(self):
        out = self._make_output()
        self.assertTrue(out.source_exists)

    def test_editable_copy_leaves_output_untouched(self):
        """「建立可編輯副本」是唯讀限制的出路，原紀錄不可被改動。"""
        out = self._make_output()
        original_json = out.content_json

        action = out.action_create_editable_copy()
        doc = self.env['doc.document'].browse(action['context']['doc_id'])
        self.assertTrue(doc.exists())
        self.assertEqual(doc.source_output_id, out)
        self.assertEqual(doc.content_json, original_json)
        # 副本的值已凍結，不該在匯出時被重新求值
        self.assertTrue(doc.snapshot_date)
        # 原輸出紀錄完全沒動
        out.invalidate_recordset()
        self.assertEqual(out.content_json, original_json)

    def test_editable_copy_blocked_after_content_purged(self):
        out = self._make_output()
        out.sudo().write({'content_json': False})
        with self.assertRaises(UserError):
            out.action_create_editable_copy()

    def test_docx_export_produces_valid_zip(self):
        """DOCX 是 zip 容器——產出必須是合法 zip，否則 Word 打不開。"""
        import base64
        import zipfile
        import io as _io
        from importlib.util import find_spec
        if not find_spec('docx'):
            self.skipTest('python-docx 未安裝（選用相依）')

        out = self._make_output()
        action = out.action_download_docx()
        self.assertEqual(action['type'], 'ir.actions.act_url')

        att = self.env['ir.attachment'].search(
            [('res_model', '=', 'doc.output'), ('res_id', '=', out.id)], limit=1,
        )
        self.assertTrue(att, '應產生 DOCX 附件')
        self.assertTrue(att.name.endswith('.docx'))
        data = base64.b64decode(att.datas)
        with zipfile.ZipFile(_io.BytesIO(data)) as z:
            names = z.namelist()
        self.assertIn('word/document.xml', names,
                      'DOCX 必須含 word/document.xml，否則不是合法的 Word 檔')

    def test_docx_blocked_after_content_purged(self):
        out = self._make_output()
        out.sudo().write({'content_json': False})
        with self.assertRaises(UserError):
            out.action_download_docx()

    def test_download_without_attachment_raises(self):
        out = self._make_output()
        with self.assertRaises(UserError):
            out.action_download()

    def test_retention_purges_content_but_keeps_record(self):
        """保留政策分兩段清：內容與附件清掉，「誰在何時印了什麼」留著。"""
        from datetime import timedelta
        from odoo import fields as odoo_fields

        out = self._make_output()
        self.binding.retention_days = 7
        out.sudo().write({
            'rendered_at': odoo_fields.Datetime.now() - timedelta(days=30),
        })

        self.env['doc.output']._gc_expired_outputs()
        out.invalidate_recordset()
        self.assertFalse(out.content_json, '逾期內容應被清掉')
        self.assertTrue(out.exists(), '紀錄本身應保留')
        self.assertEqual(out.res_name, '輸出測試客戶')


@tagged('post_install', '-at_install', 'dobtor_doc_editor')
class TestRenderInterception(TransactionCase):
    """攔截行為：有綁定走範本、沒綁定走原生、預覽不留存。"""

    def setUp(self):
        super().setUp()
        self.company = self.env['res.company'].create({
            'name': '攔截測試公司', 'city': '台中市',
        })
        self.template = self.env['doc.template'].create({
            'name': '攔截測試範本',
            'model_id': self.env['ir.model']._get('res.company').id,
            'content_json': json.dumps({
                'main': [_text('公司：'), _pill('名稱', source='record', path='name')],
            }, ensure_ascii=False),
        })
        self.report = self.env['ir.actions.report'].create({
            'name': '攔截測試報表', 'model': 'res.company',
            'report_type': 'qweb-pdf', 'report_name': 'x.intercept_test',
        })

    def _binding(self, **kw):
        vals = {
            'name': '攔截綁定',
            'template_id': self.template.id,
            'report_id': self.report.id,
        }
        vals.update(kw)
        return self.env['doc.report'].create(vals)

    def test_binding_takes_over_rendering(self):
        """有綁定時 _render_qweb_html 回我們的 HTML，且不碰 QWeb。

        report_name 刻意指向不存在的樣板——若攔截失效會以
        'External ID not found' 收場，剛好證明有沒有真的接管。
        """
        self._binding()
        html, rtype = self.report._render_qweb_html(self.report.id, [self.company.id])
        body = html.decode() if isinstance(html, bytes) else str(html)
        self.assertEqual(rtype, 'html')
        self.assertIn('<main>', body)
        self.assertIn('data-oe-id="%s"' % self.company.id, body)
        self.assertIn('攔截測試公司', body, '藥丸應已求值')

    def test_inactive_binding_falls_back_to_native(self):
        """停用綁定後必須回到原生——這是「退回原生只要停用一筆」的保證。"""
        binding = self._binding()
        binding.active = False
        self.env.registry.clear_cache()
        with self.assertRaises(Exception):
            # 原生會去找不存在的 QWeb 樣板 → 例外。有例外就代表沒被我們接管。
            self.report._render_qweb_html(self.report.id, [self.company.id])

    def test_preview_does_not_persist_output(self):
        """瀏覽器預覽不該留存紀錄——否則「先預覽再列印」會留下兩筆。

        判準是 data['report_type'] == 'pdf'（由 _render_qweb_pdf 設定）。
        """
        binding = self._binding(persist_output=True)
        Output = self.env['doc.output']
        before = Output.search_count([('doc_report_id', '=', binding.id)])

        # 預覽：data 沒有 report_type
        self.report._render_qweb_html(self.report.id, [self.company.id])
        self.assertEqual(
            Output.search_count([('doc_report_id', '=', binding.id)]), before,
            '預覽不該留存輸出紀錄',
        )

        # 列印：data 帶 report_type='pdf'
        self.report._render_qweb_html(
            self.report.id, [self.company.id], data={'report_type': 'pdf'},
        )
        self.assertEqual(
            Output.search_count([('doc_report_id', '=', binding.id)]), before + 1,
            '實際列印才留存',
        )


@tagged('post_install', '-at_install', 'dobtor_doc_editor')
class TestDocOutputReadOnly(TransactionCase):
    """唯讀必須在伺服端——只靠前端旗標任何人用 RPC 都能繞過。"""

    def setUp(self):
        super().setUp()
        self.partner = self.env['res.partner'].create({'name': '權限測試'})
        template = self.env['doc.template'].create({'name': '權限測試範本'})
        report = self.env['ir.actions.report'].create({
            'name': 'r', 'model': 'res.partner',
            'report_type': 'qweb-pdf', 'report_name': 'a.b',
        })
        binding = self.env['doc.report'].create({
            'name': 'b', 'template_id': template.id, 'report_id': report.id,
        })
        self.output = self.env['doc.output']._record_output(
            binding, self.partner, {'main': []},
        )
        self.manager = self.env['res.users'].create({
            'name': '文件管理者', 'login': 'doc_mgr_report',
            'groups_id': [(6, 0, [
                self.env.ref('base.group_user').id,
                self.env.ref('dobtor_doc_editor.group_doc_manager').id,
            ])],
        })

    def test_manager_cannot_write_output(self):
        """連管理者都不可寫——能改已發出的單據就失去稽核價值。"""
        with self.assertRaises(AccessError):
            self.output.with_user(self.manager).write({'res_name': '改掉'})

    def test_manager_can_unlink_for_cleanup(self):
        """管理者保留 unlink，供清理用。"""
        self.output.with_user(self.manager).unlink()
        self.assertFalse(self.output.exists())


@tagged('post_install', '-at_install', 'dobtor_doc_editor')
class TestAppendPages(TransactionCase):
    """附頁：把別的報表或固定 PDF 接在這張單據後面。

    真實需求是「這張單據不只我們產的那幾頁」——合約後面接標準條款、
    出貨單後面接 MSDS。以前要列印兩次再自己合併，而人會忘記或接錯版本。

    這批測試不跑 wkhtmltopdf（CI 上不一定有），釘的是取附頁與排序的邏輯，
    以及三個「壞掉時不要連單據一起毀掉」的取捨。
    """

    def setUp(self):
        super().setUp()
        model = self.env['ir.model']._get('res.partner')
        self.template = self.env['doc.template'].create({
            'name': '附頁測試範本',
            'model_id': model.id,
            'content_json': json.dumps({'main': [_text('本體')]}),
        })
        self.report = self.env['ir.actions.report'].create({
            'name': '附頁測試報表', 'model': 'res.partner',
            'report_type': 'qweb-pdf', 'report_name': 'base.report_partnercontact',
        })
        self.binding = self.env['doc.report'].create({
            'name': '附頁測試綁定',
            'template_id': self.template.id,
            'report_id': self.report.id,
        })
        self.partner = self.env['res.partner'].create({'name': '附頁客戶'})

    def _pdf_attachment(self, name, payload=b'%PDF-1.4 fake'):
        import base64
        return self.env['ir.attachment'].create({
            'name': name, 'mimetype': 'application/pdf',
            'datas': base64.b64encode(payload),
        })

    def test_attachments_are_collected_in_order(self):
        a = self._pdf_attachment('條款A.pdf', b'%PDF-A')
        b = self._pdf_attachment('條款B.pdf', b'%PDF-B')
        self.binding.append_attachment_ids = [(6, 0, (a + b).ids)]
        self.assertEqual(
            self.binding._append_streams_for(self.partner),
            [b'%PDF-A', b'%PDF-B'],
        )

    def test_report_with_a_different_model_is_skipped(self):
        """跳過並留 log，不要讓整張單據失敗，也不要拿錯模型去 browse。"""
        other = self.env['ir.actions.report'].create({
            'name': '別的模型的報表', 'model': 'res.users',
            'report_type': 'qweb-pdf', 'report_name': 'base.report_x',
        })
        self.binding.append_report_ids = [(6, 0, other.ids)]
        self.assertEqual(self.binding._append_streams_for(self.partner), [])

    def test_failing_append_report_does_not_break_the_rest(self):
        """附加報表產不出來時，固定 PDF 還是要接上。"""
        broken = self.env['ir.actions.report'].create({
            'name': '壞掉的報表', 'model': 'res.partner',
            'report_type': 'qweb-pdf', 'report_name': 'no.such_template',
        })
        att = self._pdf_attachment('還在.pdf', b'%PDF-OK')
        self.binding.append_report_ids = [(6, 0, broken.ids)]
        self.binding.append_attachment_ids = [(6, 0, att.ids)]
        self.assertEqual(
            self.binding._append_streams_for(self.partner), [b'%PDF-OK'])

    def test_no_appends_means_the_hook_is_inert(self):
        """沒設附頁時那支覆寫等於不存在——不可以多跑一次 PDF 產生。"""
        self.assertFalse(self.binding.append_report_ids)
        self.assertFalse(self.binding.append_attachment_ids)
        self.assertEqual(self.binding._append_streams_for(self.partner), [])

    def test_position_default_is_after(self):
        self.assertEqual(self.binding.append_position, 'after')

    def test_recursion_guard_context_is_set_for_appended_reports(self):
        """附加的報表若自己也綁了附頁並接回來，不擋就會無限互叫。"""
        inner = self.env['ir.actions.report'].create({
            'name': '互相附加', 'model': 'res.partner',
            'report_type': 'qweb-pdf', 'report_name': 'base.report_partnercontact',
        })
        self.binding.append_report_ids = [(6, 0, inner.ids)]
        seen = {}
        original = type(inner)._render_qweb_pdf

        def _spy(report_self, *args, **kwargs):
            seen['flag'] = report_self.env.context.get('doc_report_no_append')
            return (b'%PDF-inner', 'pdf')

        self.patch(type(inner), '_render_qweb_pdf', _spy)
        self.binding._append_streams_for(self.partner)
        self.assertTrue(seen.get('flag'), '少了防遞迴旗標')
        self.assertTrue(callable(original))


@tagged('post_install', '-at_install', 'dobtor_doc_editor')
class TestFilenamePattern(TransactionCase):
    """檔名樣式。

    這個欄位原本是**死的**：宣告了、表單上也有、但沒有任何程式讀它——使用者
    填了下載下來還是原生名字，而且沒有訊息。Odoo 只在 web 的 report_download
    決定檔名，讀報表自己的 print_report_name，沒有留 hook。
    """

    def setUp(self):
        super().setUp()
        self.Mixin = self.env['doc.render.mixin']
        self.partner = self.env['res.partner'].create({'name': '檔名測試客戶'})

    def test_renders_with_the_same_syntax_as_templates(self):
        self.assertEqual(
            self.Mixin._render_filename('報價單-{{ object.name }}', self.partner),
            '報價單-檔名測試客戶')

    def test_slash_becomes_underscore(self):
        """單號含 / 很常見（S00001/2026）。不換掉下載會壞。"""
        self.partner.name = 'S00001/2026'
        self.assertEqual(
            self.Mixin._render_filename('{{ object.name }}', self.partner),
            'S00001_2026')

    def test_windows_reserved_chars_are_replaced(self):
        self.partner.ref = 'a:b*c?d"e<f>g|h'
        self.assertEqual(
            self.Mixin._render_filename('{{ object.ref }}', self.partner),
            'a_b_c_d_e_f_g_h')

    def test_repeated_and_edge_underscores_are_tidied(self):
        self.partner.ref = '//x//'
        self.assertEqual(
            self.Mixin._render_filename('{{ object.ref }}', self.partner), 'x')

    def test_bad_expression_returns_empty_so_caller_keeps_native_name(self):
        """為了一個檔名讓整個下載失敗是最糟的結果。"""
        self.assertEqual(
            self.Mixin._render_filename('{{ object.no_such_field }}',
                                        self.partner), '')
        self.assertEqual(self.Mixin._render_filename('', self.partner), '')
        self.assertEqual(self.Mixin._render_filename('{{ x', self.partner), '')

    def test_empty_result_is_not_a_filename(self):
        self.partner.ref = False
        self.assertEqual(
            self.Mixin._render_filename('{{ object.ref }}', self.partner), '')

    def test_length_is_capped(self):
        """檔案系統上限 255 bytes，中文一個字 3 bytes。"""
        self.partner.ref = '長' * 200
        name = self.Mixin._render_filename('{{ object.ref }}', self.partner)
        self.assertLessEqual(len(name), 80)
        self.assertTrue(name)

    def test_sandbox_still_applies(self):
        """檔名樣式也是使用者可編輯的字串，不可以是提權入口。"""
        self.assertEqual(
            self.Mixin._render_filename(
                "{{ object.env['res.users'].sudo().browse(1).login }}",
                self.partner),
            '')


@tagged('post_install', '-at_install', 'dobtor_doc_editor')
class TestConvertEntryPoints(TransactionCase):
    """「轉成列印範本」的入口。

    轉換器與精靈早就做完整件事，但**只能從選單進去**，而那張表單的第一個欄位
    是一個有幾百筆的下拉。使用者是在看某一張報表時想到要轉它的。
    """

    def setUp(self):
        super().setUp()
        self.report = self.env['ir.actions.report'].create({
            'name': '入口測試報表', 'model': 'res.partner',
            'report_type': 'qweb-pdf',
            'report_name': 'dobtor_doc_editor.entry_probe',
        })

    def test_report_button_opens_the_wizard_prefilled(self):
        action = self.report.action_convert_to_doc_template()
        self.assertEqual(action.get('res_model'), 'doc.qweb.import.wizard')
        self.assertEqual(action['context']['default_report_id'], self.report.id)
        self.assertIn('入口測試報表', action['context']['default_template_name'])

    def test_non_qweb_report_is_refused_with_a_reason(self):
        text = self.env['ir.actions.report'].create({
            'name': '文字報表', 'model': 'res.partner',
            'report_type': 'qweb-text', 'report_name': 'x.y',
        })
        with self.assertRaises(UserError):
            text.action_convert_to_doc_template()

    def test_multi_selection_takes_the_first_and_flags_it(self):
        """批次轉等於把待辦清單丟掉，所以只帶第一張並講清楚。"""
        other = self.env['ir.actions.report'].create({
            'name': '另一張', 'model': 'res.partner',
            'report_type': 'qweb-pdf', 'report_name': 'a.b',
        })
        action = (self.report + other).action_convert_to_doc_template()
        self.assertEqual(action['context']['default_report_id'], self.report.id)
        self.assertEqual(action['context']['doc_convert_multi_warning'], 2)

    def test_binding_count_is_shown_on_the_report(self):
        model = self.env['ir.model']._get('res.partner')
        tmpl = self.env['doc.template'].create({
            'name': '入口測試範本', 'role': 'content',
            'model_id': model.id, 'content_json': json.dumps({'main': []}),
        })
        self.assertEqual(self.report.doc_report_count, 0)
        self.env['doc.report'].create({
            'name': '入口測試綁定', 'template_id': tmpl.id,
            'report_id': self.report.id,
        })
        self.report.invalidate_recordset(['doc_report_count'])
        self.assertEqual(self.report.doc_report_count, 1)
        action = self.report.action_view_doc_reports()
        self.assertEqual(action['res_model'], 'doc.report')

    # ── 從 qweb 範本反查報表 ────────────────────────────────────
    def test_view_finds_the_report_by_exact_xml_id(self):
        sale = self.env.ref('sale.action_report_saleorder', raise_if_not_found=False)
        if not sale:
            self.skipTest('sale 未安裝')
        view = self.env.ref('sale.report_saleorder', raise_if_not_found=False)
        if not view:
            self.skipTest('找不到 sale.report_saleorder 範本')
        self.assertIn(sale, view._doc_candidate_reports())

    def test_view_strips_the_document_suffix(self):
        """sale.report_saleorder_document 的報表是 sale.report_saleorder。"""
        sale = self.env.ref('sale.action_report_saleorder', raise_if_not_found=False)
        doc_view = self.env.ref('sale.report_saleorder_document',
                                raise_if_not_found=False)
        if not (sale and doc_view):
            self.skipTest('sale 未安裝')
        self.assertIn(sale, doc_view._doc_candidate_reports())

    def test_non_qweb_view_is_refused(self):
        view = self.env['ir.ui.view'].search([('type', '=', 'form')], limit=1)
        with self.assertRaises(UserError):
            view.action_convert_to_doc_template()

    def test_unrelated_qweb_view_explains_rather_than_guessing(self):
        """猜一張錯的報表去轉，使用者會以為轉換器壞了。"""
        view = self.env['ir.ui.view'].create({
            'name': 'doc_entry_probe_orphan',
            'type': 'qweb',
            'arch': '<t t-name="x">沒有報表用我</t>',
        })
        self.assertFalse(view._doc_candidate_reports())
        with self.assertRaises(UserError):
            view.action_convert_to_doc_template()

    def test_short_stem_does_not_match_everything(self):
        """太短的詞幹（report、label）會比到一堆無關報表。"""
        view = self.env['ir.ui.view'].create({
            'name': 'label', 'type': 'qweb',
            'arch': '<t t-name="label">x</t>',
        })
        self.assertFalse(view._doc_candidate_reports())


@tagged('post_install', '-at_install', 'dobtor_doc_editor')
class TestRecordLevelReportSettings(TransactionCase):
    """記錄這一側的三個約定方法。

    綁定管的是「這張報表用哪張範本、附哪幾頁」，依報表＋語言＋公司決定。
    但有些事只有**這一筆**知道：這張單要附它自己上傳的檢驗報告、只有這一張
    合約要附條款、這一筆用客戶指定的版面。
    """

    def setUp(self):
        super().setUp()
        self.model = self.env['ir.model']._get('res.partner')
        self.template = self.env['doc.template'].create({
            'name': '綁定的範本', 'role': 'content',
            'model_id': self.model.id,
            'content_json': json.dumps({'main': [_text('綁定範本的本文')]}),
        })
        self.report = self.env['ir.actions.report'].create({
            'name': '逐筆設定測試報表', 'model': 'res.partner',
            'report_type': 'qweb-pdf',
            'report_name': 'dobtor_doc_editor.record_probe',
        })
        self.binding = self.env['doc.report'].create({
            'name': '逐筆設定測試綁定',
            'template_id': self.template.id,
            'report_id': self.report.id,
        })
        self.partner = self.env['res.partner'].create({'name': '逐筆設定客戶'})
        import base64
        self.att = self.env['ir.attachment'].create({
            'name': '條款.pdf', 'mimetype': 'application/pdf',
            'datas': base64.b64encode(b'%PDF-FIXED'),
        })
        self.binding.append_attachment_ids = [(6, 0, self.att.ids)]

    def _patch(self, name, value):
        """把一支約定方法掛到 res.partner 上（測試結束自動還原）。

        不能用 self.patch()：它沒帶 create=True，而這幾支約定方法在
        res.partner 上本來不存在——patch.object 找不到原屬性就直接拋。
        """
        patcher = patch.object(type(self.partner), name, value, create=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    # ── ② 記錄層級的附頁開關 ───────────────────────────────────
    def test_always_does_not_even_ask_the_record(self):
        """設了附頁卻什麼都沒發生，是個找不到原因的坑。預設不問記錄。"""
        asked = []
        self._patch('doc_report_append_enabled',
                    lambda rec: asked.append(1) or False)
        self.assertEqual(self.binding.append_record_policy, 'always')
        self.assertEqual(
            self.binding._append_streams_for(self.partner), [b'%PDF-FIXED'])
        self.assertFalse(asked, 'policy=always 還是去問了記錄')

    def test_opt_out_lets_the_record_turn_it_off(self):
        self.binding.append_record_policy = 'opt_out'
        self._patch('doc_report_append_enabled', lambda rec: False)
        self.assertEqual(self.binding._append_streams_for(self.partner), [])
        self._patch('doc_report_append_enabled', lambda rec: True)
        self.assertEqual(
            self.binding._append_streams_for(self.partner), [b'%PDF-FIXED'])

    def test_opt_in_needs_the_record_to_say_yes(self):
        self.binding.append_record_policy = 'opt_in'
        self.assertEqual(self.binding._append_streams_for(self.partner), [],
                         '模型沒有那支方法時 opt_in 應該當成不附')
        self._patch('doc_report_append_enabled', lambda rec: True)
        self.assertEqual(
            self.binding._append_streams_for(self.partner), [b'%PDF-FIXED'])

    def test_missing_hook_falls_back_to_the_policy_default(self):
        self.binding.append_record_policy = 'opt_out'
        self.assertEqual(
            self.binding._append_streams_for(self.partner), [b'%PDF-FIXED'],
            '模型沒有那支方法時 opt_out 應該當成要附')

    def test_failing_hook_falls_back_to_the_policy_default(self):
        self.binding.append_record_policy = 'opt_in'
        self._patch('doc_report_append_enabled',
                    lambda rec: (_ for _ in ()).throw(ValueError('壞了')))
        self.assertEqual(self.binding._append_streams_for(self.partner), [])

    # ── ① 記錄自備附頁 ─────────────────────────────────────────
    def test_record_supplied_attachments_are_appended_last(self):
        """記錄自備的放最後：它是「這一張單的附件」，在通用條款之後。"""
        import base64
        own = self.env['ir.attachment'].create({
            'name': '檢驗報告.pdf', 'mimetype': 'application/pdf',
            'datas': base64.b64encode(b'%PDF-OWN'),
        })
        self._patch('doc_report_append_pdfs', lambda rec: own)
        self.assertEqual(
            self.binding._append_streams_for(self.partner),
            [b'%PDF-FIXED', b'%PDF-OWN'])

    def test_record_may_return_raw_bytes_too(self):
        self._patch('doc_report_append_pdfs', lambda rec: [b'%PDF-A', b'%PDF-B'])
        self.assertEqual(
            self.binding._append_streams_for(self.partner),
            [b'%PDF-FIXED', b'%PDF-A', b'%PDF-B'])

    def test_record_pdfs_without_the_hook_is_empty(self):
        self.assertEqual(self.binding._record_append_pdfs(self.partner), [])

    def test_failing_record_pdfs_does_not_lose_the_fixed_ones(self):
        self._patch('doc_report_append_pdfs',
                    lambda rec: (_ for _ in ()).throw(ValueError('壞了')))
        self.assertEqual(
            self.binding._append_streams_for(self.partner), [b'%PDF-FIXED'])

    def test_model_supplying_pdfs_alone_triggers_the_pdf_hook(self):
        """綁定沒設附頁、但模型自己會給 → 攔截點還是要進去。"""
        self.binding.append_attachment_ids = [(5, 0, 0)]
        self._patch('doc_report_append_pdfs', lambda rec: [b'%PDF-OWN'])
        self.assertEqual(
            self.binding._append_streams_for(self.partner), [b'%PDF-OWN'])

    # ── ③ 記錄層級的範本覆寫 ───────────────────────────────────
    def test_record_template_overrides_the_binding(self):
        special = self.env['doc.template'].create({
            'name': '客戶指定版面', 'role': 'content',
            'model_id': self.model.id,
            'content_json': json.dumps({'main': [_text('客戶指定的本文')]}),
        })
        self._patch('doc_report_template', lambda rec: special)
        self.assertEqual(
            self.binding._record_template_for(self.partner), special)
        html, _frozen = self.binding._build_report_html(self.partner)
        self.assertIn('客戶指定的本文', html)
        self.assertNotIn('綁定範本的本文', html)

    def test_wrong_model_template_is_ignored(self):
        """拿別的模型的範本去印，會印出一張看起來正常、值全空的單據。"""
        other = self.env['doc.template'].create({
            'name': '別的模型', 'role': 'content',
            'model_id': self.env['ir.model']._get('res.users').id,
            'content_json': json.dumps({'main': [_text('不該出現')]}),
        })
        self._patch('doc_report_template', lambda rec: other)
        self.assertFalse(self.binding._record_template_for(self.partner))
        html, _frozen = self.binding._build_report_html(self.partner)
        self.assertIn('綁定範本的本文', html)
        self.assertNotIn('不該出現', html)

    def test_no_override_uses_the_binding_template(self):
        html, _frozen = self.binding._build_report_html(self.partner)
        self.assertIn('綁定範本的本文', html)

    def test_failing_template_hook_uses_the_binding_template(self):
        self._patch('doc_report_template',
                    lambda rec: (_ for _ in ()).throw(ValueError('壞了')))
        html, _frozen = self.binding._build_report_html(self.partner)
        self.assertIn('綁定範本的本文', html)

    def test_two_records_with_different_templates_parse_once_each(self):
        """逐筆覆寫不可以變成「每筆都重新解析一次 content_json」。"""
        special = self.env['doc.template'].create({
            'name': '共用的特別範本', 'role': 'content',
            'model_id': self.model.id,
            'content_json': json.dumps({'main': [_text('特別本文')]}),
        })
        others = self.env['res.partner'].create([
            {'name': '甲'}, {'name': '乙'}, {'name': '丙'}])
        self._patch('doc_report_template', lambda rec: special)
        calls = []
        Mixin = type(self.env['doc.render.mixin'])
        original = Mixin._parse_content_json

        def _spy(mixin_self, raw):
            calls.append(1)
            return original(mixin_self, raw)

        self.patch(Mixin, '_parse_content_json', _spy)
        html, _frozen = self.binding._build_report_html(others)
        self.assertIn('特別本文', html)
        # 綁定的範本 1 次 + 特別範本 1 次（外框與綁定同一張時不重複解析）
        self.assertLessEqual(len(calls), 3,
                             '解析了 %d 次，逐筆範本沒有快取' % len(calls))

    # ── mixin 的預設實作 ───────────────────────────────────────
    def test_mixin_provides_the_three_hooks_and_two_fields(self):
        Mixin = self.env['doc.linked.mixin']
        for hook in ('doc_report_append_enabled', 'doc_report_append_pdfs',
                     'doc_report_template'):
            self.assertTrue(hasattr(Mixin, hook), '少了 %s' % hook)
        self.assertIn('doc_append_pages', Mixin._fields)
        self.assertIn('doc_report_template_id', Mixin._fields)

    def test_hook_names_are_declared_in_one_place(self):
        """名字散在兩邊會各自漂移。"""
        hooks = self.env['doc.report']._RECORD_HOOKS
        self.assertEqual(
            set(hooks.values()),
            {'doc_report_append_enabled', 'doc_report_append_pdfs',
             'doc_report_template'})


@tagged('post_install', '-at_install', 'dobtor_doc_editor')
class TestAppendPagesEndToEnd(TransactionCase):
    """附頁：真的產一份 PDF、數頁數。

    其他附頁測試釘的是「取哪些、順序、失敗取捨」——那些不需要 wkhtmltopdf。
    但「頁數對不對」與「多筆列印時每張後面都有自己那份」只能用真的 PDF 驗，
    而那正是最容易壞的地方（在 _render_qweb_pdf 之後動手的話，附頁會全部堆在
    最後一張單據後面，而單筆列印時完全看不出差別）。

    ☠️ **這一組需要多個 worker。** 測試模式下 Odoo 會把 _render_qweb_pdf 短路
    成 HTML（ir_actions_report.py:1008），註解寫明理由是「worker 不夠跑
    wkhtmltopdf」。用 force_report_rendering 強制的話，wkhtmltopdf 會回頭向
    同一個 Odoo 行程要 assets，而 --workers=0 只有一條執行緒在跑測試
    ——直接死結到 timeout（實測：一則測試卡 5 分鐘以上）。

    所以 workers=0 時 skip，訊息裡講明「附頁的頁數未由測試驗證」。
    本機 rig 就是 workers=0，所以這一組在那裡永遠是 skip；我用 odoo shell
    手動驗過一次（shell 不對外服務 HTTP，沒有那個死結），數字記在
    docs/qweb_converter_coverage.md。CI 若以多 worker 跑就會真的執行。
    """

    def setUp(self):
        super().setUp()
        from odoo.tools import config
        from odoo.tools.misc import find_in_path
        try:
            find_in_path('wkhtmltopdf')
        except (IOError, OSError):
            self.skipTest('沒有 wkhtmltopdf——附頁的頁數未由測試驗證')
        if not (config['workers'] or 0):
            self.skipTest(
                'workers=0：強制產 PDF 會與 wkhtmltopdf 的回呼死結'
                '——附頁的頁數未由測試驗證（見本類別的 docstring）')
        model = self.env['ir.model']._get('res.partner')
        self.template = self.env['doc.template'].create({
            'name': 'E2E 附頁範本', 'role': 'content', 'model_id': model.id,
            'content_json': json.dumps(
                {'main': [_text('本體內容'), _text('\n')]}),
        })
        self.report = self.env['ir.actions.report'].create({
            'name': 'E2E 附頁報表', 'model': 'res.partner',
            'report_type': 'qweb-pdf',
            'report_name': 'base.report_partnercontact',
        })
        self.binding = self.env['doc.report'].create({
            'name': 'E2E 附頁綁定',
            'template_id': self.template.id, 'report_id': self.report.id,
        })
        self.p1 = self.env['res.partner'].create({'name': 'E2E 甲'})
        self.p2 = self.env['res.partner'].create({'name': 'E2E 乙'})

    def _pages(self, content):
        import io
        from odoo.tools.pdf import PdfFileReader
        return PdfFileReader(io.BytesIO(content), strict=False).getNumPages()

    def _print(self, records):
        # force_report_rendering：測試模式下 Odoo 會把 _render_qweb_pdf 短路成
        # HTML（ir_actions_report.py:1008）。不強制的話這一整組測試量到的是
        # 字串長度而不是頁數——**而且會綠**。
        content, ext = self.report.with_context(
            force_report_rendering=True)._render_qweb_pdf(
                self.report.id, records.ids)
        self.assertEqual(ext, 'pdf', '拿到的不是 PDF（%s）' % ext)
        return self._pages(content)

    def _two_page_pdf(self):
        """拿同一張報表印兩筆當成「兩頁的固定 PDF」。"""
        content, _ext = self.report.with_context(
            doc_report_no_append=True,
            force_report_rendering=True)._render_qweb_pdf(
                self.report.id, (self.p1 + self.p2).ids)
        self.assertEqual(self._pages(content), 2)
        return content

    def test_fixed_pdf_adds_its_pages(self):
        import base64
        base = self._print(self.p1)
        two = self._two_page_pdf()
        self.binding.append_attachment_ids = [(0, 0, {
            'name': '標準條款.pdf', 'mimetype': 'application/pdf',
            'datas': base64.b64encode(two),
        })]
        self.assertEqual(self._print(self.p1), base + 2)

    def test_record_supplied_pdf_adds_its_pages(self):
        base = self._print(self.p1)
        two = self._two_page_pdf()
        patcher = patch.object(
            type(self.p1), 'doc_report_append_pdfs',
            lambda rec: [two], create=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.assertEqual(self._print(self.p1), base + 2)

    def test_record_can_turn_appends_off(self):
        import base64
        base = self._print(self.p1)
        two = self._two_page_pdf()
        self.binding.append_attachment_ids = [(0, 0, {
            'name': '標準條款.pdf', 'mimetype': 'application/pdf',
            'datas': base64.b64encode(two),
        })]
        self.binding.append_record_policy = 'opt_out'
        patcher = patch.object(
            type(self.p1), 'doc_report_append_enabled',
            lambda rec: False, create=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.assertEqual(self._print(self.p1), base)

    def test_each_record_gets_its_own_appendix(self):
        """**這一則是重點。**

        在 _render_qweb_pdf 之後合併的話，兩筆列印會變成
        「本體A + 本體B + 附頁」而不是「本體A + 附頁 + 本體B + 附頁」——
        頁數少了一份，而單筆列印時完全看不出差別。
        """
        import base64
        base = self._print(self.p1)
        two = self._two_page_pdf()
        self.binding.append_attachment_ids = [(0, 0, {
            'name': '標準條款.pdf', 'mimetype': 'application/pdf',
            'datas': base64.b64encode(two),
        })]
        self.assertEqual(self._print(self.p1 + self.p2), (base + 2) * 2)


@tagged('post_install', '-at_install', 'dobtor_doc_editor')
class TestHeaderFooterLayout(TransactionCase):
    """頁首頁尾的版面屬性與「哪一頁要出現」。

    wkhtmltopdf 的頁首是**另一份文件**、鋪滿紙張寬度，本文的左右邊距對它
    無效——所以左右內距要自己留，否則頁首與本文左右對不齊。
    """

    def setUp(self):
        super().setUp()
        model = self.env['ir.model']._get('res.partner')
        self.frame = self.env['doc.template'].create({
            'name': '頁首頁尾測試外框', 'role': 'layout',
            'model_id': model.id,
            'content_json': json.dumps({
                'header': [_text('頁首文字'), _text('\n')],
                'footer': [_text('頁尾文字'), _text('\n')],
                'main': [],
            }),
        })
        self.template = self.env['doc.template'].create({
            'name': '頁首頁尾測試範本', 'role': 'content',
            'model_id': model.id, 'layout_id': self.frame.id,
            'content_json': json.dumps({'main': [_text('本文'), _text('\n')]}),
        })
        self.report = self.env['ir.actions.report'].create({
            'name': '頁首頁尾測試報表', 'model': 'res.partner',
            'report_type': 'qweb-pdf',
            'report_name': 'dobtor_doc_editor.hf_probe',
        })
        self.binding = self.env['doc.report'].create({
            'name': '頁首頁尾測試綁定',
            'template_id': self.template.id, 'report_id': self.report.id,
        })
        self.partner = self.env['res.partner'].create({'name': '頁首測試客戶'})

    def _html(self):
        html, _frozen = self.binding._build_report_html(self.partner)
        return html

    def test_defaults_add_no_style(self):
        """沒設就不要吐 style——頁首是每頁重載的，多一段都是每頁的成本。"""
        html = self._html()
        self.assertIn('頁首文字', html)
        self.assertNotIn('div.header{', html)

    def test_padding_is_emitted(self):
        self.frame.header_padding_x = 40
        self.assertIn('padding-left:40px', self._html())

    def test_rule_is_emitted_on_the_right_side(self):
        self.frame.header_rule = True
        self.frame.footer_rule = True
        html = self._html()
        self.assertIn('border-bottom:1px solid #000', html)
        self.assertIn('border-top:1px solid #000', html)

    def test_page_scope_script_only_when_used(self):
        """沒用到頁面範圍標記就不要塞那段 script。"""
        self.assertNotIn('doc-pg-', self._html())
        self.frame.content_json = json.dumps({
            'header': [
                _pill('只在首頁', source='pageScope', scope='first',
                      isMarker=True),
                _text('信紙'), _text('\n'),
            ],
            'footer': [], 'main': [],
        })
        html = self._html()
        self.assertIn('doc-page-first', html)
        self.assertIn('doc-pg-first', html, '少了決定頁次的 script')
        self.assertIn('document.location.search', html)

    def test_script_reads_the_page_param_wkhtmltopdf_passes(self):
        """頁次只能從網址參數拿——Odoo 自己的 subst() 也是這樣做的
        （web/views/report_templates.xml）。"""
        self.frame.content_json = json.dumps({
            'header': [
                _pill('X', source='pageScope', scope='odd', isMarker=True),
                _text('奇數頁'), _text('\n')],
            'footer': [], 'main': [],
        })
        html = self._html()
        self.assertIn('v.page', html)
        self.assertIn('doc-pg-odd', html)


@tagged('post_install', '-at_install', 'dobtor_doc_editor')
class TestOpenEditorDirectly(TransactionCase):
    """點開文件直接進編輯器（做法沿用 dobtor_xmind）。

    文件的內容就是編輯器裡那一份。原本點一筆開表單，使用者看到一堆設定欄位，
    還要再按一次「開啟編輯器」——他想做的事在第二層。
    """

    def test_create_and_open_returns_the_editor(self):
        action = self.env['doc.document'].action_new_and_open_editor()
        self.assertEqual(action['type'], 'ir.actions.client')
        self.assertEqual(action['tag'], 'dobtor_doc_editor.action_doc_editor')
        self.assertTrue(action['context']['doc_id'])
        doc = self.env['doc.document'].browse(action['context']['doc_id'])
        self.assertTrue(doc.exists())

    def test_create_and_open_uses_the_blank_template(self):
        blank = self.env.ref('dobtor_doc_editor.doc_template_blank',
                             raise_if_not_found=False)
        if not blank:
            self.skipTest('找不到「空白文件」範本')
        action = self.env['doc.document'].action_new_and_open_editor()
        doc = self.env['doc.document'].browse(action['context']['doc_id'])
        self.assertEqual(doc.template_id, blank)

    def test_settings_form_is_still_reachable(self):
        """點開一筆直接進編輯器，表單上才有的設定要留一條路。"""
        doc = self.env['doc.document'].create({'name': '設定入口測試'})
        action = doc.action_open_settings_form()
        self.assertEqual(action['type'], 'ir.actions.act_window')
        self.assertEqual(action['res_model'], 'doc.document')
        self.assertEqual(action['res_id'], doc.id)
        self.assertEqual(action['view_mode'], 'form')

    def test_list_view_declares_the_js_class(self):
        """少了 js_class，點一筆還是會開表單——而那是靜默的。"""
        view = self.env.ref('dobtor_doc_editor.view_doc_document_list')
        self.assertIn('doc_document_list_open_editor', view.arch)

    def test_template_list_also_opens_the_editor(self):
        view = self.env.ref('dobtor_doc_editor.view_doc_template_list')
        self.assertIn('doc_template_list_open_editor', view.arch)

    def test_template_settings_form_is_reachable(self):
        model = self.env['ir.model']._get('res.partner')
        tmpl = self.env['doc.template'].create({
            'name': '設定入口測試範本', 'role': 'content',
            'model_id': model.id, 'content_json': json.dumps({'main': []}),
        })
        action = tmpl.action_open_settings_form()
        self.assertEqual(action['res_model'], 'doc.template')
        self.assertEqual(action['res_id'], tmpl.id)

    def test_template_new_also_opens_the_editor(self):
        """先前刻意不一致（新範本沒有模型就沒有欄位可拖），現在前提已消除：
        左欄有就地選模型的介面，所以兩邊一致了。"""
        action = self.env['doc.template'].action_new_and_open_editor()
        self.assertEqual(action['type'], 'ir.actions.client')
        self.assertTrue(action['context']['template_id'])
        tmpl = self.env['doc.template'].browse(action['context']['template_id'])
        self.assertEqual(tmpl.role, 'content')
        self.assertFalse(tmpl.model_id, '新範本本來就還沒有模型——靠左欄就地設定')

    def test_model_picker_endpoints_exist(self):
        """沒有這兩支，上面那個一致性就不成立。

        它們住在**範本** controller：選適用模型是範本設計的事。
        （2026-10-09 路由拆成四個 Controller 時這一則紅過一次——那是它該有的
        行為，結構變了就該被看到。）
        """
        from odoo.addons.dobtor_doc_editor.controllers.doc_controller_template \
            import DocTemplateController
        for name in ('list_models', 'set_edit_target_model'):
            self.assertTrue(hasattr(DocTemplateController, name), '少了 %s' % name)
