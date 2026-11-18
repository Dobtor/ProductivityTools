# -*- coding: utf-8 -*-
"""分頁角色（主圖／子圖／發想頁）與跨分頁同步（Phase 2）。"""
import importlib.util
import os

from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged
from odoo.tools import mute_logger


@tagged('post_install', '-at_install')
class TestSubSheets(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Workbook = cls.env['xmind.workbook']
        cls.Sheet = cls.env['xmind.sheet']
        cls.Topic = cls.env['xmind.topic']
        cls.Project = cls.env['project.project']
        cls.Task = cls.env['project.task']

    def _make(self):
        wb = self.Workbook.create({'name': 'WB'})
        main = self.Sheet.create({'workbook_id': wb.id, 'name': 'Main', 'sequence': 1})
        root = self.Topic.create({'sheet_id': main.id, 'title': 'Root'})
        anchor = self.Topic.create({'sheet_id': main.id, 'parent_id': root.id,
                                    'title': 'Anchor', 'sequence': 0})
        local = self.Topic.create({'sheet_id': main.id, 'parent_id': anchor.id,
                                   'title': 'Local child', 'sequence': 0})
        sub = self.Sheet.create({'workbook_id': wb.id, 'name': 'Sub', 'sequence': 2})
        sub_root = self.Topic.create({'sheet_id': sub.id, 'title': 'Anchor'})
        subs = [self.Topic.create({'sheet_id': sub.id, 'parent_id': sub_root.id,
                                   'title': 'S%d' % i, 'sequence': i}) for i in range(3)]
        sub.write({'sheet_role': 'sub', 'anchor_topic_id': anchor.id})
        return wb, main, root, anchor, local, sub, sub_root, subs

    # ----- 角色 -----
    def test_first_sheet_is_main_others_idea(self):
        wb = self.Workbook.create({'name': 'X'})
        s1 = self.Sheet.create({'workbook_id': wb.id, 'name': '1'})
        s2 = self.Sheet.create({'workbook_id': wb.id, 'name': '2'})
        self.assertEqual(s1.sheet_role, 'main')
        self.assertEqual(s2.sheet_role, 'idea')
        self.assertEqual(wb.main_sheet_id, s1)

    def test_save_creates_main_sheet(self):
        wb = self.Workbook.create({'name': 'Blank'})
        wb.save_mindmap_data({'data': {'id': 'r', 'topic': 'Blank', 'children': []}})
        self.assertEqual(wb.sheet_ids.sheet_role, 'main')

    def test_only_one_main(self):
        wb, main, *_ = self._make()
        idea = self.Sheet.create({'workbook_id': wb.id, 'name': 'Idea'})
        with self.assertRaises(ValidationError):
            idea.sheet_role = 'main'
        idea._set_as_main()
        self.assertEqual(wb.main_sheet_id, idea)
        self.assertEqual(main.sheet_role, 'idea')

    def test_sub_constraints(self):
        wb, main, root, anchor, local, sub, sub_root, subs = self._make()
        other_wb = self.Workbook.create({'name': 'Other'})
        other_sheet = self.Sheet.create({'workbook_id': other_wb.id, 'name': 'O'})
        other_topic = self.Topic.create({'sheet_id': other_sheet.id, 'title': 'O'})
        other_child = self.Topic.create({'sheet_id': other_sheet.id, 'parent_id': other_topic.id,
                                         'title': 'OC'})
        sub2 = self.Sheet.create({'workbook_id': wb.id, 'name': 'Sub2'})
        sub2_root = self.Topic.create({'sheet_id': sub2.id, 'title': 'x'})
        with self.assertRaises(ValidationError):   # 沒有錨點
            sub2.sheet_role = 'sub'
        with self.assertRaises(ValidationError):   # 別本工作簿
            sub2.write({'sheet_role': 'sub', 'anchor_topic_id': other_child.id})
        with self.assertRaises(ValidationError):   # 中心主題不可當錨點
            sub2.write({'sheet_role': 'sub', 'anchor_topic_id': root.id})
        # 成環：sub2 錨在 sub 的主題、sub 再改錨到 sub2 的主題
        child_in_sub2 = self.Topic.create({'sheet_id': sub2.id, 'parent_id': sub2_root.id,
                                           'title': 'c'})
        sub2.write({'sheet_role': 'sub', 'anchor_topic_id': subs[0].id})
        with self.assertRaises(ValidationError):
            sub.write({'anchor_topic_id': child_in_sub2.id})
        # 一顆主題最多一張子圖
        sub3 = self.Sheet.create({'workbook_id': wb.id, 'name': 'Sub3'})
        with self.assertRaises(Exception), mute_logger('odoo.sql_db'):
            with self.env.cr.savepoint():
                sub3.write({'sheet_role': 'sub', 'anchor_topic_id': anchor.id})

    def test_depth_limit(self):
        wb, main, root, anchor, local, sub, sub_root, subs = self._make()
        parent_topic = subs[0]
        for level in (2, 3):
            s = self.Sheet.create({'workbook_id': wb.id, 'name': 'L%d' % level})
            r = self.Topic.create({'sheet_id': s.id, 'title': 'r'})
            c = self.Topic.create({'sheet_id': s.id, 'parent_id': r.id, 'title': 'c%d' % level})
            s.write({'sheet_role': 'sub', 'anchor_topic_id': parent_topic.id})
            parent_topic = c
        s4 = self.Sheet.create({'workbook_id': wb.id, 'name': 'L4'})
        self.Topic.create({'sheet_id': s4.id, 'title': 'r'})
        with self.assertRaises(ValidationError):
            s4.write({'sheet_role': 'sub', 'anchor_topic_id': parent_topic.id})

    def test_anchor_cannot_be_deleted(self):
        wb, main, root, anchor, local, sub, sub_root, subs = self._make()
        with self.assertRaises(UserError):
            anchor.unlink()
        with self.assertRaises(UserError):
            main.unlink()
        # 整本一起刪不受影響
        wb.sheet_ids.unlink()
        self.assertFalse(wb.sheet_ids)

    def test_proxy_root_mirrors_anchor_title(self):
        wb, main, root, anchor, local, sub, sub_root, subs = self._make()
        anchor.title = 'Renamed anchor'
        self.assertEqual(sub_root.title, 'Renamed anchor')
        sub_root.title = 'From sub'
        self.assertEqual(anchor.title, 'From sub')
        self.assertEqual(anchor.sub_sheet_id, sub)
        self.assertEqual(sub.parent_sheet_id, main)
        # 子圖中心主題改名不會改到工作簿名稱
        self.assertEqual(wb.name, 'WB')

    # ----- 同步 -----
    def test_sub_sheet_topics_become_children_of_anchor_task(self):
        wb, main, root, anchor, local, sub, sub_root, subs = self._make()
        idea = self.Sheet.create({'workbook_id': wb.id, 'name': 'Idea'})
        idea_root = self.Topic.create({'sheet_id': idea.id, 'title': 'Idea'})
        idea_child = self.Topic.create({'sheet_id': idea.id, 'parent_id': idea_root.id,
                                        'title': 'Brainstorm'})
        wb._sync_to_project(create_if_missing=True)
        anchor_task = anchor.task_id
        self.assertTrue(anchor_task)
        self.assertFalse(sub_root.task_id, "子圖中心主題（代理）不可變成任務")
        self.assertFalse(idea_child.task_id, "發想頁不同步")
        self.assertFalse(idea_root.task_id)
        children = self.Task.search([('parent_id', '=', anchor_task.id)], order='sequence, id')
        self.assertEqual(children.mapped('name'), ['Local child', 'S0', 'S1', 'S2'])
        for t in subs:
            self.assertEqual(t.task_id.parent_id, anchor_task)
        self.assertEqual(self.Task.search_count([('project_id', '=', wb.project_id.id)]), 5)
        self.assertFalse(wb._plan_project_orphans())

    def test_moving_subtree_between_sheets_keeps_tasks(self):
        wb, main, root, anchor, local, sub, sub_root, subs = self._make()
        grandchild = self.Topic.create({'sheet_id': main.id, 'parent_id': local.id, 'title': 'GC'})
        wb._sync_to_project(create_if_missing=True)
        ids_before = {t.title: t.task_id.id for t in (local, grandchild) + tuple(subs)}
        # Local child（含子孫）從主圖搬到子圖；S2 從子圖搬回主圖根下
        (local | grandchild).write({'sheet_id': sub.id})
        local.parent_id = sub_root
        subs[2].write({'sheet_id': main.id, 'parent_id': root.id})
        stats = wb._sync_to_project()
        self.assertEqual(stats['created'], 0)
        self.assertEqual(stats['removed'], 0)
        ids_after = {t.title: t.task_id.id for t in (local, grandchild) + tuple(subs)}
        self.assertEqual(ids_before, ids_after)
        self.assertEqual(local.task_id.parent_id, anchor.task_id)
        self.assertFalse(subs[2].task_id.parent_id)
        self.assertEqual(grandchild.task_id.parent_id, local.task_id)

    def test_reverse_sync_places_child_of_anchor_into_sub_sheet(self):
        wb, main, root, anchor, local, sub, sub_root, subs = self._make()
        wb._sync_to_project(create_if_missing=True)
        project = wb.project_id
        new_task = self.Task.create({'name': 'From project', 'project_id': project.id,
                                     'parent_id': anchor.task_id.id})
        top_task = self.Task.create({'name': 'Top level', 'project_id': project.id})
        stats = project._sync_to_mindmap()
        topic = new_task.xmind_topic_id
        self.assertEqual(topic.sheet_id, sub)
        self.assertEqual(topic.parent_id, sub_root)
        self.assertEqual(top_task.xmind_topic_id.sheet_id, main)
        self.assertEqual(top_task.xmind_topic_id.parent_id, root)
        # 既有主題留在原分頁
        self.assertEqual(subs[0].sheet_id, sub)
        self.assertEqual(local.sheet_id, main)
        self.assertEqual(stats['removed'], 0)
        # 再同步一次：不重複、不搬家
        project._sync_to_mindmap()
        self.assertEqual(new_task.xmind_topic_id, topic)
        self.assertEqual(topic.sheet_id, sub)

    def test_reverse_sync_moves_topic_when_parent_changes(self):
        wb, main, root, anchor, local, sub, sub_root, subs = self._make()
        wb._sync_to_project(create_if_missing=True)
        project = wb.project_id
        s0_task = subs[0].task_id
        s0_child = self.Topic.create({'sheet_id': sub.id, 'parent_id': subs[0].id, 'title': 'deep'})
        s0_task.parent_id = False
        project._sync_to_mindmap()
        self.assertEqual(subs[0].sheet_id, main)
        self.assertEqual(subs[0].parent_id, root)
        self.assertEqual(s0_child.sheet_id, main, "子孫跟著一起換分頁")

    def test_sheet_routes_expose_role(self):
        wb, main, root, anchor, local, sub, sub_root, subs = self._make()
        from odoo.addons.dobtor_xmind.controllers.main import MindMapController
        meta = MindMapController()._get_sheet_meta(sub)
        self.assertEqual(meta['sheet_role'], 'sub')
        self.assertEqual(meta['anchor_topic_id'], anchor.id)
        self.assertEqual(meta['parent_sheet_id'], main.id)
        data = MindMapController()._apply_proxy_root(sub, {'topic': 'stale', 'data': {'taskId': 5}})
        self.assertEqual(data['topic'], 'Anchor')
        self.assertTrue(data['data']['_subSheetProxy'])
        self.assertNotIn('taskId', data['data'])

    # ----- 遷移 -----
    def test_post_migrate_backfill(self):
        path = os.path.join(os.path.dirname(__file__), '..', 'migrations', '18.0.4.0.0',
                            'post-migrate.py')
        spec = importlib.util.spec_from_file_location('xmind_post_migrate_4', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        # 由圖建立的專案（名稱＝中心主題）
        wb1 = self.Workbook.create({'name': 'Map One'})
        s1 = self.Sheet.create({'workbook_id': wb1.id, 'name': 'A', 'sequence': 5})
        self.Topic.create({'sheet_id': s1.id, 'title': 'Map One'})
        s1b = self.Sheet.create({'workbook_id': wb1.id, 'name': 'B', 'sequence': 1})
        r1b = self.Topic.create({'sheet_id': s1b.id, 'title': 'Map One'})
        self.Topic.create({'sheet_id': s1b.id, 'parent_id': r1b.id, 'title': 'T'})
        wb1._sync_to_project(create_if_missing=True)
        # 圖比專案早建立（實際上是兩個不同的請求；測試在同一個交易裡要手動拉開）
        self.env.flush_all()
        self.env.cr.execute("UPDATE xmind_workbook SET create_date = create_date - interval '1 minute' "
                            "WHERE id = %s", (wb1.id,))
        # 由專案反向建立的心智圖：專案較早 → 不算由圖建立
        rev = self.Project.create({'name': 'Reverse'})
        self.Task.create({'name': 'RT', 'project_id': rev.id})
        wb4 = self.Workbook.browse(rev._sync_to_mindmap(create_if_missing=True)['workbook_id'])
        self.env.flush_all()
        self.env.cr.execute("UPDATE project_project SET create_date = create_date - interval '1 minute' "
                            "WHERE id = %s", (rev.id,))
        # 既有專案
        proj = self.Project.create({'name': 'Existing'})
        wb2 = self.Workbook.create({'name': 'Map Two', 'project_id': proj.id})
        # 沒有分頁的工作簿
        wb3 = self.Workbook.create({'name': 'Empty'})
        task_snapshot = {t.id: (t.project_id.id, t.name, t.write_date)
                         for t in self.Task.search([])}
        self.env.flush_all()
        # 模擬升級前：角色全部是預設值、旗標未設
        self.env.cr.execute("UPDATE xmind_sheet SET sheet_role = 'idea'")
        self.env.cr.execute("UPDATE xmind_workbook SET main_sheet_id = NULL, "
                            "project_locked = FALSE, project_created_from_map = FALSE")
        self.env.invalidate_all()
        module.migrate(self.env.cr, '18.0.3.2.2')
        self.env.invalidate_all()
        # sequence 最小的那張成為主圖（不是 id 最小）
        self.assertEqual(s1b.sheet_role, 'main')
        self.assertEqual(s1.sheet_role, 'idea')
        self.assertEqual(wb1.main_sheet_id, s1b)
        self.assertTrue(wb1.project_locked)
        self.assertFalse(wb2.project_locked)
        self.assertFalse(wb3.main_sheet_id)
        self.assertTrue(wb1.project_created_from_map)
        self.assertFalse(wb2.project_created_from_map)
        self.assertFalse(wb4.project_created_from_map)
        self.assertTrue(wb4.project_locked)
        self.assertEqual({t.id: (t.project_id.id, t.name, t.write_date)
                          for t in self.Task.search([])}, task_snapshot)
