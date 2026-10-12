# -*- coding: utf-8 -*-
"""移交（計畫 8.6、已決事項 4）：客戶實例改由主體管理時，把該客戶的私有知識整包送主體。

★ 平常不移交；私有知識只有這條路會出主控台。
★ 同意紀錄：案件負責人在系統內勾「客戶已同意」並填說明；勾選人與時間由系統寫入（不能由 RPC 指定）。
★ 主體收下後仍是私有：不進發佈清單、不出現在其他從屬。
"""
import json

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from odoo.addons.dobtor_corpaas_knowledge.models.federation import console_code

CODE_KINDS = ('code_def', 'module_summary', 'code_fact')


class KnowledgeExchangeTransfer(models.Model):
    _name = 'corpaas.knowledge.exchange.transfer'
    _description = '知識移交'
    _inherit = ['mail.thread']
    _order = 'id desc'

    name = fields.Char(string='移交', required=True, default=lambda s: _('新移交'))
    direction = fields.Selection([('out', '送出（從屬）'), ('in', '收到（主體）')], required=True,
                                 default='out', readonly=True)
    partner_id = fields.Many2one('res.partner', string='客戶', tracking=True)
    partner_name = fields.Char(string='客戶名稱', help='主體收到時記對方給的客戶名稱')
    peer_id = fields.Many2one('corpaas.knowledge.exchange.peer', string='對端', readonly=True)
    module_names = fields.Text(string='移交的模組', required=True, tracking=True,
                               help='一行一個技術名：這些模組的程式知識（含私有）整包移交')
    consent = fields.Boolean(string='客戶已同意', tracking=True, copy=False)
    consent_note = fields.Text(string='同意說明', copy=False,
                               help='客戶如何同意（會議、合約條款、信件…）')
    consent_user_id = fields.Many2one('res.users', string='勾選人', readonly=True, copy=False)
    consent_at = fields.Datetime(string='勾選時間', readonly=True, copy=False)
    state = fields.Selection([('draft', '草稿'), ('sent', '已送出'), ('received', '已收到'),
                              ('cancel', '取消')], default='draft', required=True, tracking=True)
    executor_id = fields.Many2one('res.users', string='執行人', readonly=True, copy=False)
    executed_at = fields.Datetime(string='執行時間', readonly=True, copy=False)
    item_count = fields.Integer(string='筆數', readonly=True, copy=False)
    remote_ref = fields.Char(string='對端參照', readonly=True, copy=False)

    def modules(self):
        self.ensure_one()
        return {m.strip() for m in (self.module_names or '').splitlines() if m.strip()}

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            for f in ('consent_user_id', 'consent_at', 'executor_id', 'executed_at'):
                vals.pop(f, None)
        recs = super().create(vals_list)
        recs.filtered('consent')._stamp_consent()
        return recs

    def write(self, vals):
        # ★ 勾選人與時間只由系統寫：RPC 傳進來的一律丟掉
        if not self.env.context.get('_kbx_transfer_system'):
            for f in ('consent_user_id', 'consent_at', 'executor_id', 'executed_at'):
                vals.pop(f, None)
        if 'consent' in vals and self.filtered(lambda r: r.state != 'draft'):
            raise UserError(_('已送出的移交不能改同意紀錄。'))
        res = super().write(vals)
        if vals.get('consent'):
            self._stamp_consent()
        elif 'consent' in vals:
            self.with_context(_kbx_transfer_system=True).write({'consent_user_id': False, 'consent_at': False})
        return res

    def _stamp_consent(self):
        self.with_context(_kbx_transfer_system=True).write(
            {'consent_user_id': self.env.user.id, 'consent_at': fields.Datetime.now()})

    # ------------------------------------------------------------------
    def _collect_items(self):
        """這些模組的程式知識（含私有）。只有程式知識；客戶情境、建議書等業務資料不在移交範圍。"""
        self.ensure_one()
        mods = self.modules()
        Ex = self.env['corpaas.knowledge.exchange']
        items = []
        for d in Ex._model('code_def').search([('module', 'in', list(mods))]).filtered(lambda r: r._kb_exchange_ready()):
            items.append(d._kb_export())
        for s in Ex._model('module_summary').search([('module', 'in', list(mods))]).filtered(
                lambda r: r._kb_exchange_ready()):
            items.append(s._kb_export())
        for f in Ex._model('code_fact').search([('def_ids.module', 'in', list(mods))]).filtered(
                lambda r: r._kb_exchange_ready()):
            items.append(f._kb_export())
        return items

    def action_send(self):
        """從屬：送出移交。要先勾「客戶已同意」並填說明。"""
        self.ensure_one()
        if self.direction != 'out' or self.state != 'draft':
            raise UserError(_('只有草稿的送出移交可以執行。'))
        if not self.consent or not (self.consent_note or '').strip():
            raise UserError(_('要先勾「客戶已同意」並填寫同意說明。'))
        if not self.modules():
            raise UserError(_('請填要移交的模組。'))
        items = self._collect_items()
        res = self.env['corpaas.knowledge.exchange']._call('transfer', {
            'transfer': {'ref': '%s:%s' % (console_code(self.env), self.id),
                         'partner_name': self.partner_id.display_name or '', 'modules': sorted(self.modules()),
                         'consent_by': self.consent_user_id.name, 'consent_at': str(self.consent_at),
                         'note': self.consent_note},
            'items': items}, timeout=120)
        self.with_context(_kbx_transfer_system=True).write({
            'state': 'sent', 'item_count': len(items), 'remote_ref': res.get('ref') or '',
            'executor_id': self.env.user.id, 'executed_at': fields.Datetime.now()})
        self.message_post(body=_('已移交 %(n)s 筆程式知識給主體（對端參照 %(r)s）。', n=len(items),
                                 r=res.get('ref') or '-'))
        return True

    def action_cancel(self):
        self.filtered(lambda r: r.state == 'draft').write({'state': 'cancel'})
        return True

    @api.model
    def _receive(self, peer, info, items):
        """主體：收下移交。只收宣告範圍內模組的程式知識，入庫後維持私有（不發佈）。"""
        info = info if isinstance(info, dict) else {}
        mods = {m for m in info.get('modules') or [] if isinstance(m, str) and m}
        if not mods or not (info.get('note') or '').strip() or not info.get('consent_by'):
            raise UserError(_('移交缺少範圍或同意紀錄。'))
        rec = self.sudo().with_context(_kbx_transfer_system=True).create({
            'name': _('來自 %s 的移交') % peer.code, 'direction': 'in', 'peer_id': peer.id,
            'partner_name': (info.get('partner_name') or '')[:200], 'module_names': '\n'.join(sorted(mods)),
            'consent': True, 'consent_note': _('對端勾選：%(u)s，%(t)s\n%(n)s', u=info.get('consent_by'),
                                                t=info.get('consent_at'), n=(info.get('note') or '')[:2000]),
            'state': 'received', 'remote_ref': (info.get('ref') or '')[:100]})
        Ex = self.env['corpaas.knowledge.exchange']
        n = 0
        for payload in items or []:
            kind = payload.get('kind') if isinstance(payload, dict) else None
            if kind not in CODE_KINDS or not Ex._payload_modules(kind, payload) or \
                    not Ex._payload_modules(kind, payload) <= mods:
                continue   # 範圍外的不收
            Model = Ex._model(kind)
            existing = Model._kb_find(payload)
            if existing and existing._kb_exchange_ready():
                continue
            # ★ 移交來的是客戶私有：維持私有（不進發佈清單）
            Model._kb_upsert(payload, state='local', trust='replica', origin=peer.code, visibility='private')
            n += 1
        rec.with_context(_kbx_transfer_system=True).write({'item_count': n, 'executed_at': fields.Datetime.now()})
        rec.message_post(body=_('收到 %s 筆程式知識（維持私有）。') % n)
        return rec
