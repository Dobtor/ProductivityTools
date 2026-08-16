# -*- coding: utf-8 -*-
"""存檔改為「差異更新」之後的行為契約。

舊作法每次存檔都把整棵樹 ``unlink()`` 再重建，於是**每顆主題的資料庫 id
每次存檔都會換一批**。任何指向 ``xmind.topic`` 的外部參考都會斷 —— 目前只有
``project.task.xmind_topic_id``，而它是靠 payload 裡的 ``taskId`` 事後重新接
回來才沒斷；新增任何其他關聯欄位都會靜默失聯。

現在改成以 ``component_id`` 對帳（它在前後端之間是完整往返的）：對得上就
``write``，對不上才 ``create``，payload 沒提到的才刪。這組測試釘死的就是
「id 穩定」這個新契約，以及對帳本身不能製造出重複、殘留或迴圈。
"""
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestDiffSave(TransactionCase):

    def setUp(self):
        super().setUp()
        self.Topic = self.env['xmind.topic']
        self.workbook = self.env['xmind.workbook'].create({'name': 'Diff WB'})
        self.sheet = self.env['xmind.sheet'].create({
            'workbook_id': self.workbook.id, 'name': 'S1',
        })

    # ------------------------------------------------------------------ utils
    def _node(self, cid, title, children=(), data=None):
        return {
            'id': cid, 'topic': title, 'expanded': True,
            'data': data or {}, 'children': list(children),
        }

    def _save(self, root):
        self.workbook.save_mindmap_data(
            {'meta': {'name': 'x'}, 'format': 'node_tree', 'data': root},
            sheet_id=self.sheet.id,
        )
        self.sheet.invalidate_recordset(['topic_ids'])

    def _by_cid(self):
        return {t.component_id: t for t in self.sheet.topic_ids}

    # ------------------------------------------------------------------ tests
    def test_topic_ids_are_stable_across_saves(self):
        """同一份樹存兩次，主題的資料庫 id 不可以變 —— 這是整個改動的重點。"""
        tree = self._node('root', 'Root', [
            self._node('a', 'A'), self._node('b', 'B'),
        ])
        self._save(tree)
        first = {cid: t.id for cid, t in self._by_cid().items()}
        self.assertEqual(set(first), {'root', 'a', 'b'})

        self._save(tree)
        second = {cid: t.id for cid, t in self._by_cid().items()}
        self.assertEqual(first, second, "存檔後主題的資料庫 id 被換掉了")

    def test_rename_updates_in_place(self):
        self._save(self._node('root', 'Root', [self._node('a', 'A')]))
        topic_id = self._by_cid()['a'].id

        self._save(self._node('root', 'Root', [self._node('a', 'A renamed')]))
        topic = self._by_cid()['a']
        self.assertEqual(topic.id, topic_id, "改名不該重建主題")
        self.assertEqual(topic.title, 'A renamed')

    def test_added_topic_only_creates_that_one(self):
        self._save(self._node('root', 'Root', [self._node('a', 'A')]))
        before = {cid: t.id for cid, t in self._by_cid().items()}

        self._save(self._node('root', 'Root', [
            self._node('a', 'A'), self._node('b', 'B'),
        ]))
        after = self._by_cid()
        self.assertEqual(after['root'].id, before['root'])
        self.assertEqual(after['a'].id, before['a'])
        self.assertNotIn('b', before)
        self.assertIn('b', after)

    def test_removed_topic_is_deleted_with_its_subtree(self):
        self._save(self._node('root', 'Root', [
            self._node('a', 'A', [self._node('a1', 'A1')]),
            self._node('b', 'B'),
        ]))
        self.assertEqual(len(self.sheet.topic_ids), 4)

        # 拿掉 A（連同 A1）
        self._save(self._node('root', 'Root', [self._node('b', 'B')]))
        self.assertEqual(set(self._by_cid()), {'root', 'b'})

    def test_reparent(self):
        """把 A1 從 A 底下搬到 B 底下。"""
        self._save(self._node('root', 'Root', [
            self._node('a', 'A', [self._node('a1', 'A1')]),
            self._node('b', 'B'),
        ]))
        moved_id = self._by_cid()['a1'].id

        self._save(self._node('root', 'Root', [
            self._node('a', 'A'),
            self._node('b', 'B', [self._node('a1', 'A1')]),
        ]))
        topic = self._by_cid()['a1']
        self.assertEqual(topic.id, moved_id, "搬家不該重建主題")
        self.assertEqual(topic.parent_id.component_id, 'b')

    def test_parent_child_swap_does_not_raise(self):
        """把父子關係整個顛倒過來 —— 對帳若順序錯了會觸發 Odoo 的迴圈偵測。

        由上而下寫入時，每個節點的**新**祖先鏈都已經先寫好了，所以任何一步
        都不會短暫形成環。這個測試就是在釘死那個順序。
        """
        self._save(self._node('root', 'Root', [
            self._node('a', 'A', [self._node('b', 'B', [self._node('c', 'C')])]),
        ]))
        ids = {cid: t.id for cid, t in self._by_cid().items()}

        # root → C → B → A
        self._save(self._node('root', 'Root', [
            self._node('c', 'C', [self._node('b', 'B', [self._node('a', 'A')])]),
        ]))
        after = self._by_cid()
        self.assertEqual({cid: t.id for cid, t in after.items()}, ids, "顛倒層級不該重建主題")
        self.assertEqual(after['b'].parent_id.component_id, 'c')
        self.assertEqual(after['a'].parent_id.component_id, 'b')

    def test_sequence_follows_payload_order(self):
        self._save(self._node('root', 'Root', [
            self._node('a', 'A'), self._node('b', 'B'), self._node('c', 'C'),
        ]))
        # 反序存回去
        self._save(self._node('root', 'Root', [
            self._node('c', 'C'), self._node('b', 'B'), self._node('a', 'A'),
        ]))
        root = self._by_cid()['root']
        self.assertEqual(root.child_ids.mapped('component_id'), ['c', 'b', 'a'])

    def test_markers_do_not_accumulate(self):
        """標記是「整組取代」：連存兩次不可以疊加。"""
        marker = self.env['xmind.marker'].search([], limit=1)
        if not marker:
            self.skipTest("沒有可用的 xmind.marker 主檔資料")
        node = self._node('a', 'A', data={'markers': [marker.code]})
        tree = self._node('root', 'Root', [node])

        self._save(tree)
        self.assertEqual(len(self._by_cid()['a'].marker_ids), 1)
        self._save(tree)
        self.assertEqual(len(self._by_cid()['a'].marker_ids), 1, "標記被疊加了")

    def test_attachments_do_not_accumulate(self):
        """附件同樣是整組取代。"""
        img = {'data': 'data:image/png;base64,aGVsbG8=', 'options': {}}
        tree = self._node('root', 'Root', [self._node('a', 'A', data={'image': img})])

        self._save(tree)
        self.assertEqual(len(self._by_cid()['a'].attachment_ids), 1)
        self._save(tree)
        self.assertEqual(len(self._by_cid()['a'].attachment_ids), 1, "附件被疊加了")

    def test_duplicate_component_id_does_not_hijack(self):
        """payload 裡出現重複的 component_id 時，不可以把既有主題搬走。

        正常操作不會產生重複（貼上一律給新 id），但壞掉的 payload 不該造成
        「一顆主題同時出現在兩個位置」這種靜默的結構破壞。
        """
        self._save(self._node('root', 'Root', [
            self._node('dup', 'First'), self._node('dup', 'Second'),
        ]))
        root = self._by_cid()['root']
        self.assertEqual(len(root.child_ids), 2, "重複 id 讓其中一顆主題消失了")
        self.assertEqual(root.child_ids.mapped('title'), ['First', 'Second'])
        cids = root.child_ids.mapped('component_id')
        self.assertEqual(len(set(cids)), 2, "重複的 component_id 沒有被拆開")

    def test_topics_without_component_id_are_cleaned_up(self):
        """手動建立、沒有 component_id 的殘留主題會被這次存檔清掉。"""
        self._save(self._node('root', 'Root'))
        self.Topic.create({
            'sheet_id': self.sheet.id, 'title': 'Orphan', 'component_id': False,
        })
        self.sheet.invalidate_recordset(['topic_ids'])
        self.assertEqual(len(self.sheet.topic_ids), 2)

        self._save(self._node('root', 'Root'))
        self.assertEqual(set(self._by_cid()), {'root'})

    def test_project_task_link_survives_across_saves(self):
        """任務關聯跨存檔存活，且主題 id 不變。

        這是差異更新最實際的好處：舊作法下主題會被刪掉重建，
        ``project.task.xmind_topic_id`` 只能靠 payload 裡的 taskId 重新接回；
        新增任何其他指向主題的關聯欄位都會在存檔後靜默斷掉。
        """
        project = self.env['project.project'].create({'name': 'P'})
        task = self.env['project.task'].create({'name': 'T', 'project_id': project.id})

        self._save(self._node('root', 'Root', [self._node('a', 'A')]))
        topic = self._by_cid()['a']
        topic.task_id = task.id
        task.xmind_topic_id = topic.id

        # 編輯器的 payload 會帶 taskId（見 _topic_to_jsmind）
        self._save(self._node('root', 'Root', [
            self._node('a', 'A', data={'taskId': task.id}),
        ]))
        after = self._by_cid()['a']
        task.invalidate_recordset(['xmind_topic_id'])
        self.assertEqual(after.id, topic.id, "存檔後主題被重建了")
        self.assertEqual(after.task_id.id, task.id)
        self.assertEqual(task.xmind_topic_id.id, topic.id, "任務與主題的關聯斷了")

    def test_unlinking_task_clears_both_sides(self):
        """在編輯器裡拿掉任務關聯 → 兩個方向都要清乾淨。

        `topic.task_id` 與 `task.xmind_topic_id` 是兩個各自獨立的 M2O。舊作法
        每次存檔都刪掉主題重建，兩邊剛好都歸零；改成差異更新後主題會存活，
        必須明確清除，否則關聯永遠拿不掉。
        """
        project = self.env['project.project'].create({'name': 'P'})
        task = self.env['project.task'].create({'name': 'T', 'project_id': project.id})

        self._save(self._node('root', 'Root', [
            self._node('a', 'A', data={'taskId': task.id}),
        ]))
        topic = self._by_cid()['a']
        self.assertEqual(topic.task_id.id, task.id)
        task.invalidate_recordset(['xmind_topic_id'])
        self.assertEqual(task.xmind_topic_id.id, topic.id)

        # payload 不再帶 taskId
        self._save(self._node('root', 'Root', [self._node('a', 'A')]))
        topic = self._by_cid()['a']
        task.invalidate_recordset(['xmind_topic_id'])
        self.assertFalse(topic.task_id, "topic.task_id 沒有被清掉")
        self.assertFalse(task.xmind_topic_id, "反向的 task.xmind_topic_id 沒有被清掉")

    def test_project_managed_flag_can_be_turned_off(self):
        """projectManaged 同理：payload 說了算，不是「有值才設」。"""
        self._save(self._node('root', 'Root', [
            self._node('a', 'A', data={'projectManaged': True}),
        ]))
        self.assertTrue(self._by_cid()['a'].project_managed)

        self._save(self._node('root', 'Root', [self._node('a', 'A')]))
        self.assertFalse(self._by_cid()['a'].project_managed,
                         "projectManaged 關不掉")
