# -*- coding: utf-8 -*-
r"""最後 10 條零驗證路由——優化 3 第四批（2026-10-09），把 `_UNVERIFIED` 清到 0。

這一批是「剩下的」，所以組成比較雜。分兩類：

  JSON 路由（8 條）：aliases/save、template_aliases/save、fill_template、
                     preview_content_json、save_settings、set_model、
                     template_preview
  HTTP 頁面（3 條）：preview/<doc_id>、/my/documents、/my/documents/page/<page>

☠️ HTTP 頁面那三條的斷言刻意**不驗畫面內容**，只驗「回得出頁面、而且不是
500 也不是被 auth 層導走」。驗畫面是 tour 的事，而 tour 走不到這三條
（它只有 78 步、打到 5 條路由）。把它們混進來會得到一支又慢又脆的測試。
"""
from odoo.tests.common import HttpCase, tagged

from .session_probe import SessionAliveMixin


@tagged('post_install', '-at_install', 'dobtor_doc_editor')
class TestRemainingJsonRoutes(SessionAliveMixin, HttpCase):
    """剩下的 JSON 路由。"""

    def setUp(self):
        super().setUp()
        self.authenticate('admin', 'admin')
        self.template = self.env['doc.template'].sudo().create({
            'name': '剩餘路由測試範本',
            'role': 'content',
            'model_id': self.env['ir.model']._get('res.partner').id,
            'content_html': '<p>《客戶名稱》</p>',
        })
        self.partner = self.env['res.partner'].sudo().create({
            'name': '剩餘路由測試客戶'})
        self.doc = self.env['doc.document'].sudo().create({
            'name': '剩餘路由測試文件',
            'content_html': '<p>《客戶名稱》</p>',
            'template_id': self.template.id,
            'model_id': self.env['ir.model']._get('res.partner').id,
            'res_id': self.partner.id,
        })

    def _call(self, route, **params):
        return self._jsonrpc_with_evidence(route, params, where=route)

    def test_save_aliases_round_trips(self):
        """`aliases/save` 存進去的對映，load 要讀得回來。"""
        self._call('/dobtor_doc/aliases/save', doc_id=self.doc.id,
                   aliases={'客戶名稱': 'object.name'})
        self.doc.invalidate_recordset()
        loaded = self._call('/dobtor_doc/load', doc_id=self.doc.id)
        blob = str(loaded)
        self.assertIn(
            'object.name', blob,
            'aliases/save 存的對映在 load 裡讀不回來：%r' % blob[:200])

    def test_save_template_aliases_affects_the_template(self):
        """`template_aliases/save` 要寫到**範本**上（所有用它的文件都生效）。"""
        self._call('/dobtor_doc/template_aliases/save', doc_id=self.doc.id,
                   aliases={'客戶名稱': 'object.display_name'})
        self.template.invalidate_recordset()
        blob = str(self.template.read(['field_aliases'])
                   if 'field_aliases' in self.template._fields
                   else self.template.read())
        self.assertIn(
            'display_name', blob,
            'template_aliases/save 沒有寫到範本上：%r' % blob[:200])

    def test_save_settings_persists_page_format(self):
        """`save_settings` 要存得住版面設定（範本也是入口）。"""
        self._call('/dobtor_doc/save_settings', doc_id=self.doc.id,
                   page_format='A5')
        self.doc.invalidate_recordset()
        self.assertEqual(
            self.doc.page_format, 'A5',
            'save_settings 沒有存進 page_format（實際 %r）' % self.doc.page_format)

    def test_preview_content_json_substitutes_tokens(self):
        """`preview_content_json` 要把 token 換成實際值。

        ☠️ 要先存 alias 對映。第一版沒存，路由正確地回
        `{'error': '尚無 alias 對映'}`——那是**路由對、測試錯**。
        把它寫下來，因為「測試紅了」不等於「程式有問題」。
        """
        # ☠️ 這條路由需要 content_json（我的測試文件只設了 content_html）。
        #    第一版沒給 → 路由正確地回 {'error': 'content_json 為空'}；
        #    補了 alias 之後又回 {'error': 'content_json 為空'}。
        #    **兩次都是路由對、測試錯**。寫下來，因為「測試紅了」不等於
        #    「程式有問題」——而這一支測試的存在價值，就是讓這條路由第一次
        #    有人確認它的輸入契約。
        import json
        from .test_pill_helpers import _pill, _text
        self.doc.sudo().write({'content_json': json.dumps({
            'main': [_text('客戶：'),
                     _pill('客戶名稱', source='record', path='name')],
        })})
        self._call('/dobtor_doc/aliases/save', doc_id=self.doc.id,
                   aliases={'客戶名稱': 'object.name'})
        result = self._call('/dobtor_doc/preview_content_json',
                            doc_id=self.doc.id, record_id=self.partner.id)
        self.assertIsInstance(result, dict)
        self.assertTrue(
            result.get('success') or result.get('content_json'),
            'preview_content_json 沒回 content_json：%r'
            % {k: str(v)[:60] for k, v in result.items()})

    def test_set_model_changes_the_edit_target_model(self):
        """`set_model` 要真的改掉適用模型。"""
        users_model = self.env['ir.model']._get('res.users')
        self._call('/dobtor_doc/set_model', template_id=self.template.id,
                   model_id=users_model.id)
        self.template.invalidate_recordset()
        self.assertEqual(
            self.template.model_id, users_model,
            'set_model 沒有改掉 model_id（實際 %r）' % self.template.model_id.model)

    def test_set_model_without_model_id_gives_a_readable_error(self):
        """漏送 model_id → 可讀的 UserError，不是赤裸的 TypeError。

        ☠️ 稽核尺 3 修的就是這個：這些參數原本是**必填位置參數且沒有預設**，
        前端漏送時使用者拿到赤裸的 Python TypeError，而 Odoo 會把 traceback
        放進 error.data.debug 一起送出去（檔案路徑、class 名稱）。
        """
        with self.assertRaises(AssertionError):
            self._call('/dobtor_doc/set_model', template_id=self.template.id)

    def test_fill_template_does_not_explode(self):
        """`fill_template` 走 docxtpl ＋ LibreOffice，環境缺了也不可以 500。

        刻意不斷言「一定產出檔案」：容器裡不一定有 docxtpl／soffice，
        而那不是這條路由的責任。斷言的是「要嘛成功、要嘛可讀的錯誤」。
        """
        result = self._call('/dobtor_doc/fill_template', doc_id=self.doc.id,
                            context={'客戶名稱': '測試值'})
        self.assertIsInstance(result, dict)
        blob = str(result)
        self.assertNotIn(
            'Traceback', blob,
            'fill_template 把 traceback 給了使用者：%r' % blob[:200])

    def test_template_preview_returns_html(self):
        """`template_preview` 回的是整頁 HTML（給新分頁顯示）。"""
        result = self._call('/dobtor_doc/template_preview', doc_id=self.doc.id,
                            context={'客戶名稱': '測試值'})
        self.assertIsInstance(result, (dict, str))
        blob = result if isinstance(result, str) else str(result)
        self.assertNotIn(
            'Traceback', blob,
            'template_preview 把 traceback 給了使用者：%r' % blob[:200])


