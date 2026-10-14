# -*- coding: utf-8 -*-
"""外洩修正：只屬於專案方案的能力、情境、資料包、步驟區塊改成私有。

主體上已經發過的會寫一筆作廢進發佈清單，從屬下次拉取就停用鏡像。
"""
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    Vis = env['corpaas.knowledge.exchange.visibility']
    for kind in Vis.PACKAGE_SCOPED:
        model = {'capability': 'corpaas.knowledge.capability', 'scenario': 'corpaas.knowledge.scenario',
                 'seed_pack': 'corpaas.knowledge.seed_pack', 'step_block': 'corpaas.knowledge.step_block'}[kind]
        if model in env:
            Vis._classify(env[model].sudo().search([('kb_sync_state', '!=', 'mirror')]))
