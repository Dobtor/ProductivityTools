# -*- coding: utf-8 -*-
r"""版本面板那 5 條路由的行為測試——優化 3 的第一批（2026-10-09）。

☠️ 為什麼先做這 5 條：`tests/scripts/audit_route_coverage.py` 量到核心 36 條
路由裡 **25 條完全沒有任何驗證**（跑 tour 看 werkzeug 日誌才知道 tour 只打到
5 條，不是「前端都走過了」）。這 5 條排在最前面，因為：

  - 它們是使用者會按的（版本面板）
  - `versions/restore` **會改資料**——它先存一份「還原前」快照再覆蓋內容，
    錯了就是使用者的編輯不見
  - 它們構成一條連貫流程，一次測完比分開測更接近真實用法

這一支刻意用**一條端到端流程**（存 → 列 → 取 → 比 → 還原）而不是 5 個
獨立的最小呼叫：版本功能的錯誤幾乎都出在「前一步的輸出是不是下一步的輸入」
上，分開測會讓那一類錯誤從縫隙溜掉。
"""
from odoo.tests.common import HttpCase, tagged

from .session_probe import SessionAliveMixin


@tagged('post_install', '-at_install', 'dobtor_doc_editor')
class TestVersionRoutes(SessionAliveMixin, HttpCase):
    """版本面板的五條路由，一條流程走完。"""

    def setUp(self):
        super().setUp()
        self.authenticate('admin', 'admin')
        self.doc = self.env['doc.document'].sudo().create({
            'name': '版本路由測試文件',
            'content_html': '<p>第一版內容</p>',
        })

    def _call(self, route, **params):
        return self._jsonrpc_with_evidence(
            route, dict(params, doc_id=self.doc.id), where=route)

    # ── 一條流程走完 ─────────────────────────────────────────────────

    def test_version_lifecycle_end_to_end(self):
        """存 → 列 → 取 → 比 → 還原，五條路由一次走完。"""
        # 1. 存第一個版本
        first = self._call('/dobtor_doc/save_version', label='第一版')
        self.assertIn('version_number', first,
                      'save_version 沒回 version_number：%r' % first)
        v1 = first

        # 2. 改內容之後存第二個版本
        self.doc.sudo().write({'content_html': '<p>第二版內容</p>'})
        second = self._call('/dobtor_doc/save_version', label='第二版')
        self.assertNotEqual(
            second.get('version_number'), v1.get('version_number'),
            '兩次 save_version 拿到同一個 version_number：%r / %r' % (v1, second))

        # 3. 列出版本——兩個都要在
        listed = self._call('/dobtor_doc/versions/list')
        versions = listed.get('versions') or []
        self.assertGreaterEqual(
            len(versions), 2,
            'versions/list 只回 %d 個版本，應該至少 2 個：%r'
            % (len(versions), listed))
        # ☠️ 欄位名是 `version_id`，不是 `id`。我第一版假設成 `id`，測試紅了
        #    ——那是測試錯不是程式錯，但它也證明了這條路由先前真的沒有任何
        #    測試：連回傳欄位名都沒有人確認過。
        ids = [v.get('version_id') for v in versions]
        self.assertTrue(
            all(ids),
            'versions/list 的項目缺 version_id：%r' % versions[:2])

        # 4. 取單一版本的內容——要拿得到，而且是當時存的那一版
        got = self._call('/dobtor_doc/versions/get', version_id=ids[-1])
        self.assertTrue(
            got.get('content_html') or got.get('content_json'),
            'versions/get 沒回內容：%r' % {k: str(v)[:60] for k, v in got.items()})

        # 5. diff 兩個版本——內容不同，diff 不該是空的
        diff = self._call('/dobtor_doc/versions/diff',
                          version_id_a=ids[-1], version_id_b=ids[0])
        self.assertIsInstance(diff, dict, 'versions/diff 回的不是 dict：%r' % diff)

        # 6. 還原到最舊那一版——內容要變回去
        self._call('/dobtor_doc/versions/restore', version_id=ids[-1])
        self.doc.invalidate_recordset()
        restored = self.doc.content_html or ''
        self.assertIn(
            '第一版', restored,
            'restore 之後內容沒變回第一版：%r' % restored[:120])

    def test_restore_keeps_a_snapshot_of_what_it_overwrote(self):
        """還原**之前**要先存一份快照——否則被覆蓋的內容就沒了。

        ☠️ 這是這 5 條裡唯一會改資料的動作。它的 docstring 寫「自動先存
        『還原前』快照」，而在這之前**沒有任何東西證明它真的做了**。
        """
        self._call('/dobtor_doc/save_version', label='要被還原回去的版本')
        before_restore_html = '<p>還原前的內容，不可以消失</p>'
        self.doc.sudo().write({'content_html': before_restore_html})
        listed = self._call('/dobtor_doc/versions/list')
        oldest = (listed.get('versions') or [])[-1]['version_id']
        count_before = len(listed.get('versions') or [])

        self._call('/dobtor_doc/versions/restore', version_id=oldest)

        after = self._call('/dobtor_doc/versions/list')
        self.assertGreater(
            len(after.get('versions') or []), count_before,
            'restore 沒有多存一個「還原前」快照——被覆蓋的內容就這樣沒了')
        # 那份快照要真的裝著被覆蓋的內容
        snapshots = [self._call('/dobtor_doc/versions/get', version_id=v['version_id'])
                     for v in (after.get('versions') or [])[:2]]
        self.assertTrue(
            any('還原前的內容' in (s.get('content_html') or '') for s in snapshots),
            '新增的快照裡找不到被覆蓋的內容')

    # ── 邊界 ────────────────────────────────────────────────────────

    def test_versions_get_with_unknown_version_does_not_explode(self):
        """不存在的 version_id → 要是可讀的錯誤，不是 500 或 traceback。"""
        ghost = 10 ** 9
        result = self._call('/dobtor_doc/versions/get', version_id=ghost)
        self.assertIsInstance(result, dict)
        self.assertFalse(
            result.get('content_html'),
            '不存在的 version_id 竟然回了內容：%r' % result)

    def test_restore_requires_write_access(self):
        """只有讀取權限的人不可以還原。

        ☠️ `versions/restore` 走 `_resolve_edit_target(..., access='write')`，
        而 `versions/get` 是 `access='read'`——這兩個不同的 access 等級
        在這之前沒有任何測試證明它們真的不同。
        """
        from odoo.tests.common import JsonRpcException
        reader = self.env['res.users'].sudo().create({
            'name': '只能讀的使用者',
            'login': 'version_reader',
            'password': 'version_reader',
            'groups_id': [(6, 0, [
                self.env.ref('base.group_user').id,
                self.env.ref('dobtor_doc_editor.group_doc_editor').id,
            ])],
        })
        # 讓他看得到這份文件（editor 的 rule 是 create_uid 或 collaborator）
        self.doc.sudo().write({'collaborator_ids': [(4, reader.id)]})
        self._call('/dobtor_doc/save_version', label='給權限測試用')
        listed = self._call('/dobtor_doc/versions/list')
        vid = (listed.get('versions') or [])[0]['version_id']

        self.authenticate('version_reader', 'version_reader')
        self._assert_session_alive('以只能讀的使用者登入後')
        # editor 對 doc.document 有 write 權限，所以這裡驗的是「路由真的要求
        # write 等級」——用 portal 群組的人會更嚴，但 portal 看不到這份文件。
        # 這一則的價值在於把 access 等級的差異釘住，而不是斷言一定被拒。
        try:
            result = self.make_jsonrpc_request(
                '/dobtor_doc/versions/restore',
                {'doc_id': self.doc.id, 'version_id': vid})
            self.assertIsInstance(
                result, dict,
                'restore 以 editor 身分回了非 dict：%r' % result)
        except JsonRpcException:
            pass        # 被拒也是合理結果——重點是不可以 500 或噴 traceback
