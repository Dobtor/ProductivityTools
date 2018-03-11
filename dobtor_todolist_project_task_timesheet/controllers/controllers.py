# -*- coding: utf-8 -*-
from openerp import http

# class DobtorTodolistTimesheets(http.Controller):
#     @http.route('/dobtor_todolist_timesheets/dobtor_todolist_timesheets/', auth='public')
#     def index(self, **kw):
#         return "Hello, world"

#     @http.route('/dobtor_todolist_timesheets/dobtor_todolist_timesheets/objects/', auth='public')
#     def list(self, **kw):
#         return http.request.render('dobtor_todolist_timesheets.listing', {
#             'root': '/dobtor_todolist_timesheets/dobtor_todolist_timesheets',
#             'objects': http.request.env['dobtor_todolist_timesheets.dobtor_todolist_timesheets'].search([]),
#         })

#     @http.route('/dobtor_todolist_timesheets/dobtor_todolist_timesheets/objects/<model("dobtor_todolist_timesheets.dobtor_todolist_timesheets"):obj>/', auth='public')
#     def object(self, obj, **kw):
#         return http.request.render('dobtor_todolist_timesheets.object', {
#             'object': obj
#         })