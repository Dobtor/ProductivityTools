# -*- coding: utf-8 -*-
import threading

from odoo import api, fields, models
from odoo.http import request

# Reuse the exact constant from core so key-row lookup stays in sync.
from odoo.addons.base.models.res_users import INDEX_SIZE

# Attribute name used on threading.current_thread() to carry the active API
# key's group restriction into the ORM layer (see active_scope_group_ids).
_THREAD_ATTR = 'apikey_scope_group_ids'


def active_scope_group_ids(env):
    """Return the tuple of group ids the *current call's* API key is restricted
    to, or ``None`` when there is no active restriction.

    Why a thread attribute and not the request?
      External API calls arrive via XML-RPC / JSON-RPC, which run inside
      ``odoo.http.dispatch_rpc`` under ``borrow_request()`` -- i.e. the HTTP
      request is *popped off the stack* while the model method executes, so
      ``odoo.http.request`` is falsy there. Odoo itself stashes per-call state
      (``uid``, ``dbname``) on ``threading.current_thread()`` in that same
      dispatch; we do the same for the key scope, set once per call in
      ``ResUsers.check`` (which runs on every RPC dispatch).

    ``None`` (no narrowing) is returned when:
      * running as superuser (``env.su``) -- never cripple framework internals;
      * an HTTP request is bound -- i.e. web-client/session context, which is
        never authenticated by a restricted API key, and this also guarantees
        no stale thread value can leak into a normal web request.
    """
    if env.su:
        return None
    if request:
        return None
    return getattr(threading.current_thread(), _THREAD_ATTR, None)


class ApiKeyScope(models.Model):
    """Per-key permission restriction. Kept in a regular (auto) model rather
    than as extra columns on the ``_auto=False`` ``res.users.apikeys`` model,
    so the ORM manages the table and the m2m relation. Linked to the real key
    row via a FK with ``ON DELETE CASCADE``."""
    _name = 'res.users.apikeys.scope'
    _description = 'API Key Permission Scope'
    _rec_name = 'key_name'

    apikey_id = fields.Many2one(
        'res.users.apikeys', string='API Key',
        required=True, ondelete='cascade', index=True)
    user_id = fields.Many2one(
        'res.users', related='apikey_id.user_id',
        store=True, index=True, readonly=True)
    key_name = fields.Char(related='apikey_id.name', string='Description', readonly=True)
    expiration_date = fields.Datetime(related='apikey_id.expiration_date', readonly=True)
    restrict = fields.Boolean(
        string='Limit Permissions', default=True,
        help="When enabled, any request authenticated with this API key only "
             "carries the selected access groups (intersected with the owner "
             "user's real groups), regardless of the user's full permissions. "
             "Disable to fall back to standard behaviour (full user rights).")
    group_ids = fields.Many2many(
        'res.groups', 'apikey_scope_group_rel', 'scope_id', 'group_id',
        string='Allowed Groups')
    available_group_ids = fields.Many2many(
        'res.groups', compute='_compute_available_group_ids',
        string='Owner Groups',
        help="Groups the owner user actually has. A key can never grant more "
             "than the user owns.")

    _sql_constraints = [
        ('apikey_uniq', 'unique(apikey_id)',
         'A permission scope already exists for this API key.'),
    ]

    @api.depends('user_id')
    def _compute_available_group_ids(self):
        for rec in self:
            rec.available_group_ids = rec.user_id.groups_id

    def _clear_access_caches(self):
        # Invalidate scope resolution (ResUsers._resolve_apikey_scope) and the
        # scoped ACL/rule caches so a scope change takes effect immediately.
        self.env.registry.clear_cache()

    @api.model_create_multi
    def create(self, vals_list):
        recs = super().create(vals_list)
        self._clear_access_caches()
        return recs

    def write(self, vals):
        res = super().write(vals)
        self._clear_access_caches()
        return res

    def unlink(self):
        res = super().unlink()
        self._clear_access_caches()
        return res


class ApiKeys(models.Model):
    _inherit = 'res.users.apikeys'

    def _generate(self, scope, name, expiration_date):
        """Remember the id of the row just created so the (web) wizard can
        attach a permission scope to it -- core ``_generate`` only returns the
        key string. This path runs in the web client, where ``request`` is
        bound (it is not a borrowed-request RPC)."""
        key = super()._generate(scope, name, expiration_date)
        if request:
            self.env.cr.execute(
                "SELECT id FROM res_users_apikeys "
                "WHERE user_id = %s AND index = %s ORDER BY id DESC LIMIT 1",
                (self.env.user.id, key[:INDEX_SIZE]))
            row = self.env.cr.fetchone()
            request.last_generated_apikey_id = row[0] if row else False
        return key

    def _remove(self):
        # Key removal must invalidate the (uid, passwd)->scope resolution cache;
        # the scope row itself is cascade-deleted at DB level (FK), which does
        # not go through the ORM unlink, so clear here explicitly.
        res = super()._remove()
        self.env.registry.clear_cache()
        return res

    def action_manage_scope(self):
        """Self-service entry point: open (creating if needed) the permission
        scope of this key so its owner can adjust it from 'My Profile'. The
        scope record is edited on its own model, governed by this module's ACL
        and record rule (own keys only) -- this never writes ``res.users``, so
        it is unaffected by ``SELF_WRITEABLE_FIELDS`` restrictions."""
        self.ensure_one()
        Scope = self.env['res.users.apikeys.scope'].sudo()
        scope = Scope.search([('apikey_id', '=', self.id)], limit=1)
        if not scope:
            scope = Scope.create({'apikey_id': self.id, 'restrict': False})
        return {
            'type': 'ir.actions.act_window',
            'name': 'API Key Permissions',
            'res_model': 'res.users.apikeys.scope',
            'res_id': scope.id,
            'view_mode': 'form',
            'target': 'new',
        }
