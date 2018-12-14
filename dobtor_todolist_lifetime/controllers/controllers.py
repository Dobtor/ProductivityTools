# -*- coding: utf-8 -*-
from openerp import http

# class DobtorTodolistLifetime(http.Controller):
#     @http.route('/dobtor_todolist_lifetime/dobtor_todolist_lifetime/', auth='public')
#     def index(self, **kw):
#         return "Hello, world"

#     @http.route('/dobtor_todolist_lifetime/dobtor_todolist_lifetime/objects/', auth='public')
#     def list(self, **kw):
#         return http.request.render('dobtor_todolist_lifetime.listing', {
#             'root': '/dobtor_todolist_lifetime/dobtor_todolist_lifetime',
#             'objects': http.request.env['dobtor_todolist_lifetime.dobtor_todolist_lifetime'].search([]),
#         })

#     @http.route('/dobtor_todolist_lifetime/dobtor_todolist_lifetime/objects/<model("dobtor_todolist_lifetime.dobtor_todolist_lifetime"):obj>/', auth='public')
#     def object(self, obj, **kw):
#         return http.request.render('dobtor_todolist_lifetime.object', {
#             'object': obj
#         })