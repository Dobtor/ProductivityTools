# -*- coding: utf-8 -*-
"""客戶專屬疊加（知識主從計畫第三期，方案 B）：加購與開發模組只疊在該客戶的說明庫。

一筆疊加＝一個客戶在一台說明主機上的一個目錄，底下每個 repo 一個子目錄（依發行標籤抓）。
說明庫掛了疊加：建庫後安裝這些模組；清除、示範資料、探測都在掛了疊加的一次性容器裡跑；
拍照時另起一個只服務這個說明庫的臨時 Odoo（母體容器看不到這些模組）。
"""
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..services import overlay as ov

_logger = logging.getLogger(__name__)


class KnowledgeOverlay(models.Model):
    _name = 'corpaas.knowledge.overlay'
    _description = '客戶專屬疊加模組'
    _order = 'id desc'

    name = fields.Char(required=True)
    partner_id = fields.Many2one('res.partner', string='客戶', index=True)
    server_id = fields.Many2one('infrastructure.server', string='說明主機', required=True)
    line_ids = fields.One2many('corpaas.knowledge.overlay.line', 'overlay_id', string='模組')
    state = fields.Selection([('draft', '待準備'), ('ready', '已就緒'), ('error', '有錯誤')],
                             default='draft', required=True)
    prepared_at = fields.Datetime(readonly=True)
    error = fields.Text(readonly=True)

    def host_dir(self):
        self.ensure_one()
        root = (self.env['ir.config_parameter'].sudo().get_param('corpaas_knowledge.overlay_root')
                or '/opt/odoo/kb_overlay').rstrip('/')
        return '%s/%s' % (root, self.id)

    def module_names(self):
        self.ensure_one()
        return sorted(set(self.line_ids.mapped('module')))

    def repo_dirs(self):
        self.ensure_one()
        return sorted(set(self.line_ids.mapped('repo_dir')) - {False})

    def signature(self):
        """說明庫輸入簽章的一部分：模組或 SHA 變了就要重建。"""
        self.ensure_one()
        return sorted((l.module, l.sha or '') for l in self.line_ids)

    # ------------------------------------------------------------------
    def action_prepare(self):
        """依發行標籤把每個 repo 抓到說明主機；確認每個模組目錄都在。"""
        token = self.env['ir.config_parameter'].sudo().get_param('github.token') or None
        for rec in self:
            errors = []
            fetched = {}
            for line in rec.line_ids:
                try:
                    slug = ov.repo_slug(line.repo_url)
                    key = (line.repo_url, line.ref)
                    if key not in fetched:
                        fetched[key] = ov.fetch(rec.server_id, '%s/%s' % (rec.host_dir(), slug),
                                                line.repo_url, line.ref, token=token)
                    if not ov.has_module(rec.server_id, '%s/%s' % (rec.host_dir(), slug), line.module):
                        raise ov.OverlayError(_('%(r)s@%(t)s 裡沒有模組 %(m)s', r=line.repo_url, t=line.ref,
                                                m=line.module))
                    line.write({'repo_dir': slug, 'sha': fetched[key], 'error': False})
                except Exception as e:  # noqa: BLE001 — 逐筆記錯，其他照抓
                    errors.append('%s：%s' % (line.module, e))
                    line.write({'error': str(e)[:500]})
                    line._report_error(str(e))
            rec.write({'state': 'error' if errors else 'ready', 'error': '\n'.join(errors) or False,
                       'prepared_at': fields.Datetime.now()})
        return True

    def docker_args(self, instance):
        """(掛載參數, addons 路徑參數)：給一次性容器與臨時 Odoo 用。"""
        self.ensure_one()
        if self.state != 'ready':
            raise UserError(_('客戶疊加模組還沒準備好：%s') % (self.error or self.name))
        return ov.docker_args(self.host_dir(), self.repo_dirs(), ov.base_addons_path(self.env, instance))

    @api.model
    def _ensure_for(self, partner, server, modules, name=None):
        """建立或更新某客戶在某台說明主機的疊加；modules：[{module, repo_url, ref, origin, source}]。
        內容有變就回到待準備。"""
        rec = self.sudo().search([('partner_id', '=', partner.id if partner else False),
                                  ('server_id', '=', server.id)], limit=1)
        if not rec:
            rec = self.sudo().create({'name': name or (partner.display_name if partner else _('疊加')),
                                      'partner_id': partner.id if partner else False, 'server_id': server.id})
        want = {(m['module'], m['repo_url'], m['ref']) for m in modules}
        have = {(l.module, l.repo_url, l.ref) for l in rec.line_ids}
        if want != have:
            rec.line_ids.unlink()
            rec.write({'line_ids': [(0, 0, {k: m.get(k) for k in ('module', 'repo_url', 'ref', 'origin', 'source')})
                                    for m in modules], 'state': 'draft'})
        return rec


class KnowledgeOverlayLine(models.Model):
    _name = 'corpaas.knowledge.overlay.line'
    _description = '疊加模組'

    overlay_id = fields.Many2one('corpaas.knowledge.overlay', required=True, ondelete='cascade', index=True)
    module = fields.Char(string='模組', required=True)
    origin = fields.Selection([('addon', '加購'), ('dev', '開發')], string='來源')
    repo_url = fields.Char(string='Repo', required=True)
    ref = fields.Char(string='發行標籤', required=True)
    source = fields.Char(string='來源紀錄', help='model,id：抓不到時把錯誤寫回去（例如開發項目）')
    repo_dir = fields.Char(readonly=True)
    sha = fields.Char(readonly=True)
    error = fields.Char(readonly=True)

    def _report_error(self, message):
        for line in self.filtered('source'):
            model, _sep, rid = line.source.partition(',')
            if model in self.env and rid.isdigit():
                rec = self.env[model].sudo().browse(int(rid)).exists()
                if rec and 'error' in rec._fields:
                    rec.error = _('疊加到說明庫失敗：%s') % message[:500]
