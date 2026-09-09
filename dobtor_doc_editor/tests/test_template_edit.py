"""Phase 1（藥丸改版）：範本可直接在編輯器中編輯。

涵蓋三件事：
  1. doc.template 的 Canvas JSON 權威格式與開啟編輯器的 action
  2. 範本版本快照（範本是共用資源，被覆蓋時必須能回溯）
  3. controller 的編輯對象解析 _resolve_edit_target / _require_document

第 3 項用 ORM 層直接呼叫 controller method（沿用 test_controllers.py 的作法，
HttpCase 太重）。_resolve_edit_target 需要 request.env，故以 HttpCase 覆蓋
真正走 HTTP 的那一小段。
"""

import json

from odoo.exceptions import AccessError
from odoo.tests.common import HttpCase, TransactionCase, tagged


@tagged('post_install', '-at_install', 'dobtor_doc_editor')
class TestTemplateEditTarget(TransactionCase):
    """範本作為「編輯對象」的模型層行為。"""

    def setUp(self):
        super().setUp()
        self.Template = self.env['doc.template']
        self.template = self.Template.create({
            'name': '合約範本',
            'content_html': '<p>初版條款</p>',
            'content_json': json.dumps({'main': [{'value': '初版條款'}]}),
        })

    # ─── content_json 權威格式 ───────────────────────────────────────

    def test_content_json_round_trip(self):
        """content_json 存得進、讀得出，且與 content_html 各自獨立。"""
        payload = json.dumps({'main': [{'value': '甲方'}, {'value': '乙方'}]})
        self.template.content_json = payload
        self.template.invalidate_recordset()
        self.assertEqual(self.template.content_json, payload)
        # content_html 不因寫 content_json 而變動（兩者是各自維護的欄位）
        self.assertEqual(self.template.content_html, '<p>初版條款</p>')

    def test_get_content_html_matches_document_api(self):
        """與 doc.document.get_content_html() 同名同語意，controller 才能統一呼叫。"""
        self.assertEqual(self.template.get_content_html(), '<p>初版條款</p>')
        self.template.content_html = False
        self.assertEqual(self.template.get_content_html(), '')

    def test_action_open_editor_carries_template_id(self):
        """開啟編輯器帶的是 template_id，不是 doc_id——前端據此進範本模式。"""
        action = self.template.action_open_editor()
        self.assertEqual(action['tag'], 'dobtor_doc_editor.action_doc_editor')
        self.assertEqual(action['target'], 'fullscreen')
        self.assertEqual(action['context']['template_id'], self.template.id)
        self.assertNotIn('doc_id', action['context'])

    def test_company_id_defaults_to_current(self):
        self.assertEqual(self.template.company_id, self.env.company)

    # ─── 版本快照 ────────────────────────────────────────────────────

    def test_save_version_increments_and_snapshots_both_formats(self):
        result = self.template.action_save_version(label='初版定稿')
        self.assertEqual(result['version_number'], 1)
        self.assertEqual(self.template.version_number, 1)

        entry = self.template.versions_data[0]
        self.assertEqual(entry['version_no'], 1)
        self.assertEqual(entry['label'], '初版定稿')
        # 兩種格式都要進快照，否則還原後 Canvas 版面會遺失
        self.assertEqual(entry['content_html'], '<p>初版條款</p>')
        self.assertIn('初版條款', entry['content_json'])

    def test_version_list_newest_first(self):
        self.template.action_save_version(label='v1')
        self.template.action_save_version(label='v2')
        versions = self.template.get_version_list()
        self.assertEqual([v['version_number'] for v in versions], [2, 1])
        # 清單是輕量的：不含 content
        self.assertNotIn('content_json', versions[0])

    def test_restore_snapshots_current_before_overwriting(self):
        """還原前先把當前內容存成新版本，否則覆蓋後無法回頭。"""
        self.template.action_save_version(label='原始')          # v1
        self.template.write({
            'content_html': '<p>改壞了</p>',
            'content_json': json.dumps({'main': [{'value': '改壞了'}]}),
        })

        result = self.template.restore_version(1)
        self.assertTrue(result['success'])
        self.assertEqual(self.template.content_html, '<p>初版條款</p>')
        self.assertIn('初版條款', self.template.content_json)

        # v2 應該是「還原前」的自動快照，內容為改壞的版本
        auto = self.template._find_version_entry(2)
        self.assertIsNotNone(auto)
        self.assertEqual(auto['content_html'], '<p>改壞了</p>')

    def test_restore_unknown_version_returns_error(self):
        result = self.template.restore_version(999)
        self.assertFalse(result['success'])

    def test_get_version_content_unknown_returns_error_not_raise(self):
        self.assertIn('error', self.template.get_version_content(999))

    def test_diff_versions_detects_change(self):
        self.template.action_save_version(label='v1')
        self.template.content_html = '<p>初版條款</p><p>新增第二條</p>'
        self.template.action_save_version(label='v2')

        diff = self.template.diff_versions(1, 2)
        self.assertIsNotNone(diff)
        ops = {o['op'] for o in diff['opcodes']}
        self.assertIn('insert', ops)

    def test_diff_versions_unknown_returns_none(self):
        self.template.action_save_version(label='v1')
        self.assertIsNone(self.template.diff_versions(1, 999))


