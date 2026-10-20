# -*- coding: utf-8 -*-
"""存檔的樂觀鎖（``base_digest``）與預覽節點防線。

背景：``save_mindmap_data`` 是整張分頁覆寫，沒有任何版本比對 —— 後存者覆蓋先存者。
現在編輯器存檔會帶上「載入／上次存檔後」的分頁摘要，不符就拒絕。

★ 最重要的一組是**向後相容**：不帶 ``base_digest`` 的呼叫（舊前端、版本還原、
  匯入、既有測試）必須維持原本的行為，一個字都不能變。
"""

from odoo.tests import HttpCase, TransactionCase, new_test_user, tagged

from odoo.addons.dobtor_xmind.models.xmind_digest import XmindConflict


def _node(cid, title, children=(), data=None):
    return {'id': cid, 'topic': title, 'expanded': True,
            'data': data or {}, 'children': list(children)}


def _payload(root, **features):
    payload = {'meta': {'name': 'x'}, 'format': 'node_tree', 'data': root}
    payload.update(features)
    return payload


@tagged('post_install', '-at_install')
class TestSaveLock(TransactionCase):

    def setUp(self):
        super().setUp()
        self.workbook = self.env['xmind.workbook'].create({'name': 'Lock WB'})
        self.sheet = self.env['xmind.sheet'].create({
            'workbook_id': self.workbook.id, 'name': 'S1'})
        self.tree = _node('root', 'Root', [_node('a', 'A'), _node('b', 'B')])
        self.save(self.tree)

    def save(self, root, **kw):
        kw.setdefault('sheet_id', self.sheet.id)
        return self.workbook.save_mindmap_data(_payload(root), **kw)

    def topic(self, cid):
        return self.env['xmind.topic'].search(
            [('sheet_id', '=', self.sheet.id), ('component_id', '=', cid)])

    # ---------------------------------------------------------------- compat
    def test_without_digest_last_writer_still_wins(self):
        """舊行為：不帶 base_digest → 不比對，後存者覆蓋（向後相容的底線）。"""
        self.topic('a').title = 'changed elsewhere'
        self.save(_node('root', 'Root', [_node('a', 'A stale copy'), _node('b', 'B')]))
        self.assertEqual(self.topic('a').title, 'A stale copy')

    def test_empty_digest_is_treated_as_absent(self):
        self.topic('a').title = 'changed elsewhere'
        self.save(_node('root', 'Root', [_node('a', 'late'), _node('b', 'B')]), base_digest='')
        self.assertEqual(self.topic('a').title, 'late')
        self.save(_node('root', 'Root', [_node('a', 'late2'), _node('b', 'B')]), base_digest=None)
        self.assertEqual(self.topic('a').title, 'late2')

    def test_revision_restore_ignores_the_lock(self):
        """還原版本走 save_mindmap_data 且不帶摘要 —— 照舊可以覆蓋。"""
        revision = self.workbook.revision_ids[:1]
        self.topic('a').title = 'later'
        revision.action_restore()
        self.assertEqual(self.topic('a').title, 'A')

    # ------------------------------------------------------------------ lock
    def test_matching_digest_saves(self):
        digest = self.sheet._content_digest()
        self.save(_node('root', 'Root', [_node('a', 'A2'), _node('b', 'B')]), base_digest=digest)
        self.assertEqual(self.topic('a').title, 'A2')
        self.assertNotEqual(self.sheet._content_digest(), digest)

    def test_stale_digest_is_refused_and_nothing_is_written(self):
        digest = self.sheet._content_digest()
        self.topic('a').title = 'edited by someone else'   # 別人改了
        before = self.sheet._content_digest()
        with self.assertRaises(XmindConflict) as caught:
            self.save(_node('root', 'Root', [_node('a', 'my stale copy'), _node('b', 'B'),
                                             _node('c', 'new from stale tab')]),
                      base_digest=digest)
        self.assertEqual(caught.exception.current_digest, before)
        self.assertEqual(self.topic('a').title, 'edited by someone else')
        self.assertFalse(self.topic('c'), '衝突時不得有任何寫入')
        self.assertEqual(self.sheet._content_digest(), before)

    def test_save_then_apply_order_edit_after_save(self):
        """先存、後面才有人改（模擬助理套用）：之後拿舊摘要存檔必須被擋。"""
        loaded = self.sheet._content_digest()
        self.save(_node('root', 'Root', [_node('a', 'A'), _node('b', 'B')]), base_digest=loaded)
        saved = self.sheet._content_digest()
        self.topic('b').write({'title': 'B by assistant'})
        with self.assertRaises(XmindConflict):
            self.save(_node('root', 'Root', [_node('a', 'A'), _node('b', 'B')]), base_digest=saved)
        self.assertEqual(self.topic('b').title, 'B by assistant')

    def test_conflict_is_a_user_error(self):
        """舊的呼叫端 `except UserError` 仍能接住，不會變成 500。"""
        from odoo.exceptions import UserError
        self.assertTrue(issubclass(XmindConflict, UserError))

    # ---------------------------------------------------------------- digest
    def test_digest_is_deterministic(self):
        self.assertEqual(self.sheet._content_digest(), self.sheet._content_digest())

    def test_digest_ignores_expanded_and_sequence_normalisation(self):
        digest = self.sheet._content_digest()
        self.topic('a').expanded = False
        self.assertEqual(self.sheet._content_digest(), digest, '收合／展開只是檢視狀態')
        # 把 sequence 重排成 10、20（相對順序不變）不應改變摘要
        self.topic('a').sequence, self.topic('b').sequence = 10, 20
        self.assertEqual(self.sheet._content_digest(), digest)

    def test_digest_changes_on_each_kind_of_edit(self):
        seen = {self.sheet._content_digest()}

        def changed(label):
            digest = self.sheet._content_digest()
            self.assertNotIn(digest, seen, label)
            seen.add(digest)

        self.topic('a').title = 'renamed'
        changed('標題')
        self.topic('a').note = 'a note'
        changed('備註')
        self.topic('a').background_color = '#ff0000'
        changed('樣式')
        self.topic('b').sequence = -5          # b 排到 a 前面
        changed('同層順序')
        self.env['xmind.topic'].create({
            'sheet_id': self.sheet.id, 'parent_id': self.topic('a').id, 'title': 'child'})
        changed('新增節點')
        self.env['xmind.relationship'].create({
            'sheet_id': self.sheet.id, 'source_topic_id': self.topic('a').id,
            'target_topic_id': self.topic('b').id})
        changed('特徵層')

    def test_digest_is_per_sheet(self):
        other = self.env['xmind.sheet'].create({'workbook_id': self.workbook.id, 'name': 'S2'})
        mine = self.sheet._content_digest()
        self.env['xmind.topic'].create({'sheet_id': other.id, 'title': 'only in S2'})
        self.assertEqual(self.sheet._content_digest(), mine)

    # ------------------------------------------------------------- preview
    def test_preview_nodes_never_become_topics(self):
        """第二道防線：就算前端漏了，帶 ``_aiPreview`` 的節點也不入庫（連同其子孫）。"""
        tree = _node('root', 'Root', [
            _node('a', 'A'),
            _node('p1', 'ghost', [_node('p2', 'ghost child')], data={'_aiPreview': 'add'}),
            _node('b', 'B'),
        ])
        self.save(tree)
        titles = sorted(self.sheet.topic_ids.mapped('title'))
        self.assertEqual(titles, ['A', 'B', 'Root'])
        self.assertFalse(self.topic('p1') or self.topic('p2'))
        # 順序也不受影響（預覽節點不佔位）
        order = [t.component_id for t in
                 self.topic('root').child_ids.sorted(lambda t: (t.sequence, t.id))]
        self.assertEqual(order, ['a', 'b'])

    def test_non_preview_save_unchanged(self):
        self.save(_node('root', 'Root', [_node('a', 'A', data={'note': 'n'}), _node('b', 'B')]))
        self.assertEqual(self.topic('a').note, 'n')


