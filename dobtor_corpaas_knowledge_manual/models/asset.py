# -*- coding: utf-8 -*-
"""素材的「manual 標註版」：紅框＋編號畫進另一份圖，原圖不動。"""
import base64
import hashlib
import json

from odoo import api, fields, models

from ..services import annotate


class KnowledgeAsset(models.Model):
    _inherit = 'corpaas.knowledge.asset'

    manual_attachment_id = fields.Many2one('ir.attachment', string='標註版圖檔',
                                           ondelete='set null', copy=False)
    manual_regions_key = fields.Char(copy=False, help='畫標註版時的 regions 雜湊')

    def _manual_regions_key(self):
        self.ensure_one()
        return hashlib.sha1((self.regions_json or '[]').encode('utf-8')).hexdigest()[:16]

    def _manual_image_attachment(self):
        """前台用的圖：公開、已標註。regions 變了就重畫。

        ★ public=True：slide 對未登入訪客公開，圖也必須讀得到；原圖不公開（行銷出口
          另行挑選）。
        """
        self.ensure_one()
        asset = self.sudo()
        key = asset._manual_regions_key()
        att = asset.manual_attachment_id
        if att and asset.manual_regions_key == key:
            return att
        if not asset.attachment_id:
            return self.env['ir.attachment']
        png = annotate.draw_regions(asset.attachment_id.raw,
                                    json.loads(asset.regions_json or '[]'))
        vals = {'name': 'manual-%s.png' % asset.shot_name, 'datas': base64.b64encode(png),
                'mimetype': 'image/png', 'public': True,
                'res_model': 'corpaas.knowledge.asset', 'res_id': asset.id}
        if att:
            att.write(vals)
        else:
            att = self.env['ir.attachment'].sudo().create(vals)
        asset.write({'manual_attachment_id': att.id, 'manual_regions_key': key})
        return att

    @api.model
    def _gc_superseded(self, days=30):
        limit = fields.Datetime.subtract(fields.Datetime.now(), days=days)
        self.search([('state', '=', 'superseded'), ('superseded_at', '<', limit)]).mapped(
            'manual_attachment_id').unlink()
        return super()._gc_superseded(days=days)
