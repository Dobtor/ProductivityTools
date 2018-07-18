# -*- coding: utf-8 -*-

from odoo import models, fields, api


class project_template_task(models.Model):
    _inherit = "project.task.type"
    project_check = fields.Boolean(string="Project Check")

    @api.multi
    def get_type_template(self):
        return self.search([('name', '=', 'Template')], limit=1)

    @api.multi
    def get_type_new(self):
        return self.search([('name', '=', 'New')], limit=1)

    @api.multi
    def get_type_inprogress(self):
        return self.search([('name', '=', 'In Progress')], limit=1)


class project_project(models.Model):
    _inherit = "project.project"

    @api.model
    def default_get(self, flds):
        stage_type_obj = self.env['project.task.type']
        state_new_id = stage_type_obj.get_type_new() and stage_type_obj.search(
            [('name', '=', 'New')])[0]
        if state_new_id:
            state_new_id.write({'sequence': 1, 'project_check': True})
        else:
            state_new_id = stage_type_obj.create(
                {'name': 'New', 'sequence': 1, 'project_check': True})
        state_in_progress_id = stage_type_obj.get_type_inprogress()
        if state_in_progress_id:
            state_in_progress_id.write({'sequence': 2, 'project_check': True})
        else:
            progress_id = stage_type_obj.create(
                {'name': 'In Progress', 'sequence': 2, 'project_check': True})
        state_cancel_id = stage_type_obj.search(
            [('name', '=', 'Cancelled')], limit=1)
        if state_cancel_id:
            state_cancel_id.write({'sequence': 3, 'project_check': True})
        else:
            cancel_id = stage_type_obj.create(
                {'name': 'Cancelled', 'sequence': 3, 'project_check': True})
        state_pending_id = stage_type_obj.search(
            [('name', '=', 'Pending')], limit=1)
        if state_pending_id:
            state_pending_id.write({'sequence': 4, 'project_check': True})
        else:
            pending_id = stage_type_obj.create(
                {'name': 'Pending', 'sequence': 4, 'project_check': True})
        state_closed_id = stage_type_obj.search(
            [('name', '=', 'Closed')], limit=1)
        if state_closed_id:
            state_closed_id.write({'sequence': 5, 'project_check': True})
        else:
            closed_id = stage_type_obj.create(
                {'name': 'Closed', 'sequence': 4, 'project_check': True})
        stage_list = []
        result = super(project_project, self).default_get(flds)
        result['stage_id'] = state_new_id.id
        result['use_tasks'] = True
        return result

    @api.multi
    def count_sequence(self):
        for item in self:
            stage_type_obj = item.env['project.task.type']
            if item.stage_id.id == int(stage_type_obj.get_type_new()):
                item.sequence_state = 1
            elif item.stage_id.id == int(stage_type_obj.get_type_inprogress()):
                item.sequence_state = 2
            else:
                item.sequence_state = 3

    @api.multi
    def set_template(self):
        stage_type_obj = self.env['project.task.type']
        state_template_id = stage_type_obj.get_type_template()
        state_new_id = stage_type_obj.get_type_new()
        if state_template_id:
            state_template_id.write({'sequence': 1, 'project_check': True})
            state_new_id.update({'sequence': 2, 'project_check': True})
            self.update(
                {'stage_id': state_template_id.id, 'sequence_state': 3})
        else:
            template_id = stage_type_obj.create(
                {'name': 'Template', 'sequence': 1, 'project_check': True})
            template_id.write({'sequence': 1, 'project_check': True})
            state_new_id.write({'sequence': 2, 'project_check': True})
            self.write({'stage_id': template_id.id, 'sequence_state': 3})
        state_template_id.write({'project_check': False})

    @api.multi
    def reference_todolist(self, new_project):
        for task in new_project.tasks:
            for todolist in task.todolist_ids:
                self.env['dobtor.todolist.core'].browse(todolist.id).write(
                    {'parent_model': 'project.project, ' + str(new_project.id)})
        return True

    @api.multi
    def copy(self, default=None):
        default = dict(default or {})
        project = super(project_project, self).copy(default)
        if 'tasks' not in default:
            self.reference_todolist(project)
        return project
   
    @api.multi
    def new_project(self):
        stage_type_obj = self.env['project.task.type']
        project_id = self.copy()
        if stage_type_obj.get_type_template():
            project_id.write({
                'stage_id': stage_type_obj.get_type_new().id,
                'sequence_state': 1
            })
            return project_id

    @api.multi
    def reset_project(self):
        stage_type_obj = self.env['project.task.type']
        state_new_id = stage_type_obj.get_type_new()
        if state_new_id:
            self.write({'stage_id': state_new_id.id, 'sequence_state': 1})
        return

    @api.multi
    def set_progress(self):
        stage_type_obj = self.env['project.task.type']
        state_progress_id = stage_type_obj.get_type_inprogress()
        if state_progress_id:
            self.write({'stage_id': state_progress_id.id, 'sequence_state': 2})
        return

    stage_id = fields.Many2one('project.task.type', string="state")
    sequence_state = fields.Integer(
        compute="count_sequence", string="State Check")


class project_task(models.Model):
    _inherit = "project.task"

    @api.multi
    def map_todolist(self, new_task):
        for todolist in self.todolist_ids:
            defaults = {
                'name': todolist.name,
                'creater': todolist.creater.id,
                'reviewer_id': todolist.reviewer_id.id,
                'user_id': todolist.user_id.id,
                'ref_model': 'project.task,' + str(new_task.id),
                # 'parent_model': 'project.project,' + str(new_task.project_id.id),
            }
            self.browse(new_task.id).write(
                {'todolist_ids': todolist.copy(defaults)})
        return True

    @api.multi
    def copy(self, default=None):
        default = dict(default or {})
        task = super(project_task, self).copy(default)
        if 'todolist_ids' not in default:
            self.map_todolist(task)
        return task
