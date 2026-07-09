# -*- coding: utf-8 -*-
from odoo import models

from .apikey_scope import active_scope_group_ids


class IrRule(models.Model):
    _inherit = 'ir.rule'

    def _compute_domain_context_values(self):
        """``_compute_domain`` is ormcached with, among others,
        ``tuple(self._compute_domain_context_values())`` in its key. We append
        the active key-scope signature so the computed (narrowed) domain is
        cached *per scope* instead of colliding with the unrestricted domain
        for the same uid. ``_get_rules`` itself already reads the narrowed
        ``_get_group_ids()``, so the domain content is correct -- this only
        fixes the cache key."""
        yield from super()._compute_domain_context_values()
        scope = active_scope_group_ids(self.env)
        yield tuple(sorted(scope)) if scope is not None else None
