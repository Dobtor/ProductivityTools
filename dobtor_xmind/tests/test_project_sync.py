# -*- coding: utf-8 -*-
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestProjectSync(TransactionCase):

    def setUp(self):
        super().setUp()
        self.Workbook = self.env['xmind.workbook']
        self.Sheet = self.env['xmind.sheet']
        self.Topic = self.env['xmind.topic']
        self.Project = self.env['project.project']
        self.Task = self.env['project.task']

    def _make_workbook(self):
        wb = self.Workbook.create({'name': 'WB'})
        sheet = self.Sheet.create({'workbook_id': wb.id, 'name': 'S1'})
        root = self.Topic.create({'sheet_id': sheet.id, 'title': 'My Project'})
        a = self.Topic.create({'sheet_id': sheet.id, 'parent_id': root.id, 'title': 'A', 'sequence': 0})
        b = self.Topic.create({'sheet_id': sheet.id, 'parent_id': root.id, 'title': 'B', 'sequence': 1})
        a1 = self.Topic.create({'sheet_id': sheet.id, 'parent_id': a.id, 'title': 'A1', 'sequence': 0,
                                'task_progress': 100})
        return wb, sheet, root, a, b, a1

    # ----- forward (map → project) -----
    def test_create_project_builds_task_tree(self):
        wb, sheet, root, a, b, a1 = self._make_workbook()
        wb._sync_to_project(create_if_missing=True)
        self.assertTrue(wb.project_id, "project should be created and linked")
        self.assertEqual(wb.project_id.name, 'My Project')
        self.assertTrue(a.task_id and b.task_id and a1.task_id, "topics get linked tasks")
        # hierarchy: A1's task parent is A's task; A/B are top-level (no parent)
        self.assertEqual(a1.task_id.parent_id, a.task_id)
        self.assertFalse(a.task_id.parent_id)
        # progress 100 → state done
        self.assertEqual(a1.task_id.state, '1_done')
        self.assertEqual(wb.xmind_last_sync_direction, 'to_project')

    def test_resync_updates_without_duplicating(self):
        wb, sheet, root, a, b, a1 = self._make_workbook()
        wb._sync_to_project(create_if_missing=True)
        n_before = self.Task.search_count([('project_id', '=', wb.project_id.id)])
        a.title = 'A renamed'
        stats = wb._sync_to_project(create_if_missing=False)
        n_after = self.Task.search_count([('project_id', '=', wb.project_id.id)])
        self.assertEqual(n_before, n_after, "re-sync must not duplicate tasks")
        self.assertEqual(a.task_id.name, 'A renamed')
        self.assertEqual(stats['created'], 0)
        self.assertGreaterEqual(stats['updated'], 3)

    def test_removed_topic_archives_task(self):
        wb, sheet, root, a, b, a1 = self._make_workbook()
        wb._sync_to_project(create_if_missing=True)
        b_task = b.task_id
        b.unlink()
        wb._sync_to_project(create_if_missing=False)
        self.assertFalse(b_task.active, "task whose topic was removed must be archived")

    def test_plan_orphans_lists_archive_candidates(self):
        wb, sheet, root, a, b, a1 = self._make_workbook()
        wb._sync_to_project(create_if_missing=True)
        self.assertFalse(wb._plan_project_orphans())
        b.unlink()
        self.assertEqual(len(wb._plan_project_orphans()), 1)

    # ----- reverse (project → map) -----
    def test_create_mindmap_from_project(self):
        project = self.Project.create({'name': 'Proj'})
        t1 = self.Task.create({'name': 'T1', 'project_id': project.id})
        t2 = self.Task.create({'name': 'T2', 'project_id': project.id, 'parent_id': t1.id})
        stats = project._sync_to_mindmap(create_if_missing=True)
        wb = self.Workbook.browse(stats['workbook_id'])
        self.assertEqual(wb.project_id, project)
        self.assertTrue(t1.xmind_topic_id and t2.xmind_topic_id)
        # topic hierarchy mirrors task hierarchy
        self.assertEqual(t2.xmind_topic_id.parent_id, t1.xmind_topic_id)
        self.assertEqual(wb.xmind_last_sync_direction, 'to_mindmap')

    def test_reverse_preserves_map_only_children(self):
        project = self.Project.create({'name': 'Proj'})
        t1 = self.Task.create({'name': 'T1', 'project_id': project.id})
        project._sync_to_mindmap(create_if_missing=True)
        wb = project.xmind_workbook_ids
        sheet = wb.sheet_ids
        # user adds a map-only child under T1's topic
        map_only = self.Topic.create({
            'sheet_id': sheet.id, 'parent_id': t1.xmind_topic_id.id, 'title': 'note'})
        # delete the task → re-sync should remove T1's topic but KEEP map_only
        t1.unlink()
        project._sync_to_mindmap(create_if_missing=False)
        self.assertTrue(map_only.exists(), "map-only topic must survive the cascade")

    # ----- round-trip: task link survives a full-recreate save -----
    def test_task_id_survives_save(self):
        wb, sheet, root, a, b, a1 = self._make_workbook()
        wb._sync_to_project(create_if_missing=True)
        a_task = a.task_id
        # export → re-import (simulates the editor save which fully recreates topics)
        data = wb.get_mindmap_data()
        wb.save_mindmap_data(data)
        sheet2 = wb.sheet_ids[:1]
        a2 = sheet2.topic_ids.filtered(lambda t: t.title == 'A')[:1]
        self.assertTrue(a2, "topic A should exist after save")
        self.assertEqual(a2.task_id, a_task, "task link must survive the save round-trip")

    # ----- visibility mirror -----
    def test_privacy_visibility_mirrors_project(self):
        wb, sheet, root, a, b, a1 = self._make_workbook()
        wb._sync_to_project(create_if_missing=True)
        wb.project_id.privacy_visibility = 'followers'
        wb.invalidate_recordset(['privacy_visibility'])
        self.assertEqual(wb.privacy_visibility, 'followers')
