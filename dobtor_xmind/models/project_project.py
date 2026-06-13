# -*- coding: utf-8 -*-
import pytz
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
        """Create a mind map from this project (if none), sync, and open the editor."""
        self.ensure_one()
        stats = self._sync_to_mindmap(create_if_missing=True)
        return self.env['xmind.workbook'].browse(stats['workbook_id']).action_open_editor()

    def action_sync_mindmap(self):
        """Sync this project's tasks into its linked mind map (project → map)."""
        self.ensure_one()
        stats = self._sync_to_mindmap(create_if_missing=not self.xmind_workbook_ids)
        msg = _("Created %(c)s, updated %(u)s, removed %(a)s.") % {
            'c': stats['created'], 'u': stats['updated'], 'a': stats['removed']}
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {'title': _("Mind map synced"), 'message': msg,
                       'type': 'success', 'sticky': False},
        }

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
        stats = {'created': 0, 'updated': 0, 'removed': 0}

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
                'project_managed': True,
                'note': html2plaintext(task.description) if task.description else '',
                'task_assignee': ', '.join(task.user_ids.mapped('name')) if task.user_ids else '',
                'task_progress': 100 if task.state == '1_done' else 0,
            }
            # Deadline → date + time-of-day, converted from UTC to the user's tz.
            if task.date_deadline:
                tz = pytz.timezone(self.env.user.tz or 'UTC')
                local = pytz.UTC.localize(task.date_deadline).astimezone(tz)
                vals['task_end_date'] = local.date()
                vals['task_deadline_time'] = local.strftime('%H:%M')
            else:
                vals['task_end_date'] = False
                vals['task_deadline_time'] = ''
            topic = task.xmind_topic_id
            if topic and topic.exists() and topic.sheet_id.id == sheet.id:
                topic.write(vals)
                stats['updated'] += 1
            else:
                topic = Topic.create(vals)
                task.xmind_topic_id = topic.id
                stats['created'] += 1
            if topic.task_id.id != task.id:
                topic.task_id = task.id
            task_topic[task.id] = topic
            synced.add(topic.id)
            return topic

        for task in tasks:
            topic_for(task)

        # Remove topics whose source task is gone (only task-linked ones — map-only
        # content is preserved).
        # project-managed topics whose source task is gone (task deletion nulls
        # task_id, so we rely on the persistent project_managed flag, not task_id).
        orphans = sheet.topic_ids.filtered(
            lambda t: t.project_managed and t.id not in synced)
        if orphans:
            stats['removed'] = len(orphans)
            # topic.parent_id is ondelete='cascade' — reparent any surviving
            # (map-only) children of orphans up to the root BEFORE unlinking, so the
            # cascade never deletes user-added content.
            orphan_ids = set(orphans.ids)
            survivors = sheet.topic_ids.filtered(
                lambda t: t.parent_id.id in orphan_ids and t.id not in orphan_ids)
            if survivors:
                survivors.write({'parent_id': root.id})
            orphans.unlink()

        workbook.write({
            'modified_time': fields.Datetime.now(),
            'xmind_last_sync': fields.Datetime.now(),
            'xmind_last_sync_direction': 'to_mindmap',
        })
        stats['workbook_id'] = workbook.id
        return stats
