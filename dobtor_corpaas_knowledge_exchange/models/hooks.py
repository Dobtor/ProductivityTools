# -*- coding: utf-8 -*-
from odoo import api, models


class KnowledgeHooksExchange(models.AbstractModel):
    _inherit = 'corpaas.knowledge.hooks'

    @api.model
    def _knowledge_code_prefetch(self, modules=(), defs=(), facts=()):
        res = super()._knowledge_code_prefetch(modules=modules, defs=defs, facts=facts)
        self.env['corpaas.knowledge.exchange']._prefetch(modules=modules, defs=defs, facts=facts)
        return res

    @api.model
    def _knowledge_help_links(self, package, matches, query, ctx):
        """從屬：本地結果（客戶私人說明書等）＋主體公開方案的說明書；同一功能點本地優先。"""
        links = list(super()._knowledge_help_links(package, matches, query, ctx) or [])
        have = {l.get('feature_key') for l in links if l.get('feature_key')}
        for r in self.env['corpaas.knowledge.exchange']._upstream_help(package, query, ctx or {}):
            if not r.get('feature_key') or r['feature_key'] not in have:
                links.append(dict(r, source='master'))
                have.add(r.get('feature_key'))
        return links
