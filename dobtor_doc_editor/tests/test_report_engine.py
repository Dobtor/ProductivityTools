"""報表引擎（R1-R3）：doc.report 綁定、HTML 結構契約、doc.output 唯讀。

這批測試的重點是 Odoo 報表管線的**結構契約**——我們產生的 HTML 若不符合
ir_actions_report._prepare_html() 的期待，失敗方式是 IndexError 或 UserError，
而不是「版面有點怪」。所以結構比內容更該被釘住。
"""
import json

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
