# -*- coding: utf-8 -*-
from openerp import http

# class DobtorTodolistCrmOpportunity(http.Controller):
#     @http.route('/dobtor_todolist_crm_opportunity/dobtor_todolist_crm_opportunity/', auth='public')
#     def index(self, **kw):
#         return "Hello, world"

#     @http.route('/dobtor_todolist_crm_opportunity/dobtor_todolist_crm_opportunity/objects/', auth='public')
#     def list(self, **kw):
#         return http.request.render('dobtor_todolist_crm_opportunity.listing', {
#             'root': '/dobtor_todolist_crm_opportunity/dobtor_todolist_crm_opportunity',
#             'objects': http.request.env['dobtor_todolist_crm_opportunity.dobtor_todolist_crm_opportunity'].search([]),
#         })

#     @http.route('/dobtor_todolist_crm_opportunity/dobtor_todolist_crm_opportunity/objects/<model("dobtor_todolist_crm_opportunity.dobtor_todolist_crm_opportunity"):obj>/', auth='public')
#     def object(self, obj, **kw):
#         return http.request.render('dobtor_todolist_crm_opportunity.object', {
#             'object': obj
#         })