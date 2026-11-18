# -*- coding: utf-8 -*-
"""專案鎖與「絕不搬動任務」（Phase 1）。"""
from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, new_test_user, tagged


@tagged('post_install', '-at_install')
class TestProjectLock(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Workbook = cls.env['xmind.workbook']
        cls.Sheet = cls.env['xmind.sheet']
        cls.Topic = cls.env['xmind.topic']
        cls.Project = cls.env['project.project']
        cls.Task = cls.env['project.task']

    def _make_workbook(self, title='Map Title'):
        wb = self.Workbook.create({'name': 'WB'})
        sheet = self.Sheet.create({'workbook_id': wb.id, 'name': 'S1'})
        root = self.Topic.create({'sheet_id': sheet.id, 'title': title})
        a = self.Topic.create({'sheet_id': sheet.id, 'parent_id': root.id, 'title': 'A', 'sequence': 0})
        b = self.Topic.create({'sheet_id': sheet.id, 'parent_id': root.id, 'title': 'B', 'sequence': 1})
        return wb, sheet, root, a, b

    # ----- 鎖 -----
    def test_unlocked_before_sync_can_change_and_clear(self):
        wb, *_ = self._make_workbook()
        p1 = self.Project.create({'name': 'P1'})
        p2 = self.Project.create({'name': 'P2'})
        wb.project_id = p1
        self.assertFalse(wb.project_locked)
        wb.project_id = p2
        self.assertEqual(wb.project_id, p2)
        wb.project_id = False
        self.assertFalse(wb.project_id)

    def test_synced_workbook_is_locked(self):
        wb, *_ = self._make_workbook()
        project = self.Project.create({'name': 'Locked'})
        other = self.Project.create({'name': 'Other'})
        wb.project_id = project
        wb._sync_to_project()
        self.assertTrue(wb.project_locked)
        with self.assertRaises(UserError):
            wb.write({'project_id': False})
        with self.assertRaises(UserError):
            wb.write({'project_id': other.id})
        self.assertEqual(wb.project_id, project)
        # 同一個專案重寫一次不算變更
        wb.write({'project_id': project.id})

    def test_locked_without_project_can_link_one(self):
        """舊版清掉專案後留下的連結：沒有專案可「換」，允許設定（任務由同步守衛保護）。"""
        wb, sheet, root, a, b = self._make_workbook()
        a.task_id = self.Task.create({'name': 'Old', 'project_id': self.Project.create({'name': 'Old'}).id})
        self.assertTrue(wb.project_locked)
        wb.project_id = self.Project.create({'name': 'New'})
        self.assertTrue(wb.project_id)

    def test_task_link_alone_locks(self):
        wb, sheet, root, a, b = self._make_workbook()
        project = self.Project.create({'name': 'P'})
        wb.project_id = project
        a.task_id = self.Task.create({'name': 'T', 'project_id': project.id})
        self.assertTrue(wb.project_locked)

    # ----- 改名 -----
    def test_existing_project_not_renamed(self):
        wb, *_ = self._make_workbook(title='Central Topic Title')
        project = self.Project.create({'name': 'Customer Project'})
        wb.project_id = project
        wb._sync_to_project()
        self.assertEqual(project.name, 'Customer Project')
        self.assertFalse(wb.project_created_from_map)

    def test_map_created_project_follows_central_topic(self):
        wb, sheet, root, a, b = self._make_workbook(title='Created')
        wb._sync_to_project(create_if_missing=True)
        self.assertTrue(wb.project_created_from_map)
        root.title = 'Renamed'
        wb._sync_to_project()
        self.assertEqual(wb.project_id.name, 'Renamed')

    # ----- 任務絕不搬家 -----
    def test_admin_unlock_keep_then_relink_never_moves_tasks(self):
        wb, sheet, root, a, b = self._make_workbook(title='Map Title')
        proj_a = self.Project.create({'name': 'Project A'})
        proj_b = self.Project.create({'name': 'Project B'})
        wb.project_id = proj_a
        wb._sync_to_project()
        tasks_a = self.Task.search([('project_id', '=', proj_a.id)])
        self.assertEqual(len(tasks_a), 2)
        old_a_task = a.task_id

        wb.action_admin_unlock_project('keep')
        self.assertFalse(wb.project_id)
        self.assertFalse(wb.project_locked)
        self.assertFalse(a.task_id)
        self.assertTrue(all(t.active for t in tasks_a), "keep 不封存任務")

        wb.project_id = proj_b
        stats = wb._sync_to_project()
        self.assertEqual(stats['created'], 2)
        self.assertEqual(tasks_a.mapped('project_id'), proj_a, "A 的任務絕不能被搬到 B")
        self.assertTrue(all(t.active for t in tasks_a))
        self.assertNotEqual(a.task_id, old_a_task)
        self.assertEqual(a.task_id.project_id, proj_b)
        self.assertEqual(proj_a.name, 'Project A')
        self.assertEqual(proj_b.name, 'Project B')

    def test_stale_foreign_link_creates_new_task(self):
        """主題仍連著別專案的任務（例如舊編輯器畫面存回 taskId）→ 新建，不搬。"""
        wb, sheet, root, a, b = self._make_workbook()
        proj_a = self.Project.create({'name': 'Project A'})
        proj_b = self.Project.create({'name': 'Project B'})
        foreign = self.Task.create({'name': 'Foreign', 'project_id': proj_a.id,
                                    'xmind_managed': True})
        stage_before = foreign.stage_id
        wb.project_id = proj_b
        a.task_id = foreign
        stats = wb._sync_to_project()
        self.assertEqual(stats['relinked_foreign'], 1)
        self.assertEqual(foreign.project_id, proj_a)
        self.assertEqual(foreign.stage_id, stage_before)
        self.assertTrue(foreign.active)
        self.assertEqual(a.task_id.project_id, proj_b)
        self.assertNotIn(foreign, wb._plan_project_orphans())

    def test_reverse_sync_only_touches_own_tasks(self):
        proj_a = self.Project.create({'name': 'Project A'})
        proj_b = self.Project.create({'name': 'Project B'})
        t_a = self.Task.create({'name': 'TA', 'project_id': proj_a.id})
        t_b = self.Task.create({'name': 'TB', 'project_id': proj_b.id})
        proj_a._sync_to_mindmap(create_if_missing=True)
        proj_b._sync_to_mindmap(create_if_missing=True)
        self.assertEqual(t_a.project_id, proj_a)
        self.assertEqual(t_b.project_id, proj_b)
        self.assertEqual(t_a.xmind_topic_id.sheet_id.workbook_id, proj_a.xmind_workbook_ids)

    def test_admin_unlock_archive_policy(self):
        wb, sheet, root, a, b = self._make_workbook()
        project = self.Project.create({'name': 'P'})
        manual = self.Task.create({'name': 'Manual', 'project_id': project.id})
        wb.project_id = project
        wb._sync_to_project()
        generated = a.task_id | b.task_id
        wb.action_admin_unlock_project('archive')
        self.assertFalse(any(generated.mapped('active')))
        self.assertEqual(generated.mapped('project_id'), project)
        self.assertTrue(manual.active)
        self.assertFalse(wb.project_id)
        self.assertIn('Project lock removed', wb.message_ids[0].body)

    def test_admin_unlock_requires_project_manager(self):
        wb, *_ = self._make_workbook()
        project = self.Project.create({'name': 'P'})
        wb.project_id = project
        wb._sync_to_project()
        user = new_test_user(self.env, login='xmind_plain_user', groups='base.group_user')
        with self.assertRaises(AccessError):
            wb.with_user(user).action_admin_unlock_project('keep')

    def test_unlock_wizard_requires_confirmation(self):
        wb, *_ = self._make_workbook()
        project = self.Project.create({'name': 'Confirm Me'})
        wb.project_id = project
        wb._sync_to_project()
        wizard = self.env['xmind.project.unlock.wizard'].create({
            'workbook_id': wb.id, 'policy': 'keep', 'confirm_text': 'wrong'})
        with self.assertRaises(UserError):
            wizard.action_confirm()
        wizard.confirm_text = 'Confirm Me'
        wizard.action_confirm()
        self.assertFalse(wb.project_id)

    # ----- 複製（不帶專案連結） -----
    def test_duplicate_unlinked(self):
        wb, sheet, root, a, b = self._make_workbook()
        a1 = self.Topic.create({'sheet_id': sheet.id, 'parent_id': a.id, 'title': 'A1'})
        marker = self.env['xmind.marker'].search([], limit=1)
        self.env['xmind.topic.marker'].create({'topic_id': a.id, 'marker_id': marker.id})
        self.env['xmind.attachment'].create({'topic_id': a.id, 'name': 'file.txt',
                                             'attachment_type': 'file'})
        self.env['xmind.relationship'].create({
            'sheet_id': sheet.id, 'source_topic_id': a.id, 'target_topic_id': b.id})
        self.env['xmind.boundary'].create({'sheet_id': sheet.id, 'topic_ids': [(6, 0, [a.id, b.id])]})
        self.env['xmind.summary'].create({'sheet_id': sheet.id, 'topic_ids': [(6, 0, [a1.id])]})
        self.env['xmind.callout'].create({'topic_id': b.id, 'title': 'Callout'})
        self.env['xmind.floating.topic'].create({'sheet_id': sheet.id, 'title': 'Float'})
        idea = self.Sheet.create({'workbook_id': wb.id, 'name': 'Idea', 'sequence': 20})
        self.Topic.create({'sheet_id': idea.id, 'title': 'Idea root'})
        wb.project_id = self.Project.create({'name': 'P'})
        wb._sync_to_project()

        action = wb.action_duplicate_workbook_unlinked()
        copy = self.Workbook.browse(action['params']['workbook_id'])
        self.assertNotEqual(copy, wb)
        self.assertEqual(copy.name, 'WB（副本）')
        self.assertFalse(copy.project_id)
        self.assertFalse(copy.project_locked)
        topics = self.Topic.search([('sheet_id.workbook_id', '=', copy.id)])
        self.assertEqual(len(topics), 5)
        self.assertFalse(topics.filtered('task_id'))
        self.assertFalse(topics.filtered('project_managed'))
        new_main = copy.sheet_ids.sorted(lambda s: (s.sequence, s.id))[:1]
        self.assertEqual(new_main.name, 'S1')
        self.assertEqual(len(copy.sheet_ids), 2)
        self.assertEqual(len(new_main.relationship_ids), 1)
        self.assertEqual(len(new_main.boundary_ids), 1)
        self.assertEqual(len(new_main.summary_ids), 1)
        self.assertEqual(len(new_main.floating_topic_ids), 1)
        new_a = topics.filtered(lambda t: t.title == 'A')
        self.assertEqual(len(new_a.marker_ids), 1)
        self.assertEqual(len(new_a.attachment_ids), 1)
        self.assertEqual(new_main.relationship_ids.source_topic_id, new_a)
        self.assertEqual(self.env['xmind.callout'].search_count(
            [('topic_id', 'in', topics.ids)]), 1)
        # 原圖不受影響
        self.assertTrue(a.task_id)
        self.assertTrue(wb.project_locked)

    # ----- 可疑關聯報告 -----
    def test_suspicious_links_report(self):
        wb, sheet, root, a, b = self._make_workbook(title='Website Redesign')
        partner1 = self.env['res.partner'].create({'name': 'C1'})
        partner2 = self.env['res.partner'].create({'name': 'C2'})
        proj = self.Project.create({'name': 'Payroll Migration', 'partner_id': partner2.id})
        other = self.Project.create({'name': 'Other'})
        wb.project_id = proj
        wb.partner_id = partner1   # 寫入時沒有 project_id → 不會被專案客戶覆蓋
        a.task_id = self.Task.create({'name': 'Elsewhere', 'project_id': other.id})
        rows = [r for r in self.Workbook.get_suspicious_links_report() if r['workbook_id'] == wb.id]
        self.assertEqual(len(rows), 3, rows)
        action = self.env['xmind.suspicious.link.report'].action_generate()
        report = self.env['xmind.suspicious.link.report'].browse(action['res_id'])
        self.assertIn(wb, report.line_ids.mapped('workbook_id'))
        # 唯讀：沒有修正任何東西
        self.assertEqual(wb.project_id, proj)
        self.assertEqual(a.task_id.project_id, other)

    def test_project_picker_domain_excludes_linked_projects(self):
        """專案列的下拉清單：已被其他心智圖（含已封存）連結的專案不列出。"""
        free = self.Project.create({'name': 'Picker Free'})
        taken = self.Project.create({'name': 'Picker Taken'})
        archived_taken = self.Project.create({'name': 'Picker Archived'})
        self.Workbook.create({'name': 'Holder', 'project_id': taken.id})
        self.Workbook.create({'name': 'Old', 'project_id': archived_taken.id}).active = False
        found = {pid for pid, _n in self.Project.name_search(
            'Picker', args=[('xmind_workbook_ids', '=', False)])}
        self.assertEqual(found, {free.id})
