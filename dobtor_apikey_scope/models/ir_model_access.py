# -*- coding: utf-8 -*-
from odoo import models, tools
from odoo.tools import SQL

from .apikey_scope import active_scope_group_ids


class IrModelAccess(models.Model):
    _inherit = 'ir.model.access'

    def _get_allowed_models(self, mode='read'):
        """Core caches the allowed-model set per ``(uid, mode)``. That cache is
        blind to a per-request key scope, so for restricted requests we bypass
        it and use a scope-aware cache keyed by the *narrowed group tuple*
        instead (deterministic, reusable across keys with the same groups, and
        immune to cross-request poisoning)."""
        scope = active_scope_group_ids(self.env)
        if scope is None:
            return super()._get_allowed_models(mode)
        # env.user._get_group_ids() is already narrowed by our res.users override
        group_ids = self.env.user._get_group_ids()
        return self._get_allowed_models_scoped(tuple(sorted(group_ids)), mode)

    @tools.ormcache('group_ids', 'mode')
    def _get_allowed_models_scoped(self, group_ids, mode='read'):
        assert mode in ('read', 'write', 'create', 'unlink'), 'Invalid access mode'
        self.flush_model()
        rows = self.env.execute_query(SQL("""
            SELECT m.model
              FROM ir_model_access a
              JOIN ir_model m ON (m.id = a.model_id)
             WHERE a.perm_%s
               AND a.active
               AND (
                    a.group_id IS NULL OR
                    a.group_id IN %s
                )
            GROUP BY m.model
        """, SQL(mode), tuple(group_ids) or (None,)))
        return frozenset(v[0] for v in rows)
