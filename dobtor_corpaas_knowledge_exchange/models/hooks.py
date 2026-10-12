# -*- coding: utf-8 -*-
from odoo import api, models


class KnowledgeHooksExchange(models.AbstractModel):
    _inherit = 'corpaas.knowledge.hooks'

    @api.model
    def _knowledge_code_prefetch(self, modules=(), defs=(), facts=()):
        res = super()._knowledge_code_prefetch(modules=modules, defs=defs, facts=facts)
        self.env['corpaas.knowledge.exchange']._prefetch(modules=modules, defs=defs, facts=facts)
        return res
