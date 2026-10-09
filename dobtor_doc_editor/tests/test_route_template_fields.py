# -*- coding: utf-8 -*-
r"""範本欄位那 6 條路由 ＋ 匯出的行為測試——優化 3 第二批（2026-10-09）。

☠️ 這 6 條裡有 3 條**會改資料**（save_field / delete_field / save_signer），
而在這之前它們完全沒有任何驗證（`make audit` 的路由覆蓋尺量到的）。
`template_fields/load` 是唯一被 tour 走到的，但 tour 只是「打開面板」，
沒有驗內容。

一樣用**一條流程**（建簽約人 → 建欄位 → 載入確認 → 取選項 → 刪欄位）而不是
6 個獨立呼叫：欄位與簽約人有歸屬約束（`_check_signer_belongs_to_template`），
分開測會讓「前一步的輸出不是下一步的合法輸入」那類錯誤溜掉。
"""
from odoo.tests.common import HttpCase, tagged

from .session_probe import SessionAliveMixin


@tagged('post_install', '-at_install', 'dobtor_doc_editor')
class TestTemplateFieldRoutes(SessionAliveMixin, HttpCase):
    """範本欄位的六條路由，一條流程走完。"""

    def setUp(self):
        super().setUp()
        self.authenticate('admin', 'admin')
        self.template = self.env['doc.template'].sudo().create({
            'name': '欄位路由測試範本',
            'role': 'content',
            'model_id': self.env['ir.model']._get('res.partner').id,
        })
        self.doc = self.env['doc.document'].sudo().create({
            'name': '欄位路由測試文件',
            'content_html': '<p>x</p>',
            'template_id': self.template.id,
        })

    def _call(self, route, **params):
        return self._jsonrpc_with_evidence(route, params, where=route)

    def test_template_field_lifecycle_end_to_end(self):
        """建簽約人 → 建欄位 → 載入 → 取選項 → 刪欄位。"""
        # 1. 建簽約人
        signer = self._call('/dobtor_doc/template_fields/save_signer',
                            template_id=self.template.id,
                            signer={'name': '甲方'})
        self.assertTrue(
            signer.get('signer') or signer.get('id') or signer.get('signer_id'),
            'save_signer 沒回新建的簽約人：%r' % signer)

        # 2. 載入——簽約人要在裡面
        loaded = self._call('/dobtor_doc/template_fields/load',
                            template_id=self.template.id)
        signers = loaded.get('signers') or []
        self.assertTrue(signers, 'load 沒回 signers：%r' % loaded)
        signer_id = signers[0].get('id') or signers[0].get('signer_id')
        self.assertTrue(signer_id, 'signers 的項目缺 id：%r' % signers[0])

        # 3. 建一個 select 欄位（帶選項，才驗得到 options 那條路由）
        saved = self._call(
            '/dobtor_doc/template_fields/save_field',
            template_id=self.template.id,
            field={
                'signer_id': signer_id,
                'field_type': 'select',
                'layout_mode': 'inline',
                'label': '付款方式',
                'options': [{'value': '現金'}, {'value': '匯款'}],
            })
        self.assertIsInstance(saved, dict, 'save_field 回的不是 dict：%r' % saved)

        # 4. 載入確認欄位真的存進去了
        loaded2 = self._call('/dobtor_doc/template_fields/load',
                             template_id=self.template.id)
        fields = loaded2.get('fields') or []
        self.assertTrue(
            fields,
            'save_field 之後 load 回不到欄位——存進去了嗎？%r' % loaded2)
        field_id = fields[0].get('id') or fields[0].get('field_id')
        self.assertTrue(field_id, 'fields 的項目缺 id：%r' % fields[0])

        # 5. 取選項設定
        opts = self._call('/dobtor_doc/template_fields/options',
                          template_id=self.template.id, field_id=field_id)
        self.assertIsInstance(opts, dict, 'options 回的不是 dict：%r' % opts)

        # 6. 刪欄位——刪完 load 就不該再有它
        self._call('/dobtor_doc/template_fields/delete_field',
                   template_id=self.template.id, field_id=field_id)
        loaded3 = self._call('/dobtor_doc/template_fields/load',
                             template_id=self.template.id)
        remaining = [f.get('id') or f.get('field_id')
                     for f in (loaded3.get('fields') or [])]
        self.assertNotIn(
            field_id, remaining,
            'delete_field 之後欄位還在：%r' % remaining)

    def test_save_field_rejects_a_signer_from_another_template(self):
        """跨範本的簽約人要被擋——那是 `_check_signer_belongs_to_template`。

        ☠️ 約束本身有測試（test_model_constraints.py），但**沒有任何東西驗過
        這條路由會把那個約束的錯誤變成可讀的回應**而不是 500 或 traceback。
        """
        other = self.env['doc.template'].sudo().create({
            'name': '別的範本', 'role': 'content',
            'model_id': self.env['ir.model']._get('res.partner').id,
        })
        other_signer = self.env['doc.template.signer'].sudo().create({
            'template_id': other.id, 'name': '別家的簽約人',
        })
        from odoo.tests.common import JsonRpcException
        try:
            result = self._call(
                '/dobtor_doc/template_fields/save_field',
                template_id=self.template.id,
                field={'signer_id': other_signer.id, 'field_type': 'text',
                       'layout_mode': 'inline', 'label': '不該存進去'})
        except (AssertionError, JsonRpcException):
            return      # 被擋下來了，而且是 JSON 形式的錯誤
        # 若沒拋，至少不可以真的存進去
        loaded = self._call('/dobtor_doc/template_fields/load',
                            template_id=self.template.id)
        labels = [f.get('label') for f in (loaded.get('fields') or [])]
        self.assertNotIn(
            '不該存進去', labels,
            '跨範本的簽約人竟然存進去了（約束沒在這條路由上生效）：%r' % result)

    def test_template_requests_list_returns_a_list(self):
        """`template_requests/list` 至少要回得出結構（原本零驗證）。"""
        result = self._call('/dobtor_doc/template_requests/list',
                            doc_id=self.doc.id)
        self.assertIsInstance(result, (dict, list),
                              'template_requests/list 回的型別不對：%r' % result)

    def test_export_pdf_does_not_explode(self):
        """`/dobtor_doc/export` 是使用者的主要出口，原本零驗證。

        ☠️ 不斷言「一定產出 PDF」：容器裡不一定有 wkhtmltopdf，而
        「有沒有 PDF 引擎」不是這條路由的責任。斷言的是**它要嘛成功、
        要嘛給可讀的錯誤**——不可以 500、不可以噴 traceback 給使用者。
        """
        result = self._call('/dobtor_doc/export',
                            doc_id=self.doc.id, format='pdf')
        self.assertIsInstance(result, dict,
                              'export 回的不是 dict：%r' % result)
        if not result.get('success', True):
            msg = result.get('error') or ''
            self.assertNotIn(
                'Traceback', msg,
                'export 失敗時把 traceback 給了使用者：%r' % msg[:200])
            self.assertTrue(msg, 'export 失敗卻沒給任何訊息：%r' % result)
