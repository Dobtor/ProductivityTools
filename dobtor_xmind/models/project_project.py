# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError
from odoo.tools import html2plaintext


class ProjectProject(models.Model):
    _inherit = 'project.project'

    # Reverse of xmind.workbook.project_id (1:1 in practice — at most one mind map
    # per project). Used for navigation and the reverse create/sync.
    xmind_workbook_ids = fields.One2many(
        'xmind.workbook', 'project_id', string='Mind Maps')
    xmind_workbook_count = fields.Integer(
        compute='_compute_xmind_workbook_count', string='Mind Map Count')

    @api.depends('xmind_workbook_ids')
    def _compute_xmind_workbook_count(self):
        for project in self:
            project.xmind_workbook_count = len(project.xmind_workbook_ids)

    # -------------------------------------------------------------------------
    # Reverse sync — project / tasks → mind map
    # -------------------------------------------------------------------------
    def action_create_mindmap(self):
        """Create a mind map from this project (if none) and sync its topics."""
        self.ensure_one()
        return self._sync_to_mindmap(create_if_missing=True)

    def action_sync_mindmap(self):
        """Sync this project's tasks into its linked mind map (project → map)."""
        self.ensure_one()
        return self._sync_to_mindmap(create_if_missing=not self.xmind_workbook_ids)

    def action_open_mindmaps(self):
        """Smart button: open the linked mind map(s)."""
        self.ensure_one()
        workbooks = self.xmind_workbook_ids
        if len(workbooks) == 1:
            return workbooks.action_open_editor()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Mind Maps'),
            'res_model': 'xmind.workbook',
            'view_mode': 'kanban,list,form',
            'domain': [('project_id', '=', self.id)],
        }

    def _sync_to_mindmap(self, create_if_missing=False):
        """Diff-sync this project's task tree into a mind map: project → central
        topic; each task → topic (task.parent_id hierarchy → topic.parent_id).
        Links kept via task.xmind_topic_id, so re-sync updates instead of
        duplicating; topics whose source task is gone are removed. Map-only
        topics (no task_id) are left untouched."""
        self.ensure_one()
        Topic = self.env['xmind.topic']

        workbook = self.xmind_workbook_ids[:1]
        if not workbook:
            if not create_if_missing:
                raise UserError(_("This project has no linked mind map yet."))
            workbook = self.env['xmind.workbook'].create({
                'name': self.name,
                'project_id': self.id,
            })
        sheet = workbook.sheet_ids[:1]
        if not sheet:
            sheet = self.env['xmind.sheet'].create({
                'workbook_id': workbook.id,
                'name': self.name,
            })

        # Central topic mirrors the project name.
        root = sheet.topic_ids.filtered(lambda t: not t.parent_id)[:1]
        if not root:
            root = Topic.create({'sheet_id': sheet.id, 'title': self.name})
        elif root.title != self.name:
            root.title = self.name

        tasks = self.env['project.task'].search(
            [('project_id', '=', self.id)], order='sequence, id')

        task_topic = {}
        synced = set()

        def topic_for(task):
            if task.id in task_topic:
                return task_topic[task.id]
            if task.parent_id and task.parent_id.project_id.id == self.id:
                parent_topic = topic_for(task.parent_id)
            else:
                parent_topic = root
            vals = {
                'sheet_id': sheet.id,
                'parent_id': parent_topic.id,
                'title': task.name or _('Task'),
                'sequence': task.sequence or 0,
                'note': html2plaintext(task.description) if task.description else '',
                'task_end_date': task.date_deadline.date() if task.date_deadline else False,
                'task_assignee': task.user_ids[:1].name if task.user_ids else '',
                'task_progress': 100 if task.state == '1_done' else 0,
            }
            topic = task.xmind_topic_id
            if topic and topic.exists() and topic.sheet_id.id == sheet.id:
                topic.write(vals)
            else:
                topic = Topic.create(vals)
                task.xmind_topic_id = topic.id
            if topic.task_id.id != task.id:
                topic.task_id = task.id
            task_topic[task.id] = topic
            synced.add(topic.id)
            return topic

        for task in tasks:
            topic_for(task)

        # Remove topics whose source task is gone (only task-linked ones — map-only
        # content is preserved).
        orphans = sheet.topic_ids.filtered(
            lambda t: t.task_id and t.id not in synced)
        if orphans:
            orphans.unlink()

        workbook.modified_time = fields.Datetime.now()
        return workbook.action_open_editor()
