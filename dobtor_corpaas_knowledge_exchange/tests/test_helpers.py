# -*- coding: utf-8 -*-
def make_db(env, number=9461):
    from odoo.addons.dobtor_corpaas_knowledge.tests.test_usage_flow import make_database
    return make_database(env, number)
