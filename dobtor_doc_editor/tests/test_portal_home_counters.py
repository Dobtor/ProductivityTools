"""入口網站 /my 首頁計數：沒有文件權限的 portal 使用者不可讓整個計數請求失敗。

背景（2026-11 經銷商站實測）：/my 首頁的磁貼計數是一次 JSON 請求
（/my/counters）把所有磁貼一起算。一般 portal 使用者（沒有 group_doc_portal）
對 doc.document 沒有 ACL，舊版 `search_count` 丟 AccessError → 整個請求失敗
→ 首頁一直轉圈，其他模組的磁貼也一起不出現。
"""
from unittest.mock import patch

from odoo.addons.portal.controllers.portal import CustomerPortal
from odoo.tests import HttpCase, new_test_user, tagged

from .session_probe import SessionAliveMixin


@tagged('post_install', '-at_install', 'dobtor_doc_editor', 'security')
class TestPortalHomeCounters(SessionAliveMixin, HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.plain_portal = new_test_user(
            cls.env, login='doc_plain_portal', password='doc_plain_portal',
            groups='base.group_portal')
        cls.doc_portal = new_test_user(
            cls.env, login='doc_collab_portal', password='doc_collab_portal',
            groups='base.group_portal,dobtor_doc_editor.group_doc_portal')
        cls.env['doc.document'].sudo().create({
            'name': 'portal counter doc',
            'content_html': '<p>x</p>',
            'collaborator_ids': [(6, 0, cls.doc_portal.ids)],
        })

    def _counters(self, counters):
        # 上游 portal 的基底 _prepare_home_portal_values 回 {}；這裡讓它帶一個
        # 「別的模組」的計數，用來確認 doc_count 不會把其他磁貼一起拖垮。
        def _base(self_ctrl, counters):
            return {'probe_count': 7} if 'probe_count' in counters else {}
        with patch.object(CustomerPortal, '_prepare_home_portal_values', _base):
            return self._jsonrpc_with_evidence(
                '/my/counters', {'counters': counters}, where='/my/counters')

    def test_plain_portal_user_counters_do_not_fail(self):
        self.assertFalse(
            self.env['doc.document'].with_user(self.plain_portal).has_access('read'),
            '前提：一般 portal 使用者對 doc.document 應該沒有讀取權限')
        self.authenticate('doc_plain_portal', 'doc_plain_portal')
        res = self._counters(['doc_count', 'probe_count'])
        self.assertEqual(res.get('doc_count'), 0)
        self.assertEqual(res.get('probe_count'), 7, '其他磁貼的計數要照常回傳')

    def test_plain_portal_user_home_page_200(self):
        self.authenticate('doc_plain_portal', 'doc_plain_portal')
        resp = self._url_open_live('/my', where='/my')
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn('/web/login', resp.url)

    def test_doc_portal_user_counts_own_documents(self):
        self.authenticate('doc_collab_portal', 'doc_collab_portal')
        res = self._counters(['doc_count', 'probe_count'])
        self.assertEqual(res.get('doc_count'), 1)
        self.assertEqual(res.get('probe_count'), 7)
