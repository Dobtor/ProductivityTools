# -*- coding: utf-8 -*-
"""行銷內容匯出：給別的網站（白標經銷商的商品頁）顯示同一份已核准的內容。

★ 只送商品頁本來就公開的東西：上線快照（不是編輯中的稿）、目前仍成立的宣稱、
  本期新增那一篇。範圍與商品頁同一套（`_knowledge_marketing_values_unsafe`），
  差別只在方案是明確指定的（目錄項＝方案），不從變體推。
★ 圖片不送網址：本站網址會出現在對方的商品頁上，access_token 也不該外流。
  改成 corpaas-image:<附件 id> 標記，對方再用 API 逐張下載成自己的附件
  （與說明書匯出 `_reseller_manual_export` 同一種做法）。
★ 內文再過一次 html_guard：人工改稿的 Html 欄位只經 Odoo 的一般清洗，
  送到別人的網站前一律收斂成行銷白名單（沒有 <a>、<img>、style）。
★ content_hash：內容沒變 hash 就不變，對方可以跳過下載；什麼都沒有時是 False。
"""
import hashlib
import json

from odoo import models

from . import html_guard

IMAGE_TOKEN = 'corpaas-image:%s'


class SolutionPackageMarketingExport(models.Model):
    _inherit = 'infrastructure.solution.package'

    def _marketing_export(self):
        """(payload, 圖片附件 id 集合)。

        payload = {cards: [{anchor, headline, body_html, claims, images: [{src, alt}],
                   classes}], release_note: {title, date, body_html} | None, content_hash}
        """
        self.ensure_one()
        pkg = self.sudo()
        tmpl = pkg.product_tmpl_id or pkg.product_id.product_tmpl_id
        cards, note, images = [], None, set()
        if tmpl:
            scope = [('product_tmpl_id', '=', tmpl.id),
                     '|', ('package_id', '=', pkg.id), ('package_id', '=', False),
                     ('live_json', '!=', False), ('state', '!=', 'retired')]
            pitches = self.env['corpaas.knowledge.pitch'].sudo().search(
                scope, order='sequence, id')
            assets = pitches._live_assets_map() if pitches else {}
            for pitch, card in zip(pitches, pitches._website_cards(pkg)):
                pics = []
                if not pitch.images_hidden:
                    for asset in assets[pitch.id]:
                        att = asset.attachment_id
                        if not (att.mimetype or '').startswith('image/'):
                            continue
                        images.add(att.id)
                        pics.append({'src': IMAGE_TOKEN % att.id, 'alt': asset.name or ''})
                cards.append({
                    'anchor': card['anchor'],
                    'headline': card['headline'],
                    'body_html': html_guard.clean(card['body_html']),
                    'claims': list(card['claims']),
                    'images': pics,
                    'classes': card.get('classes') or [],
                })
            notes = self.env['corpaas.knowledge.release_note'].sudo().search(
                scope, order='published_date desc, id desc')
            shown = notes._marketing_first_showable(pkg)
            if shown:
                live = shown._website_note()
                note = {'title': live['title'],
                        'date': str(live['date']) if live['date'] else None,
                        'body_html': html_guard.clean(live['body_html'])}
        payload = {'cards': cards, 'release_note': note}
        payload['content_hash'] = hashlib.sha256(
            json.dumps(payload, sort_keys=True, ensure_ascii=False).encode('utf-8')
        ).hexdigest()[:32] if (cards or note) else False
        return payload, images