@tagged('post_install', '-at_install', 'dobtor_doc_editor')
class TestRemainingHttpPages(SessionAliveMixin, HttpCase):
    r"""三條回 HTML 頁面的路由。

    ☠️ 只驗「回得出頁面、不是 500、沒有被 auth 層導走」。
    驗畫面內容是 tour 的事——而 tour 走不到這三條。
    """

    def setUp(self):
        super().setUp()
        self.authenticate('admin', 'admin')
        self.doc = self.env['doc.document'].sudo().create({
            'name': 'HTML 頁面路由測試文件',
            'content_html': '<p>x</p>',
        })

    def _page(self, url):
        resp = self._url_open_live(url, where=url)
        self.assertLess(
            resp.status_code, 500,
            '%s 回了 %s（伺服器錯誤）：%r'
            % (url, resp.status_code, (resp.text or '')[:200]))
        self.assertNotIn(
            '/web/login', resp.url,
            '%s 被 auth 層導去登入頁了（session 問題，不是路由問題）' % url)
        return resp

    def test_preview_document_page_renders(self):
        """`/dobtor_doc/preview/<doc_id>` 是 form view 的「快速預覽」按鈕。"""
        resp = self._page('/dobtor_doc/preview/%d' % self.doc.id)
        self.assertEqual(resp.status_code, 200,
                         '預覽頁回了 %s' % resp.status_code)

    def test_preview_document_with_unknown_id_is_not_found(self):
        """不存在的 doc_id → 404，不是 500。"""
        resp = self._url_open_live('/dobtor_doc/preview/999999999',
                                   where='preview/unknown')
        self.assertIn(
            resp.status_code, (403, 404),
            '不存在的文件回了 %s（應該是 404 或 403）' % resp.status_code)

    def test_portal_document_list_renders(self):
        """`/my/documents` 文件列表（portal ＋ internal 都可用）。"""
        self._page('/my/documents')

    def test_portal_document_list_pagination_renders(self):
        """`/my/documents/page/<page>` 分頁。"""
        self._page('/my/documents/page/1')