@tagged('post_install', '-at_install')
class TestSaveLockRoute(HttpCase):
    """走真的路由：``/save`` 的回應形狀與 ``/data`` 的新增欄位。"""

    def setUp(self):
        super().setUp()
        self.user = new_test_user(self.env, login='xm_lock', password='xm_lock',
                                  groups='base.group_user')
        self.workbook = self.env['xmind.workbook'].with_user(self.user).create({'name': 'Route WB'})
        self.sheet = self.env['xmind.sheet'].with_user(self.user).create({
            'workbook_id': self.workbook.id, 'name': 'S1'})
        self.workbook.with_user(self.user).save_mindmap_data(
            _payload(_node('root', 'Root', [_node('a', 'A')])), sheet_id=self.sheet.id)
        self.env.cr.flush()
        self.authenticate('xm_lock', 'xm_lock')

    def rpc(self, path, params):
        return self.make_jsonrpc_request(path, params)

    def test_data_carries_digest_and_sheet_id(self):
        res = self.rpc('/xmind/workbook/%s/data' % self.workbook.id, {})
        self.assertEqual(res['sheet_id'], self.sheet.id)
        self.assertEqual(res['digest'], self.sheet.with_user(self.user)._content_digest())
        res2 = self.rpc('/xmind/workbook/%s/sheet/%s/data' % (self.workbook.id, self.sheet.id), {})
        self.assertEqual(res2['digest'], res['digest'])

    def test_save_roundtrip_and_conflict_shape(self):
        data = self.rpc('/xmind/workbook/%s/data' % self.workbook.id, {})
        tree = _payload(_node('root', 'Root', [_node('a', 'A edited')]))
        ok = self.rpc('/xmind/workbook/%s/save' % self.workbook.id, {
            'data': tree, 'sheet_id': data['sheet_id'], 'base_digest': data['digest']})
        self.assertTrue(ok['success'])
        self.assertTrue(ok['digest'] and ok['digest'] != data['digest'])
        # 用舊摘要再存 → 衝突、不覆蓋，並附目前摘要
        stale = self.rpc('/xmind/workbook/%s/save' % self.workbook.id, {
            'data': _payload(_node('root', 'Root', [_node('a', 'stale')])),
            'sheet_id': data['sheet_id'], 'base_digest': data['digest']})
        self.assertTrue(stale.get('conflict'))
        self.assertEqual(stale['digest'], ok['digest'])
        self.assertIn('error', stale)
        self.env.invalidate_all()
        title = self.env['xmind.topic'].search(
            [('sheet_id', '=', self.sheet.id), ('component_id', '=', 'a')]).title
        self.assertEqual(title, 'A edited')

    def test_old_client_without_digest_behaves_as_before(self):
        res = self.rpc('/xmind/workbook/%s/save' % self.workbook.id, {
            'data': _payload(_node('root', 'Root', [_node('a', 'old client')])),
            'sheet_id': self.sheet.id})
        self.assertTrue(res['success'])
        self.assertNotIn('conflict', res)
        self.env.invalidate_all()
        self.assertEqual(self.env['xmind.topic'].search(
            [('sheet_id', '=', self.sheet.id), ('component_id', '=', 'a')]).title, 'old client')
