# -*- coding: utf-8 -*-
import contextlib
import threading

from odoo import api, fields, models, tools, SUPERUSER_ID
from odoo.http import request
from odoo.addons.base.models.res_users import (
    check_identity, INDEX_SIZE, KEY_CRYPT_CONTEXT,
)

from .apikey_scope import active_scope_group_ids, _THREAD_ATTR

# Baseline "user type" groups that must never be dropped by a key scope,
# otherwise the request's user would stop being internal/portal and a large
# amount of framework logic (has_group('base.group_user') gates) would break.
FLOOR_GROUP_XMLIDS = (
    'base.group_user',
    'base.group_portal',
    'base.group_public',
)


class ResUsers(models.Model):
    _inherit = 'res.users'

    # ------------------------------------------------------------------
    # Per-call: capture which API key authenticated this RPC call
    # ------------------------------------------------------------------
    @classmethod
    def check(cls, db, uid, passwd):
        """``check`` runs on *every* RPC dispatch (service/model.dispatch), so
        it is the right per-call seam to record the key's scope on the thread.
        Core's credential validation stays cached; only our (also cached)
        scope resolution is added and the thread attribute is (re)set every
        call, so no scope can leak from a previous call on the same thread."""
        # Reset first so a failed auth cannot leave a previous call's scope on
        # this (reusable) worker thread.
        setattr(threading.current_thread(), _THREAD_ATTR, None)
        res = super().check(db, uid, passwd)
        try:
            scope = cls._resolve_apikey_scope(uid, passwd)
        except Exception:  # never let scope resolution break authentication
            scope = None
        setattr(threading.current_thread(), _THREAD_ATTR, scope)
        return res

    @classmethod
    @tools.ormcache('uid', 'passwd')
    def _resolve_apikey_scope(cls, uid, passwd):
        """Map ``(uid, api_key)`` -> tuple of restricted group ids, or ``None``
        when the credential is not a restricted API key (a plain password, an
        unrestricted key, or no matching key). Cached by ``(uid, passwd)`` and
        invalidated via ``registry.clear_cache()`` on scope/key changes."""
        if not passwd:
            return None
        with contextlib.closing(cls.pool.cursor()) as cr:
            env = api.Environment(cr, SUPERUSER_ID, {})
            cr.execute(
                "SELECT id, key FROM res_users_apikeys WHERE user_id = %s AND index = %s",
                (uid, passwd[:INDEX_SIZE]))
            for kid, key_hash in cr.fetchall():
                if KEY_CRYPT_CONTEXT.verify(passwd, key_hash):
                    scope = env['res.users.apikeys.scope'].search(
                        [('apikey_id', '=', kid), ('restrict', '=', True)], limit=1)
                    return tuple(scope.group_ids.ids) if scope else None
        return None

    # ------------------------------------------------------------------
    # The single choke point that narrows effective permissions
    # ------------------------------------------------------------------
    def _get_group_ids(self):
        """Used by model ACLs (``ir.model.access``), record rules
        (``ir.rule._get_rules``) and ``has_group``. When the current call is
        authenticated with a restricted API key, intersect the user's real
        groups with the key's allowed set (plus the mandatory floor). Narrowing
        can only *remove* groups, so it can only tighten access, never widen
        it."""
        full = super()._get_group_ids()
        # Only narrow the current user, and only for restricted-key calls.
        if self.id != self.env.uid:
            return full
        scope = active_scope_group_ids(self.env)
        if scope is None:
            return full

        allowed = set(scope)
        for xmlid in FLOOR_GROUP_XMLIDS:
            grp = self.env.ref(xmlid, raise_if_not_found=False)
            if grp and grp.id in full:
                allowed.add(grp.id)
        return tuple(gid for gid in full if gid in allowed)


class ApiKeyDescription(models.TransientModel):
    _inherit = 'res.users.apikeys.description'

    scope_restrict = fields.Boolean(
        string='Limit permissions', default=False,
        help="Restrict this key to a subset of your access groups. When off, "
             "the key carries your full permissions (standard behaviour).")
    scope_group_ids = fields.Many2many(
        'res.groups', 'apikey_desc_group_rel', 'desc_id', 'group_id',
        string='Allowed Groups',
        default=lambda self: [(6, 0, self.env.user.groups_id.ids)])
    available_group_ids = fields.Many2many(
        'res.groups', compute='_compute_available_group_ids',
        string='Your Groups')

    @api.depends_context('uid')
    def _compute_available_group_ids(self):
        groups = self.env.user.groups_id
        for rec in self:
            rec.available_group_ids = groups

    @check_identity
    def make_key(self):
        # Capture selection before super() unlinks this transient wizard.
        restrict = self.scope_restrict
        group_ids = self.scope_group_ids.ids
        res = super().make_key()
        key_id = getattr(request, 'last_generated_apikey_id', False) if request else False
        if key_id:
            self.env['res.users.apikeys.scope'].sudo().create({
                'apikey_id': key_id,
                'restrict': restrict,
                'group_ids': [(6, 0, group_ids)],
            })
        return res