@tagged('post_install', '-at_install', 'dobtor_doc_editor')
class TestTemplateEditPermissions(TransactionCase):
    """範本編輯的權限邊界。

    doc.template 的 ACL：editor 唯讀、manager 可寫（ir.model.access.csv:4-5）。
    範本模式開放後，這條界線就是「誰能改共用範本」，必須守住。
    """

    def setUp(self):
        super().setUp()
        self.template = self.env['doc.template'].create({
            'name': '權限測試範本',
            'content_html': '<p>x</p>',
        })
        self.editor_user = self.env['res.users'].create({
            'name': '一般編輯者',
            'login': 'doc_editor_phase1',
            'groups_id': [(6, 0, [
                self.env.ref('base.group_user').id,
                self.env.ref('dobtor_doc_editor.group_doc_editor').id,
            ])],
        })

    def test_editor_can_read_template(self):
        tmpl = self.template.with_user(self.editor_user)
        self.assertEqual(tmpl.name, '權限測試範本')

    def test_editor_cannot_write_template_content(self):
        """一般編輯者不能改共用範本的內容——範本模式不可繞過這條 ACL。"""
        tmpl = self.template.with_user(self.editor_user)
        with self.assertRaises(AccessError):
            tmpl.write({'content_json': '{"main": []}'})

    def test_editor_cannot_create_template_field(self):
        """doc.template.field 對 editor 是唯讀（ir.model.access.csv:25）。

        這正是模型變數改為「自描述元素」的原因：若欄位定義一律落在
        doc.template.field，一般使用者拖欄位進文件就會撞上這道 ACL。
        """
        signer = self.env['doc.template.signer'].create({
            'template_id': self.template.id,
            'name': '甲方',
        })
        FieldModel = self.env['doc.template.field'].with_user(self.editor_user)
        with self.assertRaises(AccessError):
            FieldModel.create({
                'template_id': self.template.id,
                'signer_id': signer.id,
                'field_type': 'text',
            })


@tagged('post_install', '-at_install', 'dobtor_doc_editor')
class TestEditTargetResolution(HttpCase):
    """controller 的雙入口解析。

    _resolve_edit_target 需要 request.env，故走 HttpCase 以取得真正的
    request context；直接呼叫 controller method 即可，不必經過路由。
    """

    def setUp(self):
        super().setUp()
        self.template = self.env['doc.template'].create({
            'name': '解析測試範本',
            'content_html': '<p>範本內容</p>',
        })
        self.doc = self.env['doc.document'].create({
            'name': '解析測試文件',
            'content_html': '<p>文件內容</p>',
        })

    def _controller(self):
        from odoo.addons.dobtor_doc_editor.controllers.doc_controller import (
            DocController,
        )
        return DocController()

    def test_load_template_payload_shape_matches_document(self):
        """兩種模式的 /load 回傳 key 必須一致，前端才只有一條解析路徑。"""
        ctrl = self._controller()
        payload = ctrl._load_template_payload(self.template)

        self.assertEqual(payload['edit_target'], 'template')
        self.assertEqual(payload['id'], self.template.id)
        self.assertEqual(payload['content_html'], '<p>範本內容</p>')
        # 範本沒有的東西給預設值而不是省略 key
        self.assertIs(payload['res_id'], False)
        self.assertIs(payload['has_template'], False)
        self.assertEqual(payload['margin_top'], 96)
        self.assertEqual(payload['template_field_aliases'], {})

    def test_load_template_payload_has_no_missing_keys_vs_document(self):
        """逐 key 比對：範本 payload 不可少於文件 payload。"""
        self.authenticate('admin', 'admin')
        ctrl = self._controller()
        tmpl_payload = ctrl._load_template_payload(self.template)

        expected_keys = {
            'id', 'name', 'content_json', 'content_html', 'header_html',
            'footer_html', 'page_format', 'margin_top', 'margin_bottom',
            'margin_left', 'margin_right', 'model_id', 'model_name', 'res_id',
            'field_aliases', 'template_field_aliases', 'template_name',
            'has_template', 'template_filename', 'template_variables',
            'has_different_first_page', 'first_header_html',
            'first_footer_html', 'write_date', 'version_number', 'edit_target',
        }
        self.assertEqual(set(tmpl_payload), expected_keys)
