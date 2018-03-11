# -*- coding: utf-8 -*-

from openerp import models, fields, api

# class dobtor_todolist_lifetime(models.Model):
#     _name = 'dobtor_todolist_lifetime.dobtor_todolist_lifetime'

#     name = fields.Char()
#     value = fields.Integer()
#     value2 = fields.Float(compute="_value_pc", store=True)
#     description = fields.Text()
#
#     @api.depends('value')
#     def _value_pc(self):
#         self.value2 = float(self.value) / 100

class DobtorTodoListLifeLine(models.Model):
    _inherit = 'dobtor.todolist.core'

    lifeline = fields.Float(string="Completion", default='0', copy=False, readonly=True)

    @api.model
    def process_lifeline_scheduler(self):
        todo_ids = self.search([])
        for todo in todo_ids:
            todo.calculate_lifeline()

    @api.multi
    def calculate_lifeline(self):
        self.lifeline = 0
        if self.timesheet_ids:
            work_hour = 0
            for timesheet in self.timesheet_ids:
                work_hour = work_hour + timesheet.unit_amount
            if self.planned_hours > 0:
                self.lifeline = (work_hour / self.planned_hours) * 100
            if self.lifeline > 100:
                self.lifeline = 100
        if self.state == 'done':
            self.lifeline = 100
        if self.date_deadline and self.date_deadline <= fields.Datetime.now():
            self.out_of_deadline = True
            self.lifeline = 100
        else:
            self.out_of_deadline = False

    @api.constrains('date_deadline', 'state')
    def change_deadline(self):
        self.calculate_lifeline()

        # task_obj = self.pool.get('project.task')
        # task_ids = task_obj.search(cr, uid, [])
        # time_now = fields.Datetime.from_string(fields.Datetime.now())
        # for task_id in task_ids:
        #     task = task_obj.browse(cr, uid, task_id, context=context)
        #     start_date = fields.Datetime.from_string(task.date_assign)
        #     end_date = fields.Datetime.from_string(task.date_deadline)
        #     if task.stage_id and (task.stage_id.name == 'Done' or task.stage_id.name == 'Cancelled'):
        #         task.lifeline = 0
        #     else:
        #         if task.date_deadline and task.date_assign and end_date > start_date:
        #             if time_now < end_date:
        #                 total_difference_days = relativedelta(end_date, start_date)
        #                 difference_minute = total_difference_days.hours * 60 + total_difference_days.minutes
        #                 date_difference = end_date - start_date
        #                 total_difference_minute = int(date_difference.days) * 24 * 60 + difference_minute

        #                 remaining_days = relativedelta(time_now, start_date)
        #                 remaining_minute = remaining_days.hours * 60 + remaining_days.minutes
        #                 date_remaining = time_now - start_date
        #                 total_minute_remaining = int(date_remaining.days) * 24 * 60 + remaining_minute
        #                 if total_difference_minute != 0:
        #                     task.lifeline = (100 - ((total_minute_remaining * 100) / total_difference_minute))
        #                 else:
        #                     task.lifeline = 0
        #             else:
        #                 task.lifeline = 0

