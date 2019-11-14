# -*- coding: utf-8 -*-

from odoo import models, fields, api

class DobtorCheckListLifeLine(models.Model):
    _inherit = 'dobtor.checklist.core'

    lifeline = fields.Float(string="Completion", default='0', copy=False, readonly=True)

    @api.model
    def process_lifeline_scheduler(self):
        todo_ids = self.search([])
        for todo in todo_ids:
            todo.calculate_lifeline()

    @api.multi
    def calculate_lifeline(self):
        for record in self:
            record.lifeline = 0
            if record.timesheet_ids:
                work_hour = 0
                for timesheet in record.timesheet_ids:
                    work_hour = work_hour + timesheet.unit_amount
                if record.planned_hours > 0:
                    record.lifeline = (work_hour / record.planned_hours) * 100
                if record.lifeline > 100:
                    record.lifeline = 100
            if record.state == 'done':
                record.lifeline = 100
            if record.date_deadline and record.date_deadline <= fields.Datetime.now():
                record.out_of_deadline = True
                record.lifeline = 100
            else:
                record.out_of_deadline = False

    @api.constrains('date_deadline', 'state')
    def change_deadline(self):
        self.calculate_lifeline()

