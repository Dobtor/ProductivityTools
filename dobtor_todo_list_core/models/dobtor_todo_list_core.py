# -*- coding: utf-8 -*-

import odoo
from odoo import models, fields, api, SUPERUSER_ID, _
#from odoo.addons.base.res import res_request
from odoo.tools import html_escape as escape
from odoo.exceptions import Warning as UserError

from datetime import timedelta, date, datetime

TODO_STATES = {
    'todo': 'Todo',
            'done': 'Done',
            'pending': 'Pending',
            'cancelled': 'Cancelled'
}


class DobtorTodoListCore(models.Model):
    _name = "dobtor.todo.list.core"
    _inherit = ["mail.thread", 'mail.activity.mixin']
    _description = 'Dobtor Todo List Core'

    tag_ids = fields.Many2many(
        string='Tags',
        comodel_name='todo.list.tags',
        relation='todo_list_tags_rel',
        column1='tag_id',
        column2='todo_id',
    )
    stage_id = fields.Many2one('todo.list.type', string='Stage', ondelete='restrict',
                               track_visibility='onchange', index=True, group_expand='_read_group_stage_ids', copy=False)
    state = fields.Selection(selection='get_todo_state',
                             string='Status',
                             required=True,
                             copy=False,
                             default='todo')
    name = fields.Char(required=True, string="Description")
    creater = fields.Many2one('res.users',
                              'Creater',
                              readonly=True,
                              default=lambda self: self.env.user)
    reviewer_id = fields.Many2one('res.users',
                                  'Reviewer',
                                  default=lambda self: self.env.user)
    user_id = fields.Many2one('res.users', 'Assigned to', required=True)
    hide_button = fields.Boolean(compute='_compute_hide_button')
    recolor = fields.Boolean(compute='_compute_recolor')
    ref_model = fields.Reference(selection='set_ref_models',
                                 string="Refer To",
                                 default=None)
    ref_id = fields.Integer(string='ref_id')
    ref_name = fields.Char(string='ref_name')
    parent_model = fields.Reference(selection='referencable_models',
                                    string="Parent",
                                    default=None)
    parent_id = fields.Integer(string='parent_id')
    parent_name = fields.Char(string='parent_name')
    partner_id = fields.Many2one('res.partner',
                                 default=lambda self: self.env.user.partner_id)
    date_assign = fields.Datetime('Assigning Date',
                                  default=fields.Datetime.now)
    date_complete = fields.Datetime('Complete Date')
    date_deadline = fields.Datetime("Deadline")
    planned_hours = fields.Float(string='Planned Hours', default=0)
    out_of_deadline = fields.Boolean(string="Out of deadline",
                                     default=False,
                                     compute="_compute_todo_deadline")
    sequence = fields.Integer()
    description = fields.Html(string='Description')

    # region perferment Performance into tree view
    ref_model_name = fields.Char(compute='_compute_model_name',
                                 string="Refer To")
    ref_parent_model_name = fields.Char(compute='_compute_parent_model_name',
                                        string="Parent")

    @api.depends("date_deadline", "state")
    def compute_todo_week(self):
        for todo in self:
            if todo.date_deadline:
                todo.week_start = todo.date_deadline - \
                    timedelta(days=datetime.now().weekday())
                todo.week_end = todo.date_deadline + timedelta(weeks=1)
            if str(todo.date_deadline)<str(datetime.today()) and todo.state =='todo':
                todo.overdue = True
            else:
                todo.overdue = False 

    @api.depends("week_start", "week_end")
    def compute_on_week(self):
        for todo in self:
            today = str(datetime.today())
            if today > str(todo.week_start) and today <= str(todo.week_end):
                todo.on_week = True
            else:
                todo.on_week = False


    week_start = fields.Datetime("week start", compute="compute_todo_week")
    week_end = fields.Datetime("week end", compute="compute_todo_week")
    on_week = fields.Boolean(
        string='On Week', compute="compute_on_week", store=True)
    overdue =  fields.Boolean(
        string='OverDue',compute="compute_todo_week", store=True
    )
    

    @api.depends('ref_name', 'ref_id')
    @api.multi
    def _compute_model_name(self):
        for record in self:
            if record.ref_name:
                record.ref_model_name = self.env[record.ref_name].browse(
                    record.ref_id).name

    @api.model
    def index_state(self):
        return [
            (10, 'todo'),
            (20, 'done'),
            (30, 'pending'),
            (40, 'cancelled'),
        ]

    @api.model
    def _sort_state(self, array_state):
        result = []
        for set_value in sorted(self.index_state(), key=lambda x: x[0]):
            result += [item for item in array_state if item[0] == set_value[1]]
        return result

    @api.model
    def get_todo_state(self):
        return self._sort_state([
            ('todo', 'Todo'),
            ('done', 'Done'),
            ('pending', 'Pending'),
            ('cancelled', 'Cancelled'),
        ])

    @api.depends('parent_name', 'parent_id')
    @api.multi
    def _compute_parent_model_name(self):
        for record in self:
            if record.parent_name:
                record.ref_parent_model_name = self.env[
                    record.parent_name].browse(record.parent_id).name

    # endregion

    @api.model
    def set_todo_status(self):
        return [(k, v) for k, v in self.get_todo_states().items()]

    @api.model
    def set_ref_models(self):
        return []

    @api.model
    def referencable_models(self):
        models = self.env['res.request.link'].search([])
        return [(model.object, model.name) for model in models]
        # return [('project.project', 'Project'), ('crm.lead', 'Crm Lead')]

    @api.multi
    def _compute_todo_deadline(self):
        for record in self:
            if record.date_deadline and record.date_deadline <= fields.Datetime.now(
            ):
                record.out_of_deadline = True
            else:
                record.out_of_deadline = False

    @api.multi
    def _compute_recolor(self):
        for record in self:
            if record.user_id and self.env.user == record.user_id and record.state == 'todo':
                record.recolor = True

    @api.multi
    def _compute_hide_button(self):
        for record in self:
            if self.env.user not in [record.reviewer_id, record.user_id]:
                record.hide_button = True

    @api.multi
    def _compute_reviewer_id(self):
        for record in self:
            record.reviewer_id = record.create_uid

    @api.model
    def _needaction_domain_get(self):
        if self._needaction:
            return [('state', '=', 'todo'), ('user_id', '=', self.env.uid)]
        return []

    @api.multi
    def _handle_ref_model(self, vals):
        if 'ref_model' in vals and vals['ref_model']:
            vals['ref_id'] = vals['ref_model'].split(',')[1]
            vals['ref_name'] = vals['ref_model'].split(',')[0]
        return vals

    @api.multi
    def _handle_parent_model(self, vals):
        if 'parent_model' in vals and vals['parent_model']:
            vals['parent_id'] = vals['parent_model'].split(',')[1]
            vals['parent_name'] = vals['parent_model'].split(',')[0]
        return vals

    @api.multi
    def write(self, vals):
        vals = self._handle_ref_model(vals)
        vals = self._handle_parent_model(vals)
        old_names = dict(zip(self.mapped('id'), self.mapped('name')))
        result = super().write(vals)
        for r in self:
            if (vals.get('state')) and r.user_id:
                self.send_todo_list_email(r.name, r.state, r.reviewer_id.id,
                                          r.user_id.id, r.ref_model)
                if self.env.user != r.reviewer_id and self.env.user != r.user_id:
                    raise UserError(
                        _('Only users related to that subtask can change state.'
                          ))
            if vals.get('name') and r.user_id:
                self.send_todo_list_email(r.name,
                                          r.state,
                                          r.reviewer_id.id,
                                          r.user_id.id,
                                          r.ref_model,
                                          old_name=old_names[r.id])
                if self.env.user != r.reviewer_id and self.env.user != r.user_id:
                    raise UserError(
                        _('Only users related to that subtask can change state.'
                          ))
            if vals.get('user_id'):
                self.send_todo_list_email(r.name, r.state, r.reviewer_id.id,
                                          r.user_id.id, r.ref_model)
        return result

    @api.model
    def create(self, vals):
        vals = self._handle_ref_model(vals)
        vals = self._handle_parent_model(vals)
        result = super().create(vals)
        # vals = self._add_missing_default_values(vals)
        if result.user_id:
            self.send_todo_list_email(result.name, result.state,
                                      result.reviewer_id.id, result.user_id.id)
        return result

    @api.multi
    def change_state_done(self):
        for record in self:
            record.state = 'done'
            record.date_complete = fields.Datetime.now()

    @api.multi
    def change_state_todo(self):
        for record in self:
            record.state = 'todo'
            record.date_complete = None

    @api.multi
    def change_state_cancelled(self):
        for record in self:
            record.state = 'cancelled'
            record.date_complete = None

    @api.multi
    def change_state_waiting(self):
        for record in self:
            record.state = 'waiting'
            record.date_complete = None

    @api.onchange('user_id')
    def change_user_id(self):
        if self.user_id:
            self.date_assign = fields.Datetime.now()
        else:
            self.date_assign = None

    @api.multi
    def defaults_copy(self, default=None):
        defaults = dict(default or {})
        for item in self:
            defaults.update({
                'name': item.name,
                'creater': item.creater.id,
                'reviewer_id': item.reviewer_id.id,
            })
            if item.user_id:
                defaults.update({'user_id': item.user_id.id})
        return defaults

    # region upload freature (Attchment)
    attachment_number = fields.Integer(compute='_compute_attachment_number',
                                       string='Number of Attachments')

    @api.multi
    def _compute_attachment_number(self):
        attachment_data = self.env['ir.attachment'].read_group(
            [('res_model', '=', self._name),
             ('res_id', 'in', self.ids)], ['res_id'], ['res_id'])
        attachment = dict(
            (res['res_id'], res['res_id_count']) for res in attachment_data)
        for record in self:
            record.attachment_number = attachment.get(record.id, 0)

    @api.multi
    def action_get_attachment_view(self):
        self.ensure_one()
        res = self.env['ir.actions.act_window'].for_xml_id(
            'base', 'action_attachment')
        res['domain'] = [('res_model', '=', self._name),
                         ('res_id', 'in', self.ids)]
        res['context'] = {
            'default_res_model': self._name,
            'default_res_id': self.id
        }
        return res

    @api.multi
    def attachment_form_view(self):
        self.ensure_one()
        return {
            'name':
            _('Attachments'),
            'res_model':
            'ir.attachment',
            'type':
            'ir.actions.act_window',
            'view_id':
            self.env.ref(
                'dobtor_todo_list_core.view_todo_list_core_attachment_form').
            id,
            'view_mode':
            'form',
            'view_type':
            'form',
            'context':
            "{'default_res_model': '%s','default_res_id': %d}" %
            (self._name, self.id)
        }

    # endregion

    # region Send mail
    @api.multi
    def send_todo_list_email(self,
                             todo_name,
                             todo_state,
                             todo_reviewer_id,
                             todo_user_id,
                             ref_model=None,
                             old_name=None):
        reviewer = self.env["res.users"].browse(todo_reviewer_id)
        user = self.env["res.users"].browse(todo_user_id)

        state_list = self.get_todo_state()
        state_dict = {}
        for i in range(0, len(state_list)):
            state_dict.update({state_list[i][0]: state_list[i][1]})
        state = state_dict[todo_state]

        state_str = '<span></span>'
        if todo_state == 'done':
            state_str = '<span style="color:#080">' + state + '</span>'
        elif todo_state == 'todo':
            state_str = '<span style="color:#A00">' + state + '</span>'
        elif todo_state == 'cancelled':
            state_str = '<span style="color:#777">' + state + '</span>'
        elif todo_state == 'waiting':
            state_str = '<span style="color:#b818ce">' + state + '</span>'
        else:
            state_str = '<span>' + state + '</span>'

        subtype = 'dobtor_todo_list_core.todo_list_core_subtype'

        body = ''
        partner_ids = []
        if user == self.env.user and reviewer == self.env.user:
            body = '<p>' + '<strong>' + state_str + \
                '</strong> ' + escape(todo_name)
            subtype = False
        elif self.env.user == reviewer:
            body = '<p>' + escape(user.name) + ', <br><strong>' + \
                state_str + '</strong>: ' + escape(todo_name)
            partner_ids = [user.partner_id.id]
        elif self.env.user == user:
            body = '<p>' + escape(reviewer.name) + ', <em style="color:#999">I updated todo-list item assigned to me:</em> <br><strong>' + \
                state_str + '</strong>: ' + escape(todo_name)
            partner_ids = [reviewer.partner_id.id]
        else:
            body = '<p>' + escape(user.name) + ', ' + escape(reviewer.name) + ', <em style="color:#999">I updated todo-list item, now its assigned to ' + \
                escape(user.name) + ': </em> <br><strong>' + \
                state_str + '</strong>: ' + escape(todo_name)
            partner_ids = [user.partner_id.id, reviewer.partner_id.id]
        if old_name:
            body = body + '<br><em style="color:#999">Updated from</em><br><strong>' + \
                state_str + '</strong>: ' + escape(old_name) + '</p>'
        else:
            body = body + '</p>'

        self.message_post(subject='Your todo list',
                          message_type='comment',
                          subtype=subtype,
                          body=body,
                          partner_ids=partner_ids)

    # endregion
    @api.multi
    def action_form_todo_list(self):
        return {
            'name': _('Todo-List'),
            'res_model': self._name,
            'type': 'ir.actions.act_window',
            'view_id': False,
            'view_mode': 'form',
            'view_type': 'form',
            'target': 'current',
            'res_id': self.id,
        }

    @api.model
    def _read_group_stage_ids(self, stages, domain, order):
        """ Read group customization in order to display all the stages in the
            kanban view, even if they are empty
        """
        stage_ids = stages._search(
            [], order=order, access_rights_uid=SUPERUSER_ID)
        return stages.browse(stage_ids)
        

    @api.onchange('ref_model')
    def _add_followers(self):
        for todo in self:
            if todo.ref_model:
                if todo.reviewer_id:
                    todo.ref_model.message_subscribe([todo.reviewer_id.partner_id.id])
                if todo.creater:
                    todo.ref_model.message_subscribe([todo.creater.partner_id.id])
                if todo.user_id:
                    todo.ref_model.message_subscribe([todo.user_id.partner_id.id])
                 



class TodoListType(models.Model):
    _name = 'todo.list.type'
    _description = 'Todo Stage'
    _order = 'sequence, id'

    name = fields.Char(string='Stage Name', required=True, translate=True)
    description = fields.Text(translate=True)
    sequence = fields.Integer(default=1)
    todo_ids = fields.One2many(
        'dobtor.todo.list.core', 'stage_id', string='Todo',)
    fold = fields.Boolean(string='Folded in Kanban')


class TodoListTags(models.Model):
    _name = 'todo.list.tags'
    _description = 'Todo Tags'

    name = fields.Char(string='Name', required=True, translate=True)

    todo_ids = fields.Many2many(
        string='todo',
        comodel_name='dobtor.todo.list.core',
        relation='todo_list_tags_rel',
        column1='todo_id',
        column2='tag_id',
    )
