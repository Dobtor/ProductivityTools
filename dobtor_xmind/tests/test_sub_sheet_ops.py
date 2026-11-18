# -*- coding: utf-8 -*-
"""子心智圖操作（Phase 3）與 .xmind 子圖往返（Phase 4）。

每個操作都要斷言：專案任務（id、專案、父任務、狀態、階段、名稱、啟用）一筆都沒變。
"""
import base64

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestSubSheetOps(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Workbook = cls.env['xmind.workbook']
        cls.Sheet = cls.env['xmind.sheet']
        cls.Topic = cls.env['xmind.topic']
        cls.Task = cls.env['project.task']

    def _make(self, sync=True):
        wb = self.Workbook.create({'name': 'Ops'})
        main = self.Sheet.create({'workbook_id': wb.id, 'name': 'Main', 'sequence': 1})
        T = lambda title, parent, seq=0, **kw: self.Topic.create(dict(
            {'sheet_id': main.id, 'title': title, 'parent_id': parent.id if parent else False,
             'sequence': seq}, **kw))
        root = T('Ops', None)
        a = T('A', root, 0)
        a1 = T('A1', a, 0, note='keep me')
        a2 = T('A2', a, 1, task_progress=40)
        a2a = T('A2a', a2, 0)
        b = T('B', root, 1)
        marker = self.env['xmind.marker'].search([], limit=1)
        if marker:
            self.env['xmind.topic.marker'].create({'topic_id': a1.id, 'marker_id': marker.id})
        self.env['xmind.attachment'].create({
            'topic_id': a2a.id, 'name': 'f.txt', 'file': base64.b64encode(b'x')})
        self.env['xmind.callout'].create({'topic_id': a1.id, 'title': 'Callout'})
        Rel = self.env['xmind.relationship']
        inside = Rel.create({'sheet_id': main.id, 'source_topic_id': a1.id,
                             'target_topic_id': a2a.id})
        crossing = Rel.create({'sheet_id': main.id, 'source_topic_id': a1.id,
                               'target_topic_id': b.id})
        boundary = self.env['xmind.boundary'].create({
            'sheet_id': main.id, 'topic_ids': [(6, 0, [a1.id, a2.id])]})
        summary = self.env['xmind.summary'].create({
            'sheet_id': main.id, 'topic_ids': [(6, 0, [a1.id, a2.id])]})
        if sync:
            wb._sync_to_project(create_if_missing=True)
        return dict(wb=wb, main=main, root=root, a=a, a1=a1, a2=a2, a2a=a2a, b=b,
                    inside=inside, crossing=crossing, boundary=boundary, summary=summary)

    def _task_snapshot(self, wb):
        tasks = self.Task.with_context(active_test=False).search(
            [('project_id', '=', wb.project_id.id)])
        return {t.id: (t.project_id.id, t.parent_id.id, t.state, t.stage_id.id, t.name,
                       t.active, t.xmind_topic_id.id, t.sequence) for t in tasks}

    # ----- 延伸 -----
    def test_extend_creates_empty_sub_sheet(self):
        d = self._make()
        before = self._task_snapshot(d['wb'])
        res = d['wb'].action_create_sub_sheets([d['a'].id], 'extend', names={str(d['a'].id): 'Detail'})
        self.assertEqual(len(res['created']), 1)
        sub = self.Sheet.browse(res['created'][0])
        self.assertEqual(sub.sheet_role, 'sub')
        self.assertEqual(sub.anchor_topic_id, d['a'])
        self.assertEqual(sub.name, 'Detail')
        self.assertEqual(sub.layout_type, 'logic_right')
        root = sub._get_root_topic()
        self.assertEqual(root.title, 'A')
        self.assertTrue(root._is_sub_sheet_proxy_root())
        self.assertEqual(len(sub.topic_ids), 1)
        self.assertEqual(d['a'].child_ids, d['a1'] | d['a2'])
        self.assertEqual(self._task_snapshot(d['wb']), before)
        # 第二次：已有分頁 → existing
        res2 = d['wb'].action_create_sub_sheets([d['a'].component_id], 'extend',
                                                sheet_id=d['main'].id)
        self.assertFalse(res2['created'])
        self.assertEqual(res2['existing'][0]['sheet_id'], sub.id)

    def test_split_moves_subtree_with_features(self):
        d = self._make()
        before = self._task_snapshot(d['wb'])
        tasks_before = {t.title: t.task_id.id for t in (d['a1'], d['a2'], d['a2a'])}
        res = d['wb'].action_create_sub_sheets([d['a'].id], 'split', layout='tree_right')
        sub = self.Sheet.browse(res['created'][0])
        proxy = sub._get_root_topic()
        self.assertEqual(sub.layout_type, 'tree_right')
        self.assertEqual(proxy.child_ids, d['a1'] | d['a2'])
        self.assertEqual(d['a2a'].sheet_id, sub)
        self.assertEqual(d['a2a'].parent_id, d['a2'])
        self.assertFalse(d['a'].child_ids)
        # 標記／備註／附件／標註跟著主題
        self.assertEqual(d['a1'].note, 'keep me')
        self.assertEqual(len(d['a2a'].attachment_ids), 1)
        self.assertTrue(self.env['xmind.callout'].search([('topic_id', '=', d['a1'].id)]))
        # 關聯線：完全在內 → 搬；跨界 → 刪
        self.assertEqual(d['inside'].sheet_id, sub)
        self.assertFalse(d['crossing'].exists())
        self.assertEqual(res['dropped']['relationships'], 1)
        self.assertEqual(d['boundary'].sheet_id, sub)
        self.assertEqual(d['summary'].sheet_id, sub)
        # 任務一筆都沒變
        self.assertEqual(self._task_snapshot(d['wb']), before)
        self.assertEqual({t.title: t.task_id.id for t in (d['a1'], d['a2'], d['a2a'])},
                         tasks_before)
        # 之後再同步：不新建、不封存，任務仍掛在 A 的任務下
        stats = d['wb']._sync_to_project()
        self.assertEqual((stats['created'], stats['removed']), (0, 0))
        self.assertEqual(d['a1'].task_id.parent_id, d['a'].task_id)

    def test_refusals(self):
        d = self._make()
        idea = self.Sheet.create({'workbook_id': d['wb'].id, 'name': 'Idea'})
        idea_root = self.Topic.create({'sheet_id': idea.id, 'title': 'I'})
        idea_child = self.Topic.create({'sheet_id': idea.id, 'parent_id': idea_root.id,
                                        'title': 'IC'})
        with self.assertRaises(UserError):
            d['wb'].action_create_sub_sheets([d['root'].id], 'extend')
        with self.assertRaises(UserError):
            d['wb'].action_create_sub_sheets([idea_child.id], 'extend')
        res = d['wb'].action_create_sub_sheets([d['root'].id, d['b'].id], 'extend')
        self.assertEqual(len(res['created']), 1)
        self.assertEqual(res['skipped'][0]['title'], 'Ops')
        # 深度：主圖 → 1 → 2 → 3，第 4 層拒絕
        anchor = d['a']
        for _level in range(3):
            res = d['wb'].action_create_sub_sheets([anchor.id], 'extend')
            sheet = self.Sheet.browse(res['created'][0])
            anchor = self.Topic.create({'sheet_id': sheet.id, 'title': 'deeper',
                                        'parent_id': sheet._get_root_topic().id})
        with self.assertRaises(UserError):
            d['wb'].action_create_sub_sheets([anchor.id], 'extend')

    def test_split_refuses_when_nested_anchor_would_exceed_depth(self):
        d = self._make(sync=False)
        anchor = d['a2']
        for _level in range(3):
            sheet = self.Sheet.browse(
                d['wb'].action_create_sub_sheets([anchor.id], 'extend')['created'][0])
            anchor = self.Topic.create({'sheet_id': sheet.id, 'title': 'x',
                                        'parent_id': sheet._get_root_topic().id})
        # A2 已帶三層子圖；拆出 A 會讓它們各往下沉一層 → 拒絕
        with self.assertRaises(UserError):
            d['wb'].action_create_sub_sheets([d['a'].id], 'split')
        self.assertEqual(d['a2'].sheet_id, d['main'])

    def test_merge_back(self):
        d = self._make()
        before = self._task_snapshot(d['wb'])
        sub = self.Sheet.browse(
            d['wb'].action_create_sub_sheets([d['a'].id], 'split')['created'][0])
        extra = self.Topic.create({'sheet_id': sub.id, 'title': 'New in sub',
                                   'parent_id': sub._get_root_topic().id, 'sequence': 9})
        res = d['wb'].action_merge_sub_sheet(sub.id)
        self.assertFalse(sub.exists())
        self.assertEqual(res['target_sheet_id'], d['main'].id)
        self.assertEqual(d['a'].child_ids, d['a1'] | d['a2'] | extra)
        self.assertEqual(d['a2a'].sheet_id, d['main'])
        self.assertEqual(d['inside'].sheet_id, d['main'])
        self.assertEqual(d['boundary'].sheet_id, d['main'])
        self.assertEqual(self._task_snapshot(d['wb']), before)
        with self.assertRaises(UserError):
            d['wb'].action_merge_sub_sheet(d['main'].id)

    def test_attach_idea_sheet(self):
        d = self._make()
        before = self._task_snapshot(d['wb'])
        idea = self.Sheet.create({'workbook_id': d['wb'].id, 'name': 'Brainstorm'})
        idea_root = self.Topic.create({'sheet_id': idea.id, 'title': 'Idea root'})
        idea_child = self.Topic.create({'sheet_id': idea.id, 'parent_id': idea_root.id,
                                        'title': 'Idea 1'})
        d['wb'].action_attach_idea_sheet(idea.id, d['b'].id)
        self.assertEqual(idea.sheet_role, 'sub')
        self.assertEqual(idea.anchor_topic_id, d['b'])
        self.assertEqual(idea_root.title, 'B', "代理中心主題顯示錨點標題")
        self.assertEqual(d['b'].title, 'B', "錨點標題不被發想頁的中心主題蓋掉")
        self.assertEqual(idea_child.parent_id, idea_root)
        self.assertEqual(self._task_snapshot(d['wb']), before)
        with self.assertRaises(UserError):   # 已是子圖
            d['wb'].action_attach_idea_sheet(idea.id, d['a'].id)
        idea2 = self.Sheet.create({'workbook_id': d['wb'].id, 'name': 'Idea 2'})
        self.Topic.create({'sheet_id': idea2.id, 'title': 'x'})
        with self.assertRaises(UserError):   # 錨點已有子圖
            d['wb'].action_attach_idea_sheet(idea2.id, d['b'].id)
        with self.assertRaises(UserError):   # 中心主題
            d['wb'].action_attach_idea_sheet(idea2.id, d['root'].id)

    def test_move_topics_to_sheet(self):
        d = self._make()
        before = self._task_snapshot(d['wb'])
        sub = self.Sheet.browse(
            d['wb'].action_create_sub_sheets([d['b'].id], 'extend')['created'][0])
        # A（含子孫）搬進 B 的子圖：跨界的 A1→B 關聯線被刪
        res = d['wb'].move_topics_to_sheet([d['a'].id, d['a1'].id], sub.id)
        self.assertEqual(res['moved'], 4)   # A、A1、A2、A2a
        self.assertEqual(d['a'].sheet_id, sub)
        self.assertEqual(d['a'].parent_id, sub._get_root_topic())
        self.assertEqual(d['a2a'].sheet_id, sub)
        self.assertEqual(res['dropped']['relationships'], 1)
        self.assertEqual(d['inside'].sheet_id, sub)
        self.assertEqual(self._task_snapshot(d['wb']), before)
        # 指定父主題（同一張分頁內搬移）
        d['wb'].move_topics_to_sheet([d['a2a'].component_id], sub.id, d['a1'].component_id,
                                     sheet_id=sub.id)
        self.assertEqual(d['a2a'].parent_id, d['a1'])
        # 錨點不能搬進自己的子圖；中心主題不能搬；不能搬到自己底下
        with self.assertRaises(UserError):
            d['wb'].move_topics_to_sheet([d['b'].id], sub.id)
        with self.assertRaises(UserError):
            d['wb'].move_topics_to_sheet([d['root'].id], sub.id)
        with self.assertRaises(UserError):
            d['wb'].move_topics_to_sheet([d['a'].id], sub.id, d['a1'].id)
        self.assertEqual(self._task_snapshot(d['wb']), before)

    def test_badge(self):
        d = self._make()
        sub = self.Sheet.browse(
            d['wb'].action_create_sub_sheets([d['a'].id], 'split')['created'][0])
        from odoo.addons.dobtor_xmind.controllers.main import MindMapController
        from types import SimpleNamespace
        from unittest.mock import patch
        ctrl = MindMapController()
        with patch('odoo.addons.dobtor_xmind.controllers.main.request',
                   new=SimpleNamespace(env=self.env)):
            badge = ctrl._sub_sheet_badge(sub)
            data = ctrl._sheet_mindmap_data(d['wb'], d['main'])
        self.assertEqual(badge['count'], 3)    # A1、A2、A2a
        self.assertEqual(badge['progress'], round(40 / 3))   # 三顆都連了任務，只有 A2 有進度
        node_a = next(c for c in data['data']['children'] if c['id'] == d['a'].component_id)
        self.assertEqual(node_a['data']['subSheet']['id'], sub.id)
